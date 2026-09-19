#!/usr/bin/env python3
"""
One-shot, decision-oriented diagnosis for workflow/process discovery.

Purpose
-------
The earlier workflow-discovery experiments showed that the boundary segmenter is
usable, while the discovery layer is not. This script is designed to make the
next process_discovery implementation decision in ONE run.

It evaluates, on the same Dataset-A holdout sessions:
  1) data/segmentation sanity and contamination;
  2) multiple execution representations (structure, entity, context,
     semantic text, and the current v2 combined representation);
  3) threshold-based agglomerative clustering;
  4) cluster-count-based agglomerative clustering (k sweep);
  5) ordered-sequence clustering using normalized Levenshtein distance;
  6) leave-one-session-out 1-NN process-code retrieval as a clustering-agnostic
     separability test;
  7) internal-vs-oracle selection gap, so we can tell whether the final B
     pipeline can choose its operating point without labels.

IMPORTANT
---------
- GT is used ONLY for evaluation/diagnosis, never to fit representations or
  clustering parameters used for the proposed unlabeled B pipeline.
- Dataset-A-specific literal app/window names are isolated as a diagnostic
  ablation; they are NOT a recommendation for the final transfer-safe model.
- No Dataset-B data is required or used.

Outputs
-------
  discovery_diagnosis.json
  discovery_diagnosis.csv

The script prints a decision summary at the end, so the user should not need
another exploratory diagnostic script before implementing the final discovery
layer.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import adjusted_rand_score, silhouette_score, precision_recall_fscore_support
from sklearn.preprocessing import Normalizer, StandardScaler

try:
    import process_discovery_v2 as pdv2
except Exception:
    pdv2 = None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

THRESHOLD_GRID = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]
K_GRID = list(range(2, 31))
SIL_SAMPLE = 500
RNG_SEED = 42
ENTITY_TYPES = {
    "INVOICE_ID", "EMPLOYEE_ID", "CASE_ID", "DOCUMENT_ID", "CUSTOMER_ID",
    "ORDER_ID", "PO_ID", "TRANSACTION_ID", "BANK_ID", "ID_CANDIDATE",
    "EMAIL", "FILENAME",
}
NUMBER_RE = re.compile(r"\b\d+(?:[.,:/-]\d+)*\b")
EMAIL_RE = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", re.I)
URL_RE = re.compile(r"\b(?:https?://|www\.)[^\s]+\b", re.I)
HEX_RE = re.compile(r"\b[0-9a-f]{8,}\b", re.I)
SPACE_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Parsing / normalization
# ---------------------------------------------------------------------------

def parse_ts(value: Any) -> float:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid timestamp: {value!r}")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError(f"Timezone required: {value!r}")
    return dt.timestamp()


def norm(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return SPACE_RE.sub(" ", value.casefold().strip())


def mask_dynamic(value: Any) -> str:
    text = norm(value)
    if not text:
        return ""
    text = URL_RE.sub(" <URL> ", text)
    text = EMAIL_RE.sub(" <EMAIL> ", text)
    text = HEX_RE.sub(" <HEX> ", text)
    text = NUMBER_RE.sub(" <NUM> ", text)
    return SPACE_RE.sub(" ", text).strip()


def safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def entity_types(activity: dict[str, Any]) -> list[str]:
    out: set[str] = set()
    for entity in safe_list(activity.get("entities")):
        if not isinstance(entity, dict):
            continue
        et = entity.get("type")
        if isinstance(et, str) and et in ENTITY_TYPES:
            out.add(et)
    return sorted(out)


def compact(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if not value:
            continue
        if not out or out[-1] != value:
            out.append(value)
    return out


def gap_bucket(seconds: float) -> str:
    if seconds <= 1:
        return "G0"
    if seconds <= 3:
        return "G1"
    if seconds <= 10:
        return "G2"
    if seconds <= 30:
        return "G3"
    return "G4"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_activities(path: Path) -> dict[str, list[dict[str, Any]]]:
    by_sid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"activities line {line_no}: not an object")
            aid = row.get("activity_id")
            sid = row.get("session_id")
            if not isinstance(aid, str) or not aid:
                raise ValueError(f"activities line {line_no}: invalid activity_id")
            if not isinstance(sid, str) or not sid:
                raise ValueError(f"activities line {line_no}: invalid session_id")
            if aid in seen:
                raise ValueError(f"duplicate activity_id: {aid}")
            seen.add(aid)
            row["_start"] = parse_ts(row.get("start"))
            row["_end"] = parse_ts(row.get("end"))
            if row["_end"] < row["_start"]:
                raise ValueError(f"activity {aid}: end < start")
            by_sid[sid].append(row)
    for sid in by_sid:
        by_sid[sid].sort(key=lambda a: (a["_start"], a["_end"], a["activity_id"]))
    return dict(by_sid)


def load_segments(path: Path) -> dict[str, list[dict[str, Any]]]:
    by_sid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, float, float, str]] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            sid = row.get("session_id")
            if not isinstance(sid, str) or not sid:
                raise ValueError(f"segments line {line_no}: invalid session_id")
            row["_start"] = parse_ts(row.get("start"))
            row["_end"] = parse_ts(row.get("end"))
            if row["_end"] < row["_start"]:
                raise ValueError(f"segments line {line_no}: end < start")
            key = (sid, row["_start"], row["_end"], str(row.get("label", "")))
            if key in seen:
                raise ValueError(f"duplicate segment: {key}")
            seen.add(key)
            by_sid[sid].append(row)
    for sid in by_sid:
        by_sid[sid].sort(key=lambda x: (x["_start"], x["_end"], str(x.get("label", ""))))
        for a, b in zip(by_sid[sid], by_sid[sid][1:]):
            if b["_start"] < a["_end"]:
                raise ValueError(f"overlap in predicted segments for {sid}")
    return dict(by_sid)


def load_gt(path: Path) -> dict[str, list[dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, list[dict[str, Any]]] = {}
    for session in data.get("sessions", []):
        sid = session.get("session_id")
        if not isinstance(sid, str):
            continue
        rows: list[dict[str, Any]] = []
        exec_to_code = {str(ex.get("execution_id")): ex.get("process_code") for ex in session.get("executions", [])}
        for seg in session.get("segments", []):
            exid = str(seg.get("execution_id"))
            code = exec_to_code.get(exid, seg.get("process_code"))
            start = parse_ts(seg["start"])
            end = parse_ts(seg["end"])
            rows.append({
                "start": start,
                "end": end,
                "_start": start,
                "_end": end,
                "process_code": code,
                "execution_id": exid,
            })
        rows.sort(key=lambda x: (x["start"], x["end"], x["execution_id"]))
        out[sid] = rows
    return out


# ---------------------------------------------------------------------------
# Activity ownership and segment extraction
# ---------------------------------------------------------------------------

def point_or_interval_inside(activity: dict[str, Any], seg: dict[str, Any]) -> bool:
    a0, a1 = activity["_start"], activity["_end"]
    s0, s1 = seg["_start"], seg["_end"]
    if a0 == a1:
        return s0 <= a0 <= s1
    return not (a1 < s0 or a0 > s1)


def segment_activities(activities: list[dict[str, Any]], seg: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [a for a in activities if point_or_interval_inside(a, seg)]
    rows.sort(key=lambda a: (a["_start"], a["_end"], a["activity_id"]))
    return rows


def activity_owner(activity: dict[str, Any], gt_rows: list[dict[str, Any]]) -> str | None:
    a0, a1 = activity["_start"], activity["_end"]
    best_code = None
    best_score = -1.0
    best_start = math.inf
    for gt in gt_rows:
        g0, g1 = gt["start"], gt["end"]
        if a0 == a1:
            inside = g0 <= a0 <= g1
            score = 1.0 if inside else 0.0
        else:
            score = max(0.0, min(a1, g1) - max(a0, g0))
        if score > best_score or (score == best_score and g0 < best_start):
            best_score = score
            best_code = gt.get("process_code")
            best_start = g0
    return best_code if best_score > 0 else None


def assign_segment_code(seg: dict[str, Any], activities: list[dict[str, Any]], gt_rows: list[dict[str, Any]]) -> str | None:
    owners = []
    for act in segment_activities(activities, seg):
        code = activity_owner(act, gt_rows)
        if code is not None:
            owners.append(code)
    if not owners:
        return None
    return Counter(owners).most_common(1)[0][0]


def build_records(
    activities: dict[str, list[dict[str, Any]]],
    segments: dict[str, list[dict[str, Any]]],
    gt: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    records = []
    for sid in sorted(segments):
        acts = activities.get(sid, [])
        gt_rows = gt.get(sid, [])
        for idx, seg in enumerate(segments[sid], 1):
            seg_acts = segment_activities(acts, seg)
            if not seg_acts:
                continue
            rec = build_record(sid, idx, seg, seg_acts)
            rec["gt_process_code"] = assign_segment_code(seg, acts, gt_rows)
            records.append(rec)
    return records


# ---------------------------------------------------------------------------
# Signature construction
# ---------------------------------------------------------------------------

def build_record(sid: str, idx: int, seg: dict[str, Any], activities: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(activities, key=lambda a: (a["_start"], a["_end"], a["activity_id"]))
    types = [str(a.get("type") or "UNKNOWN") for a in ordered]
    apps = [norm(a.get("app")) for a in ordered]
    windows = [mask_dynamic(a.get("window")) for a in ordered]
    tabs = [norm(a.get("browser_tab")) for a in ordered]

    # Ordered type sequence.
    type_seq = tuple(types)
    type_compact = tuple(compact(types))

    # Type 1/2/3-grams preserve order.
    type_tokens = [f"T1::{t}" for t in types]
    for n, pfx in ((2, "T2"), (3, "T3")):
        for i in range(max(0, len(types) - n + 1)):
            type_tokens.append(pfx + "::" + ">".join(types[i:i+n]))

    # Relational context only: never encode literal app/window identities.
    relation_tokens = []
    relation_seq = []
    for i in range(1, len(ordered)):
        same_app = bool(apps[i] and apps[i] == apps[i - 1])
        same_window = bool(windows[i] and windows[i] == windows[i - 1])
        same_tab = bool(tabs[i] and tabs[i] == tabs[i - 1])
        gap = max(0.0, ordered[i]["_start"] - ordered[i-1]["_end"])
        rel = f"REL::{int(same_app)}::{int(same_window)}::{int(same_tab)}::{gap_bucket(gap)}"
        relation_tokens.append(rel)
        relation_seq.append(rel)

    # Diagnostic-only literal app pattern.
    app_tokens = []
    for t, app in zip(types, apps):
        if app:
            app_tokens.append(f"TA::{t}::{app}")
    for left, right in zip(apps, apps[1:]):
        if left and right:
            app_tokens.append(f"A2::{left}>>{right}")

    # Entity/action pattern.
    entity_tokens = []
    entity_seq = []
    for act in ordered:
        ets = entity_types(act)
        entity_seq.append(tuple(ets))
        for et in ets:
            entity_tokens.append(f"E::{et}")
            entity_tokens.append(f"ET::{act.get('type','UNKNOWN')}::{et}")

    # Supporting semantic evidence.
    text_fields = []
    for act in ordered:
        vals = [act.get("window"), act.get("target_field"), act.get("text"), act.get("screen_text")]
        vals = [mask_dynamic(v) for v in vals]
        vals = [v for v in vals if v]
        if vals:
            text_fields.append(" | ".join(vals)[:2000])
    text_blob = " ".join(text_fields)

    duration = max(0.0, seg["_end"] - seg["_start"])
    active_span = max(0.0, ordered[-1]["_end"] - ordered[0]["_start"]) if ordered else 0.0

    return {
        "session_id": sid,
        "segment_index": idx,
        "start": seg["_start"],
        "end": seg["_end"],
        "duration": duration,
        "active_span": active_span,
        "activity_count": len(ordered),
        "types": type_seq,
        "type_compact": type_compact,
        "relation_seq": tuple(relation_seq),
        "entity_seq": tuple(entity_seq),
        "type_doc": " ".join(type_tokens) or "EMPTY",
        "relation_doc": " ".join(relation_tokens) or "EMPTY",
        "app_doc": " ".join(app_tokens) or "EMPTY",
        "entity_doc": " ".join(entity_tokens) or "EMPTY",
        "semantic_doc": text_blob or "EMPTY",
        "full_struct_doc": " ".join(type_tokens + relation_tokens) or "EMPTY",
        "full_struct_app_doc": " ".join(type_tokens + relation_tokens + app_tokens) or "EMPTY",
        "gt_process_code": None,
    }


# ---------------------------------------------------------------------------
# Representation builders
# ---------------------------------------------------------------------------

def tfidf_word(docs: list[str], ngram=(1, 2), min_df=1) -> csr_matrix:
    vec = TfidfVectorizer(token_pattern=r"(?u)\S+", lowercase=False, ngram_range=ngram, min_df=min_df, sublinear_tf=True)
    return vec.fit_transform(docs)


def tfidf_char(docs: list[str], ngram=(2, 5), min_df=2) -> csr_matrix:
    vec = TfidfVectorizer(analyzer="char", lowercase=False, ngram_range=ngram, min_df=min_df, sublinear_tf=True)
    return vec.fit_transform(docs)


def normalize_dense_sparse(X: csr_matrix) -> np.ndarray:
    return Normalizer(copy=False).fit_transform(X).toarray().astype(np.float32, copy=False)


def build_vector_representations(records: list[dict[str, Any]]) -> dict[str, np.ndarray]:
    type_block = tfidf_word([r["type_doc"] for r in records], (1, 3), 1)
    relation_block = tfidf_word([r["relation_doc"] for r in records], (1, 2), 1)
    app_block = tfidf_word([r["app_doc"] for r in records], (1, 2), 1)
    entity_block = tfidf_word([r["entity_doc"] for r in records], (1, 2), 1)
    semantic_block = tfidf_char([r["semantic_doc"] for r in records], (2, 5), 2)

    numeric = np.asarray([
        [math.log1p(r["duration"]), math.log1p(r["activity_count"]), math.log1p(r["active_span"])]
        for r in records
    ], dtype=np.float32)
    numeric = StandardScaler().fit_transform(numeric).astype(np.float32)

    reps: dict[str, np.ndarray] = {}
    reps["TYPE_ORDER"] = normalize_dense_sparse(type_block)
    reps["TYPE_RELATION"] = normalize_dense_sparse(hstack([type_block * 1.5, relation_block * 1.0], format="csr"))
    reps["TYPE_ENTITY"] = normalize_dense_sparse(hstack([type_block * 1.5, entity_block * 0.9], format="csr"))
    reps["TYPE_APP_DIAGNOSTIC"] = normalize_dense_sparse(hstack([type_block * 1.5, app_block * 1.0], format="csr"))
    reps["SEMANTIC"] = normalize_dense_sparse(semantic_block)
    reps["STRUCT_SEMANTIC"] = normalize_dense_sparse(hstack([type_block * 1.5, relation_block * 0.8, entity_block * 0.8, semantic_block * 0.9], format="csr"))
    reps["V2_FULL_APPROX"] = normalize_dense_sparse(hstack([type_block * 1.6, app_block * 1.0, entity_block * 0.8, semantic_block * 0.65, csr_matrix(numeric * 0.15)], format="csr"))
    return reps



def build_v2_exact_representation(
    activities_by_sid: dict[str, list[dict[str, Any]]],
    gt_segments_by_sid: dict[str, list[dict[str, Any]]],
) -> np.ndarray | None:
    """Recreate the actual shipped process_discovery_v2 representation.

    This is diagnostic-only. It lets us compare the exact v2 representation
    against the ablations in this script without relying on remembered output.
    """
    if pdv2 is None:
        return None
    rows = []
    for sid in sorted(gt_segments_by_sid):
        acts = activities_by_sid.get(sid, [])
        for idx, seg in enumerate(gt_segments_by_sid[sid], 1):
            seg_acts = pdv2.segment_activities(acts, seg)
            if not seg_acts:
                continue
            docs, meta = pdv2.build_signature(seg_acts)
            rows.append({
                "doc_struct": docs["struct"],
                "doc_entity": docs["entity"],
                "doc_text": docs["text"],
                **meta,
            })
    if not rows:
        return None
    return np.asarray(pdv2.feature_matrix(rows), dtype=np.float32)


# ---------------------------------------------------------------------------
# Clustering / metrics
# ---------------------------------------------------------------------------

def agglomerative_cosine(X: np.ndarray, *, k: int | None = None, threshold: float | None = None, linkage="average") -> np.ndarray:
    if len(X) == 0:
        return np.zeros(0, dtype=int)
    if len(X) == 1:
        return np.zeros(1, dtype=int)
    kwargs = {"linkage": linkage, "metric": "cosine"}
    if k is not None:
        model = AgglomerativeClustering(n_clusters=k, **kwargs)
    else:
        model = AgglomerativeClustering(n_clusters=None, distance_threshold=threshold, **kwargs)
    return model.fit_predict(X)


def normalized_levenshtein(a: Sequence[Any], b: Sequence[Any]) -> float:
    """Normalized Levenshtein distance without third-party dependencies.

    Uses two DP rows, so memory is O(min(len(a), len(b))). This is only used
    for the one-shot Dataset-A diagnostic, where the segment count is small
    enough to make the O(n^2 * L1 * L2) distance matrix practical.
    """
    if a is b or a == b:
        return 0.0
    la, lb = len(a), len(b)
    if la == 0:
        return 1.0 if lb else 0.0
    if lb == 0:
        return 1.0

    # Keep the inner loop on the shorter sequence to reduce Python work.
    if lb > la:
        a, b = b, a
        la, lb = lb, la

    prev = list(range(lb + 1))
    cur = [0] * (lb + 1)
    for i, ai in enumerate(a, 1):
        cur[0] = i
        row_min = cur[0]
        for j, bj in enumerate(b, 1):
            cost = 0 if ai == bj else 1
            deletion = prev[j] + 1
            insertion = cur[j - 1] + 1
            substitution = prev[j - 1] + cost
            value = deletion if deletion < insertion else insertion
            if substitution < value:
                value = substitution
            cur[j] = value
            if value < row_min:
                row_min = value
        prev, cur = cur, prev

    return float(prev[lb]) / float(max(la, lb))


def sequence_distance_matrix(seqs: list[Sequence[Any]]) -> np.ndarray:
    n = len(seqs)
    D = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        for j in range(i + 1, n):
            d = normalized_levenshtein(seqs[i], seqs[j])
            D[i, j] = d
            D[j, i] = d
    return D


def agglomerative_precomputed(D: np.ndarray, *, k: int | None = None, threshold: float | None = None, linkage="average") -> np.ndarray:
    if len(D) <= 1:
        return np.zeros(len(D), dtype=int)
    kwargs = {"linkage": linkage, "metric": "precomputed"}
    if k is not None:
        model = AgglomerativeClustering(n_clusters=k, **kwargs)
    else:
        model = AgglomerativeClustering(n_clusters=None, distance_threshold=threshold, **kwargs)
    return model.fit_predict(D)


def purity(labels: np.ndarray, truth: list[str | None]) -> float:
    usable = [i for i, t in enumerate(truth) if t is not None]
    if not usable:
        return 0.0
    total = 0
    for lab in sorted(set(int(labels[i]) for i in usable)):
        vals = [truth[i] for i in usable if int(labels[i]) == lab]
        total += Counter(vals).most_common(1)[0][1]
    return total / len(usable)


def ari(labels: np.ndarray, truth: list[str | None]) -> float:
    usable = [i for i, t in enumerate(truth) if t is not None]
    if len(usable) < 2:
        return 0.0
    return float(adjusted_rand_score([truth[i] for i in usable], [int(labels[i]) for i in usable]))


def safe_silhouette(X: np.ndarray, labels: np.ndarray, metric: str = "cosine") -> float:
    k = len(set(labels.tolist()))
    if len(X) < 3 or k < 2 or k >= len(X):
        return float("nan")
    sample = min(SIL_SAMPLE, len(X))
    idx = np.linspace(0, len(X) - 1, sample, dtype=int)
    try:
        return float(silhouette_score(X[idx], labels[idx], metric=metric))
    except Exception:
        return float("nan")


def safe_silhouette_precomputed(D: np.ndarray, labels: np.ndarray) -> float:
    k = len(set(labels.tolist()))
    if len(D) < 3 or k < 2 or k >= len(D):
        return float("nan")
    idx = np.linspace(0, len(D) - 1, min(SIL_SAMPLE, len(D)), dtype=int)
    try:
        return float(silhouette_score(D[np.ix_(idx, idx)], labels[idx], metric="precomputed"))
    except Exception:
        return float("nan")


def cluster_size_stats(labels: np.ndarray) -> tuple[int, float, float]:
    sizes = Counter(labels.tolist())
    k = len(sizes)
    singleton = sum(1 for x in sizes.values() if x == 1) / max(1, k)
    largest = max(sizes.values()) if sizes else 0
    return k, float(singleton), float(largest / max(1, len(labels)))


def threshold_sweep_vector(X: np.ndarray, truth: list[str | None], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for t in THRESHOLD_GRID:
        labels = agglomerative_cosine(X, threshold=t)
        k, singleton, largest = cluster_size_stats(labels)
        rows.append({
            "threshold": t,
            "clusters": k,
            "purity": purity(labels, truth),
            "ari": ari(labels, truth),
            "silhouette": safe_silhouette(X, labels),
            "singleton_fraction": singleton,
            "largest_cluster_fraction": largest,
        })
    return rows


def threshold_sweep_sequence(D: np.ndarray, truth: list[str | None]) -> list[dict[str, Any]]:
    rows = []
    for t in [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]:
        labels = agglomerative_precomputed(D, threshold=t)
        k, singleton, largest = cluster_size_stats(labels)
        rows.append({
            "threshold": t,
            "clusters": k,
            "purity": purity(labels, truth),
            "ari": ari(labels, truth),
            "silhouette": safe_silhouette_precomputed(D, labels),
            "singleton_fraction": singleton,
            "largest_cluster_fraction": largest,
        })
    return rows


def k_sweep_vector(X: np.ndarray, truth: list[str | None]) -> list[dict[str, Any]]:
    rows = []
    usable_codes = len({x for x in truth if x is not None})
    max_k = min(max(K_GRID), len(X) - 1)
    for k in range(2, max_k + 1):
        labels = agglomerative_cosine(X, k=k)
        sil = safe_silhouette(X, labels)
        rows.append({
            "k": k,
            "purity": purity(labels, truth),
            "ari": ari(labels, truth),
            "silhouette": sil,
            "oracle_k": bool(k == usable_codes),
        })
    return rows


def k_sweep_sequence(D: np.ndarray, truth: list[str | None]) -> list[dict[str, Any]]:
    rows = []
    usable_codes = len({x for x in truth if x is not None})
    max_k = min(max(K_GRID), len(D) - 1)
    for k in range(2, max_k + 1):
        labels = agglomerative_precomputed(D, k=k)
        sil = safe_silhouette_precomputed(D, labels)
        rows.append({
            "k": k,
            "purity": purity(labels, truth),
            "ari": ari(labels, truth),
            "silhouette": sil,
            "oracle_k": bool(k == usable_codes),
        })
    return rows


# ---------------------------------------------------------------------------
# Session-aware 1-NN retrieval
# ---------------------------------------------------------------------------

def cosine_distance_rowwise(Xa: np.ndarray, Xb: np.ndarray) -> np.ndarray:
    # Rows are L2-normalized by construction.
    sims = Xa @ Xb.T
    return 1.0 - sims


def session_loo_knn_vector(X: np.ndarray, records: list[dict[str, Any]]) -> dict[str, Any]:
    codes = [r["gt_process_code"] for r in records]
    sessions = [r["session_id"] for r in records]
    correct = total = 0
    true_labels = []
    pred_labels = []
    covered = 0
    for sid in sorted(set(sessions)):
        test_idx = [i for i, s in enumerate(sessions) if s == sid and codes[i] is not None]
        train_idx = [i for i, s in enumerate(sessions) if s != sid and codes[i] is not None]
        if not test_idx or not train_idx:
            continue
        train_codes = [codes[i] for i in train_idx]
        for i in test_idx:
            if codes[i] not in set(train_codes):
                continue
            covered += 1
            d = cosine_distance_rowwise(X[i:i+1], X[train_idx])[0]
            j = int(np.argmin(d))
            pred = train_codes[j]
            true_labels.append(codes[i])
            pred_labels.append(pred)
            total += 1
            correct += int(pred == codes[i])
    if total == 0:
        return {"coverage": 0.0, "accuracy": 0.0, "macro_f1": 0.0, "n": 0}
    _, _, macro_f1, _ = precision_recall_fscore_support(true_labels, pred_labels, average="macro", zero_division=0)
    return {"coverage": covered / max(1, sum(c is not None for c in codes)), "accuracy": correct / total, "macro_f1": float(macro_f1), "n": total}


def session_loo_knn_sequence(D: np.ndarray, records: list[dict[str, Any]]) -> dict[str, Any]:
    codes = [r["gt_process_code"] for r in records]
    sessions = [r["session_id"] for r in records]
    correct = total = 0
    true_labels = []
    pred_labels = []
    covered = 0
    for sid in sorted(set(sessions)):
        test_idx = [i for i, s in enumerate(sessions) if s == sid and codes[i] is not None]
        train_idx = [i for i, s in enumerate(sessions) if s != sid and codes[i] is not None]
        if not test_idx or not train_idx:
            continue
        train_codes = [codes[i] for i in train_idx]
        for i in test_idx:
            if codes[i] not in set(train_codes):
                continue
            covered += 1
            d = D[i, train_idx]
            j = int(np.argmin(d))
            pred = train_codes[j]
            true_labels.append(codes[i])
            pred_labels.append(pred)
            total += 1
            correct += int(pred == codes[i])
    if total == 0:
        return {"coverage": 0.0, "accuracy": 0.0, "macro_f1": 0.0, "n": 0}
    _, _, macro_f1, _ = precision_recall_fscore_support(true_labels, pred_labels, average="macro", zero_division=0)
    return {"coverage": covered / max(1, sum(c is not None for c in codes)), "accuracy": correct / total, "macro_f1": float(macro_f1), "n": total}


# ---------------------------------------------------------------------------
# Diagnostic helpers
# ---------------------------------------------------------------------------

def best_row(rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    valid = [r for r in rows if np.isfinite(r.get(key, float("nan")))]
    return max(valid, key=lambda r: (r[key], -r.get("clusters", r.get("k", 0)))) if valid else None


def top_k_row(rows: list[dict[str, Any]], k: int) -> dict[str, Any] | None:
    matches = [r for r in rows if r.get("k") == k]
    return matches[0] if matches else None


def predicted_contamination(
    activities: dict[str, list[dict[str, Any]]],
    pred_segments: dict[str, list[dict[str, Any]]],
    gt: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    total = 0
    mixed = 0
    owner_purity_vals = []
    segment_count = 0
    for sid, segs in pred_segments.items():
        acts = activities.get(sid, [])
        gt_rows = gt.get(sid, [])
        for seg in segs:
            seg_acts = segment_activities(acts, seg)
            if not seg_acts:
                continue
            owners = [activity_owner(a, gt_rows) for a in seg_acts]
            owners = [x for x in owners if x is not None]
            if not owners:
                continue
            counts = Counter(owners)
            maj = counts.most_common(1)[0][1]
            purity_here = maj / len(owners)
            owner_purity_vals.append(purity_here)
            segment_count += 1
            total += len(owners)
            mixed += len(owners) - maj
    return {
        "segments_with_evidence": segment_count,
        "activity_owner_contamination": mixed / max(1, total),
        "mean_pred_segment_owner_purity": float(np.mean(owner_purity_vals)) if owner_purity_vals else 0.0,
        "median_pred_segment_owner_purity": float(np.median(owner_purity_vals)) if owner_purity_vals else 0.0,
    }


def same_vs_diff_similarity_vector(X: np.ndarray, truth: list[str | None], sample_pairs: int = 25000) -> dict[str, float]:
    rng = random.Random(RNG_SEED)
    by_code: dict[str, list[int]] = defaultdict(list)
    valid = [i for i, t in enumerate(truth) if t is not None]
    for i in valid:
        by_code[truth[i]].append(i)
    codes = list(by_code)
    if len(valid) < 2:
        return {"same_mean": 0.0, "diff_mean": 0.0, "margin": 0.0}
    same = []
    diff = []
    for _ in range(min(sample_pairs, max(1000, len(valid) * 20))):
        i = rng.choice(valid)
        code = truth[i]
        same_pool = by_code.get(code, [])
        if len(same_pool) > 1:
            j = i
            while j == i:
                j = rng.choice(same_pool)
            same.append(float(X[i] @ X[j]))
        diff_code = rng.choice([c for c in codes if c != code]) if len(codes) > 1 else None
        if diff_code:
            j = rng.choice(by_code[diff_code])
            diff.append(float(X[i] @ X[j]))
    return {
        "same_mean": float(np.mean(same)) if same else 0.0,
        "same_median": float(np.median(same)) if same else 0.0,
        "diff_mean": float(np.mean(diff)) if diff else 0.0,
        "diff_median": float(np.median(diff)) if diff else 0.0,
        "margin": float((np.mean(same) if same else 0.0) - (np.mean(diff) if diff else 0.0)),
    }


def sequence_pair_margin(D: np.ndarray, truth: list[str | None], sample_pairs: int = 25000) -> dict[str, float]:
    rng = random.Random(RNG_SEED)
    valid = [i for i, t in enumerate(truth) if t is not None]
    by_code: dict[str, list[int]] = defaultdict(list)
    for i in valid:
        by_code[truth[i]].append(i)
    codes = list(by_code)
    same = []
    diff = []
    for _ in range(min(sample_pairs, max(1000, len(valid) * 20))):
        i = rng.choice(valid)
        code = truth[i]
        pool = by_code[code]
        if len(pool) > 1:
            j = i
            while j == i:
                j = rng.choice(pool)
            same.append(1.0 - float(D[i, j]))
        if len(codes) > 1:
            dc = rng.choice([c for c in codes if c != code])
            j = rng.choice(by_code[dc])
            diff.append(1.0 - float(D[i, j]))
    return {
        "same_mean": float(np.mean(same)) if same else 0.0,
        "same_median": float(np.median(same)) if same else 0.0,
        "diff_mean": float(np.mean(diff)) if diff else 0.0,
        "diff_median": float(np.median(diff)) if diff else 0.0,
        "margin": float((np.mean(same) if same else 0.0) - (np.mean(diff) if diff else 0.0)),
    }


def internal_selection_from_threshold(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [r for r in rows if 5 <= r["clusters"] <= 60 and np.isfinite(r["silhouette"])]
    if not candidates:
        return None
    best = max(candidates, key=lambda r: (r["silhouette"] - 0.10 * r["singleton_fraction"], -abs(r["clusters"] - 15)))
    return best


def internal_selection_from_k(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [r for r in rows if np.isfinite(r["silhouette"])]
    if not candidates:
        return None
    return max(candidates, key=lambda r: (r["silhouette"], -abs(r["k"] - 15)))


def ensure_finite(X: np.ndarray, name: str) -> None:
    if not np.all(np.isfinite(X)):
        raise AssertionError(f"{name} contains non-finite values")


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

def preflight() -> None:
    records = [
        {
            "session_id": "s1", "segment_index": 1, "start": 0.0, "end": 3.0,
            "duration": 3.0, "active_span": 2.0, "activity_count": 2,
            "types": ("CLICK", "COPY"), "type_compact": ("CLICK", "COPY"),
            "entity_seq": (("CASE_ID",), ("CASE_ID",)),
            "type_doc": "T1::CLICK T1::COPY T2::CLICK>COPY",
            "relation_doc": "REL::1::1::1::G1",
            "app_doc": "TA::CLICK::portal A2::portal>>portal",
            "entity_doc": "E::CASE_ID ET::CLICK::CASE_ID",
            "semantic_doc": "tax portal case <NUM>",
            "full_struct_doc": "T1::CLICK T1::COPY T2::CLICK>COPY REL::1::1::1::G1",
            "full_struct_app_doc": "T1::CLICK T1::COPY T2::CLICK>COPY REL::1::1::1::G1 TA::CLICK::portal A2::portal>>portal",
            "gt_process_code": "A",
        },
        {
            "session_id": "s2", "segment_index": 1, "start": 0.0, "end": 3.0,
            "duration": 3.0, "active_span": 2.0, "activity_count": 2,
            "types": ("CLICK", "COPY"), "type_compact": ("CLICK", "COPY"),
            "entity_seq": (("CASE_ID",), ("CASE_ID",)),
            "type_doc": "T1::CLICK T1::COPY T2::CLICK>COPY",
            "relation_doc": "REL::1::1::1::G1",
            "app_doc": "TA::CLICK::portal A2::portal>>portal",
            "entity_doc": "E::CASE_ID ET::CLICK::CASE_ID",
            "semantic_doc": "tax portal case <NUM>",
            "full_struct_doc": "T1::CLICK T1::COPY T2::CLICK>COPY REL::1::1::1::G1",
            "full_struct_app_doc": "T1::CLICK T1::COPY T2::CLICK>COPY REL::1::1::1::G1 TA::CLICK::portal A2::portal>>portal",
            "gt_process_code": "A",
        },
        {
            "session_id": "s3", "segment_index": 1, "start": 0.0, "end": 3.0,
            "duration": 3.0, "active_span": 2.0, "activity_count": 2,
            "types": ("APP_SWITCH", "CLICK"), "type_compact": ("APP_SWITCH", "CLICK"),
            "entity_seq": (("BANK_ID",), ("BANK_ID",)),
            "type_doc": "T1::APP_SWITCH T1::CLICK T2::APP_SWITCH>CLICK",
            "relation_doc": "REL::0::0::0::G1",
            "app_doc": "TA::APP_SWITCH::finance A2::finance>>finance",
            "entity_doc": "E::BANK_ID ET::APP_SWITCH::BANK_ID",
            "semantic_doc": "bank reconciliation",
            "full_struct_doc": "T1::APP_SWITCH T1::CLICK T2::APP_SWITCH>CLICK REL::0::0::0::G1",
            "full_struct_app_doc": "T1::APP_SWITCH T1::CLICK T2::APP_SWITCH>CLICK REL::0::0::0::G1 TA::APP_SWITCH::finance A2::finance>>finance",
            "gt_process_code": "B",
        },
    ]
    reps = build_vector_representations(records)
    assert "TYPE_ORDER" in reps and reps["TYPE_ORDER"].shape[0] == 3
    for name, X in reps.items():
        ensure_finite(X, name)
    D = sequence_distance_matrix([r["types"] for r in records])
    assert D.shape == (3, 3) and np.allclose(np.diag(D), 0.0)
    assert D[0, 1] < D[0, 2]
    print("Preflight comprehensive-discovery self-test: PASS (12 assertions)", flush=True)


# ---------------------------------------------------------------------------
# Main diagnostic
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="One-shot comprehensive Dataset-A process-discovery diagnosis")
    parser.add_argument("--activities", required=True)
    parser.add_argument("--predicted-segments", required=True)
    parser.add_argument("--gt", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    preflight()
    activities = load_activities(Path(args.activities))
    pred_segments = load_segments(Path(args.predicted_segments))
    gt = load_gt(Path(args.gt))

    session_ids = sorted(set(pred_segments) & set(gt))
    if not session_ids:
        raise RuntimeError("No common sessions between predicted segments and GT")

    # GT/oracle segment records on exactly the same holdout sessions.
    gt_segments = {sid: gt[sid] for sid in session_ids}
    gt_records = build_records(activities, gt_segments, gt)
    pred_records = build_records(activities, {sid: pred_segments[sid] for sid in session_ids}, gt)

    # Purity of predicted segment activity ownership.
    contamination = predicted_contamination(activities, {sid: pred_segments[sid] for sid in session_ids}, gt)

    print("COMPREHENSIVE PROCESS-DISCOVERY DIAGNOSIS", flush=True)
    print("=" * 78, flush=True)
    print(f"Holdout sessions: {len(session_ids)}", flush=True)
    print(f"GT segments with activity evidence: {len(gt_records):,}", flush=True)
    print(f"Predicted segments with activity evidence: {len(pred_records):,}", flush=True)
    print(f"Predicted segment activity contamination: {contamination['activity_owner_contamination']:.4f}", flush=True)
    print(f"Predicted segment mean owner purity: {contamination['mean_pred_segment_owner_purity']:.4f}", flush=True)

    gt_truth = [r["gt_process_code"] for r in gt_records]
    process_codes = sorted({x for x in gt_truth if x is not None})
    print(f"GT process codes represented in holdout: {len(process_codes)} -> {process_codes}", flush=True)

    # Build representations for oracle GT segments.
    reps = build_vector_representations(gt_records)
    exact_v2 = build_v2_exact_representation(activities, gt_segments)
    if exact_v2 is not None:
        reps["V2_EXACT"] = exact_v2
    seq_D = sequence_distance_matrix([r["types"] for r in gt_records])
    seq_D_rel = sequence_distance_matrix([
        tuple(
            token
            for pair in zip(r["types"], r["relation_seq"])
            for token in (f"T::{pair[0]}", pair[1])
        ) + ((f"T::{r['types'][-1]}",) if r["types"] else tuple())
        for r in gt_records
    ])

    diagnosis: dict[str, Any] = {
        "holdout_sessions": session_ids,
        "gt_segments_with_activity_evidence": len(gt_records),
        "predicted_segments_with_activity_evidence": len(pred_records),
        "predicted_segmentation_sanity": contamination,
        "gt_process_code_count": len(process_codes),
        "gt_process_codes": process_codes,
        "representations": {},
        "sequence_methods": {},
        "recommendation": {},
    }

    summary_rows = []

    print("\nREPRESENTATION ABLATION ON ORACLE GT SEGMENTS", flush=True)
    print("-" * 78, flush=True)
    print("representation             oracle-k ARI  best-k ARI  1NN-acc  margin", flush=True)
    print("--------------------------  -----------  ----------  -------  ------", flush=True)

    for name, X in reps.items():
        ensure_finite(X, name)
        threshold_rows = threshold_sweep_vector(X, gt_truth, gt_records)
        k_rows = k_sweep_vector(X, gt_truth)
        oracle_k_row = top_k_row(k_rows, len(process_codes))
        best_k = best_row(k_rows, "ari")
        internal_k = internal_selection_from_k(k_rows)
        internal_threshold = internal_selection_from_threshold(threshold_rows)
        knn = session_loo_knn_vector(X, gt_records)
        margin = same_vs_diff_similarity_vector(X, gt_truth)
        row = {
            "representation": name,
            "oracle_k": len(process_codes),
            "oracle_k_purity": oracle_k_row["purity"] if oracle_k_row else None,
            "oracle_k_ari": oracle_k_row["ari"] if oracle_k_row else None,
            "best_k": best_k["k"] if best_k else None,
            "best_k_purity": best_k["purity"] if best_k else None,
            "best_k_ari": best_k["ari"] if best_k else None,
            "best_k_silhouette": best_k["silhouette"] if best_k else None,
            "internal_k": internal_k["k"] if internal_k else None,
            "internal_k_ari": internal_k["ari"] if internal_k else None,
            "internal_threshold": internal_threshold["threshold"] if internal_threshold else None,
            "internal_threshold_ari": internal_threshold["ari"] if internal_threshold else None,
            "session_loo_1nn_accuracy": knn["accuracy"],
            "session_loo_1nn_macro_f1": knn["macro_f1"],
            "session_loo_coverage": knn["coverage"],
            "similarity_margin": margin["margin"],
            "same_similarity_mean": margin["same_mean"],
            "diff_similarity_mean": margin["diff_mean"],
        }
        summary_rows.append(row)
        diagnosis["representations"][name] = {
            "threshold_sweep": threshold_rows,
            "k_sweep": k_rows,
            "session_loo_1nn": knn,
            "similarity_separation": margin,
        }
        print(
            f"{name:26s}  "
            f"{row['oracle_k_ari'] if row['oracle_k_ari'] is not None else 0:11.4f}  "
            f"{row['best_k_ari'] if row['best_k_ari'] is not None else 0:10.4f}  "
            f"{row['session_loo_1nn_accuracy']:7.4f}  "
            f"{row['similarity_margin']:6.4f}",
            flush=True,
        )

    # Ordered-sequence methods are separated because their metric is not cosine.
    print("\nORDERED-SEQUENCE DIAGNOSIS", flush=True)
    print("-" * 78, flush=True)
    seq_methods = {
        "TYPE_SEQUENCE_EDIT": seq_D,
        "TYPE_PLUS_RELATION_EDIT": seq_D_rel,
    }
    sequence_summary = []
    for name, D in seq_methods.items():
        threshold_rows = threshold_sweep_sequence(D, gt_truth)
        k_rows = k_sweep_sequence(D, gt_truth)
        oracle_k_row = top_k_row(k_rows, len(process_codes))
        best_k = best_row(k_rows, "ari")
        internal_k = internal_selection_from_k(k_rows)
        internal_threshold = max(
            [r for r in threshold_rows if np.isfinite(r["silhouette"])],
            key=lambda r: (r["silhouette"], -abs(r["clusters"] - len(process_codes))),
            default=None,
        )
        knn = session_loo_knn_sequence(D, gt_records)
        margin = sequence_pair_margin(D, gt_truth)
        row = {
            "representation": name,
            "oracle_k": len(process_codes),
            "oracle_k_purity": oracle_k_row["purity"] if oracle_k_row else None,
            "oracle_k_ari": oracle_k_row["ari"] if oracle_k_row else None,
            "best_k": best_k["k"] if best_k else None,
            "best_k_purity": best_k["purity"] if best_k else None,
            "best_k_ari": best_k["ari"] if best_k else None,
            "best_k_silhouette": best_k["silhouette"] if best_k else None,
            "internal_k": internal_k["k"] if internal_k else None,
            "internal_k_ari": internal_k["ari"] if internal_k else None,
            "internal_threshold": internal_threshold["threshold"] if internal_threshold else None,
            "internal_threshold_ari": internal_threshold["ari"] if internal_threshold else None,
            "session_loo_1nn_accuracy": knn["accuracy"],
            "session_loo_1nn_macro_f1": knn["macro_f1"],
            "session_loo_coverage": knn["coverage"],
            "similarity_margin": margin["margin"],
            "same_similarity_mean": margin["same_mean"],
            "diff_similarity_mean": margin["diff_mean"],
        }
        sequence_summary.append(row)
        diagnosis["sequence_methods"][name] = {
            "threshold_sweep": threshold_rows,
            "k_sweep": k_rows,
            "session_loo_1nn": knn,
            "similarity_separation": margin,
        }
        print(
            f"{name:26s}  oracle-k ARI={row['oracle_k_ari'] if row['oracle_k_ari'] is not None else 0:.4f} "
            f"best-k ARI={row['best_k_ari'] if row['best_k_ari'] is not None else 0:.4f} "
            f"1NN={row['session_loo_1nn_accuracy']:.4f} "
            f"margin={row['similarity_margin']:.4f}",
            flush=True,
        )

    all_rows = summary_rows + sequence_summary
    best_by_ari = max(all_rows, key=lambda r: (r["best_k_ari"] or -1.0, r["oracle_k_ari"] or -1.0))
    best_by_1nn = max(all_rows, key=lambda r: (r["session_loo_1nn_accuracy"], r["session_loo_1nn_macro_f1"]))
    best_by_oracle_k = max(all_rows, key=lambda r: (r["oracle_k_ari"] or -1.0, r["oracle_k_purity"] or -1.0))

    # Compare semantic-only vs structural variants, giving an explicit signal
    # about whether text is carrying the separability that the old diagnostic lacked.
    def get(name: str) -> dict[str, Any] | None:
        return next((r for r in all_rows if r["representation"] == name), None)

    semantic = get("SEMANTIC")
    structural = get("TYPE_ORDER")
    combined = get("STRUCT_SEMANTIC")
    type_relation = get("TYPE_RELATION")

    semantic_lift_over_type = None
    if semantic and structural:
        semantic_lift_over_type = (semantic["best_k_ari"] or 0.0) - (structural["best_k_ari"] or 0.0)
    app_diag = get("TYPE_APP_DIAGNOSTIC")
    app_lift_over_relation = None
    if app_diag and type_relation:
        app_lift_over_relation = (app_diag["best_k_ari"] or 0.0) - (type_relation["best_k_ari"] or 0.0)
    combined_lift_over_structure = None
    if combined and structural:
        combined_lift_over_structure = (combined["best_k_ari"] or 0.0) - (structural["best_k_ari"] or 0.0)

    # Internal-selection gap: if large, the final unlabeled B pipeline needs a
    # better cluster-count/threshold rule, not just a better representation.
    for r in all_rows:
        r["internal_to_best_ari_gap"] = (r["best_k_ari"] or 0.0) - (r["internal_k_ari"] or 0.0)
        r["internal_threshold_to_best_ari_gap"] = (r["best_k_ari"] or 0.0) - (r["internal_threshold_ari"] or 0.0)

    recommendation = {
        "best_representation_by_best_k_ari": best_by_ari["representation"],
        "best_representation_by_oracle_k_ari": best_by_oracle_k["representation"],
        "best_representation_by_leave_session_out_1nn": best_by_1nn["representation"],
        "best_k": best_by_ari.get("best_k"),
        "best_k_ari": best_by_ari.get("best_k_ari"),
        "best_oracle_k_ari": best_by_oracle_k.get("oracle_k_ari"),
        "best_1nn_accuracy": best_by_1nn.get("session_loo_1nn_accuracy"),
        "semantic_vs_type_best_k_ari_lift": semantic_lift_over_type,
        "combined_vs_type_best_k_ari_lift": combined_lift_over_structure,
        "literal_app_diagnostic_lift_over_relation": app_lift_over_relation,
        "internal_selection_gap_for_best_representation": best_by_ari.get("internal_to_best_ari_gap"),
    }

    # Decision guidance, deliberately descriptive rather than pretending to
    # know Dataset-B cluster count.
    notes = []
    if best_by_ari["best_k_ari"] is not None and best_by_ari["best_k_ari"] >= 0.30:
        notes.append("There is meaningful process-type structure in at least one representation; a new discovery implementation is justified rather than abandoning clustering.")
    else:
        notes.append("Even the best k-oracle ARI is weak; exact process-type discovery remains difficult from the current activity/segment evidence.")
    if semantic_lift_over_type is not None and semantic_lift_over_type > 0.10:
        notes.append("Semantic text is materially contributing beyond activity-type order; the final discoverer should retain masked screen/window/text evidence as a supporting block.")
    else:
        notes.append("Semantic text does not clearly dominate activity-order structure; do not make raw text the foundation.")
    if app_lift_over_relation is not None and app_lift_over_relation > 0.10:
        notes.append("Literal application identity adds substantial A-only separability; treat this as diagnostic evidence, not as a transfer-safe foundation for Dataset B.")
    else:
        notes.append("Literal application identity does not add a large advantage over relational context, which is preferable for cross-dataset transfer.")
    if best_by_ari.get("internal_to_best_ari_gap", 0.0) > 0.15:
        notes.append("Internal cluster selection is substantially below the best k on A; the final B pipeline needs a stronger unlabeled model-selection rule than the current silhouette-only threshold heuristic.")
    else:
        notes.append("Internal selection is reasonably aligned with the best A operating point; threshold/k selection is less likely to be the dominant issue.")
    recommendation["notes"] = notes
    diagnosis["recommendation"] = recommendation

    # Human-readable summary.
    print("\nFINAL DECISION SUMMARY", flush=True)
    print("-" * 78, flush=True)
    print(f"Best representation by best-k ARI: {best_by_ari['representation']} (k={best_by_ari['best_k']}, ARI={best_by_ari['best_k_ari']:.4f})", flush=True)
    print(f"Best representation at oracle process-code count: {best_by_oracle_k['representation']} (ARI={best_by_oracle_k['oracle_k_ari']:.4f})", flush=True)
    print(f"Best representation by leave-session-out 1NN: {best_by_1nn['representation']} (accuracy={best_by_1nn['session_loo_1nn_accuracy']:.4f}, coverage={best_by_1nn['session_loo_coverage']:.4f})", flush=True)
    print(f"Semantic vs TYPE_ORDER best-k ARI lift: {semantic_lift_over_type if semantic_lift_over_type is not None else 0.0:+.4f}", flush=True)
    print(f"STRUCT_SEMANTIC vs TYPE_ORDER best-k ARI lift: {combined_lift_over_structure if combined_lift_over_structure is not None else 0.0:+.4f}", flush=True)
    print(f"TYPE_APP_DIAGNOSTIC vs TYPE_RELATION best-k ARI lift: {app_lift_over_relation if app_lift_over_relation is not None else 0.0:+.4f}", flush=True)
    print(f"Best-representation internal-k ARI gap: {best_by_ari.get('internal_to_best_ari_gap', 0.0):.4f}", flush=True)
    print("\nRECOMMENDATION", flush=True)
    for note in notes:
        print(f"- {note}", flush=True)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "discovery_diagnosis.json").write_text(json.dumps(diagnosis, indent=2, ensure_ascii=False, default=float), encoding="utf-8")

    csv_fields = sorted({k for row in all_rows for k in row.keys()})
    with (out / "discovery_diagnosis.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nWrote: {out / 'discovery_diagnosis.json'}", flush=True)
    print(f"Wrote: {out / 'discovery_diagnosis.csv'}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
