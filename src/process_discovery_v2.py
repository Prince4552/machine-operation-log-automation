#!/usr/bin/env python3
"""
Process/workflow discovery v2.

Design:
  - Cluster recovered segments (or execution-like records) using ordered
    workflow structure first, with context/entity evidence and lightweight
    semantic text as supporting evidence.
  - Fit independently on the supplied dataset. Dataset-A process labels are
    never features and are never used to fit clusters.
  - Deterministic enough for reruns: all input records are canonically sorted,
    random states are fixed, and cluster labels are remapped by canonical time.

Inputs:
  --activities activities.jsonl
  --segments   recovered segment JSONL
  --gt         optional Dataset-A GT JSON for validation only

Outputs:
  segments_labeled.jsonl
  discovery_report.json
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import Normalizer, StandardScaler

ENTITY_TYPES = {
    "INVOICE_ID", "EMPLOYEE_ID", "CASE_ID", "DOCUMENT_ID", "CUSTOMER_ID",
    "ORDER_ID", "PO_ID", "TRANSACTION_ID", "BANK_ID", "ID_CANDIDATE",
    "EMAIL", "FILENAME",
}

# A deliberately broad, unsupervised grid. We select with internal structure,
# not Dataset-A labels.
DEFAULT_DISTANCE_GRID = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65]
MIN_CLUSTERS = 5
MAX_CLUSTERS = 40
SILHOUETTE_SAMPLE = 500

NUMBER_RE = re.compile(r"\b\d+(?:[.,:/-]\d+)*\b")
EMAIL_RE = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", re.I)
URL_RE = re.compile(r"\b(?:https?://|www\.)[^\s]+\b", re.I)
HEX_RE = re.compile(r"\b[0-9a-f]{8,}\b", re.I)
SPACE_RE = re.compile(r"\s+")


def parse_ts(value: Any) -> float:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid timestamp: {value!r}")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError(f"Timestamp must contain timezone: {value!r}")
    return dt.timestamp()


def norm(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return SPACE_RE.sub(" ", value.casefold().strip())


def safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def mask_dynamic_text(value: Any) -> str:
    text = norm(value)
    if not text:
        return ""
    text = URL_RE.sub(" <URL> ", text)
    text = EMAIL_RE.sub(" <EMAIL> ", text)
    text = HEX_RE.sub(" <HEX> ", text)
    text = NUMBER_RE.sub(" <NUM> ", text)
    return SPACE_RE.sub(" ", text).strip()


def entity_types(activity: dict[str, Any]) -> list[str]:
    out = []
    for entity in safe_list(activity.get("entities")):
        if not isinstance(entity, dict):
            continue
        et = entity.get("type")
        if isinstance(et, str) and et in ENTITY_TYPES:
            out.append(et)
    return sorted(set(out))


def compact(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if not value:
            continue
        if not out or out[-1] != value:
            out.append(value)
    return out


def load_activities(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.exists():
        raise FileNotFoundError(path)
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
                raise ValueError(f"activities line {line_no}: missing activity_id")
            if not isinstance(sid, str) or not sid:
                raise ValueError(f"activities line {line_no}: missing session_id")
            if aid in seen:
                raise ValueError(f"duplicate activity_id: {aid}")
            seen.add(aid)
            start = parse_ts(row.get("start"))
            end = parse_ts(row.get("end"))
            if end < start:
                raise ValueError(f"activity {aid}: end < start")
            row["_start"] = start
            row["_end"] = end
            by_sid[sid].append(row)
    for sid in by_sid:
        by_sid[sid].sort(key=lambda x: (x["_start"], x["_end"], x["activity_id"]))
    return dict(by_sid)


def load_segments(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.exists():
        raise FileNotFoundError(path)
    by_sid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, float, float]] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"segments line {line_no}: not an object")
            sid = row.get("session_id")
            if not isinstance(sid, str) or not sid:
                raise ValueError(f"segments line {line_no}: missing session_id")
            start = parse_ts(row.get("start"))
            end = parse_ts(row.get("end"))
            if end < start:
                raise ValueError(f"segments line {line_no}: end < start")
            key = (sid, start, end)
            if key in seen:
                raise ValueError(f"duplicate segment interval: {key}")
            seen.add(key)
            row["_start"] = start
            row["_end"] = end
            by_sid[sid].append(row)
    for sid, rows in by_sid.items():
        rows.sort(key=lambda x: (x["_start"], x["_end"], x.get("label", "")))
        for left, right in zip(rows, rows[1:]):
            if right["_start"] < left["_end"]:
                raise ValueError(f"overlapping segments in session {sid}")
    return dict(by_sid)


def load_gt_codes(path: Path) -> dict[str, list[dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, list[dict[str, Any]]] = {}
    for session in data.get("sessions", []):
        sid = session.get("session_id")
        if not isinstance(sid, str):
            continue
        rows: list[dict[str, Any]] = []
        execs = session.get("executions", [])
        for ex in execs:
            ex_id = ex.get("execution_id")
            code = ex.get("process_code")
            for seg in session.get("segments", []):
                if seg.get("execution_id") == ex_id:
                    rows.append({
                        "start": parse_ts(seg["start"]),
                        "end": parse_ts(seg["end"]),
                        "process_code": code,
                        "execution_id": ex_id,
                    })
        if not rows:
            for seg in session.get("segments", []):
                rows.append({
                    "start": parse_ts(seg["start"]),
                    "end": parse_ts(seg["end"]),
                    "process_code": seg.get("process_code"),
                    "execution_id": seg.get("execution_id"),
                })
        rows.sort(key=lambda x: (x["start"], x["end"], str(x["execution_id"])))
        out[sid] = rows
    return out


def overlap_seconds(a0: float, a1: float, b0: float, b1: float) -> float:
    if a0 == a1:
        return 1.0 if b0 <= a0 <= b1 else 0.0
    if b0 == b1:
        return 1.0 if a0 <= b0 <= a1 else 0.0
    return max(0.0, min(a1, b1) - max(a0, b0))


def segment_activities(activities: list[dict[str, Any]], segment: dict[str, Any]) -> list[dict[str, Any]]:
    s0, s1 = segment["_start"], segment["_end"]
    return [a for a in activities if not (a["_end"] < s0 or a["_start"] > s1)]


def build_signature(activities: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, Any]]:
    ordered = sorted(activities, key=lambda x: (x["_start"], x["_end"], x["activity_id"]))
    types = [str(a.get("type") or "UNKNOWN") for a in ordered]
    apps = [norm(a.get("app")) for a in ordered]
    windows = [mask_dynamic_text(a.get("window")) for a in ordered]

    # Structural stream: 1/2/3-grams preserve local order.
    structural: list[str] = []
    for x in types:
        structural.append(f"T1::{x}")
    for n, prefix in ((2, "T2"), (3, "T3")):
        for i in range(len(types) - n + 1):
            structural.append(prefix + "::" + ">".join(types[i:i + n]))

    # Type + application gives a more meaningful action-context sequence.
    for typ, app in zip(types, apps):
        if app:
            structural.append(f"TA::{typ}::{app}")

    # Application transitions, including repeated use counts through tokens.
    for left, right in zip(apps, apps[1:]):
        if left and right:
            structural.append(f"A2::{left}>>{right}")

    # Context-change pattern: whether the operator stayed in the same UI context.
    for i in range(1, len(ordered)):
        gap = max(0.0, ordered[i]["_start"] - ordered[i - 1]["_end"])
        same_app = bool(apps[i] and apps[i] == apps[i - 1])
        same_window = bool(windows[i] and windows[i] == windows[i - 1])
        gap_bin = "G0" if gap <= 1 else "G1" if gap <= 3 else "G2" if gap <= 10 else "G3" if gap <= 30 else "G4"
        structural.append(f"CTX::{int(same_app)}::{int(same_window)}::{gap_bin}")

    entity_stream: list[str] = []
    for a in ordered:
        ets = entity_types(a)
        for et in ets:
            entity_stream.append(f"E::{et}")
            entity_stream.append(f"ET::{a.get('type','UNKNOWN')}::{et}")

    # Semantic stream: supporting evidence only. Dynamic values are masked.
    text_parts: list[str] = []
    for a in ordered:
        fields = [a.get("window"), a.get("target_field"), a.get("text"), a.get("screen_text")]
        pieces = [mask_dynamic_text(x) for x in fields]
        pieces = [x for x in pieces if x]
        if pieces:
            text_parts.append(" | ".join(pieces)[:1800])
    semantic = " ".join(text_parts)

    duration = max(0.0, ordered[-1]["_end"] - ordered[0]["_start"]) if ordered else 0.0
    meta = {
        "activity_count": len(ordered),
        "duration_seconds": duration,
        "types": types,
        "apps": compact(apps),
        "entity_types": sorted({et for a in ordered for et in entity_types(a)}),
        "start_ts": ordered[0]["_start"] if ordered else 0.0,
        "end_ts": ordered[-1]["_end"] if ordered else 0.0,
    }
    return {
        "struct": " ".join(structural) or "EMPTY",
        "entity": " ".join(entity_stream) or "EMPTY",
        "text": semantic or "EMPTY",
    }, meta


def build_records(activities_by_sid: dict[str, list[dict[str, Any]]], segments_by_sid: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for sid in sorted(segments_by_sid):
        acts = activities_by_sid.get(sid, [])
        for index, segment in enumerate(segments_by_sid[sid], 1):
            seg_acts = segment_activities(acts, segment)
            if not seg_acts:
                continue
            docs, meta = build_signature(seg_acts)
            rec = {
                "session_id": sid,
                "segment_index": index,
                "start": segment["_start"],
                "end": segment["_end"],
                "start_iso": segment.get("start"),
                "end_iso": segment.get("end"),
                "original_label": segment.get("label", ""),
                "execution_id": segment.get("execution_id"),
                "doc_struct": docs["struct"],
                "doc_entity": docs["entity"],
                "doc_text": docs["text"],
                **meta,
            }
            records.append(rec)
    records.sort(key=lambda r: (r["session_id"], r["start"], r["end"], r["segment_index"]))
    return records


def tfidf_block(docs: list[str], analyzer: str, ngram_range: tuple[int, int], min_df: int = 1) -> csr_matrix:
    vec = TfidfVectorizer(
        analyzer=analyzer,
        token_pattern=r"(?u)\S+" if analyzer == "word" else None,
        ngram_range=ngram_range,
        lowercase=False,
        min_df=min_df,
        sublinear_tf=True,
    )
    return vec.fit_transform(docs)


def feature_matrix(records: list[dict[str, Any]]) -> np.ndarray:
    struct = tfidf_block([r["doc_struct"] for r in records], "word", (1, 3), min_df=1)
    entity = tfidf_block([r["doc_entity"] for r in records], "word", (1, 2), min_df=1)
    # Character n-grams are useful for Japanese text without assuming word boundaries.
    semantic = tfidf_block([r["doc_text"] for r in records], "char", (2, 5), min_df=2)

    numeric = np.asarray([
        [
            math.log1p(r["duration_seconds"]),
            math.log1p(r["activity_count"]),
        ]
        for r in records
    ], dtype=float)
    numeric = StandardScaler().fit_transform(numeric)

    Xs = struct * 1.60
    Xe = entity * 0.80
    Xt = semantic * 0.65
    Xn = csr_matrix(numeric * 0.15)
    X = hstack([Xs, Xe, Xt, Xn], format="csr")
    X = Normalizer(copy=False).fit_transform(X)
    dense = X.toarray().astype(np.float32, copy=False)
    return dense


def cluster_matrix(X: np.ndarray, distance_threshold: float) -> np.ndarray:
    n = len(X)
    if n == 0:
        return np.zeros(0, dtype=int)
    if n == 1:
        return np.zeros(1, dtype=int)
    model = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=float(distance_threshold),
        linkage="average",
        metric="cosine",
    )
    return model.fit_predict(X)


def remap_labels(labels: np.ndarray, records: list[dict[str, Any]]) -> np.ndarray:
    members: dict[int, list[int]] = defaultdict(list)
    for i, lab in enumerate(labels.tolist()):
        members[int(lab)].append(i)
    ordered = sorted(
        members,
        key=lambda lab: (
            min(records[i]["session_id"] for i in members[lab]),
            min(records[i]["start"] for i in members[lab]),
            -len(members[lab]),
            lab,
        ),
    )
    mapping = {old: new for new, old in enumerate(ordered, 1)}
    return np.asarray([mapping[int(x)] for x in labels], dtype=int)


def purity(labels: np.ndarray, truth: list[str | None]) -> float:
    usable = [i for i, t in enumerate(truth) if t is not None]
    if not usable:
        return 0.0
    total = 0
    for lab in sorted(set(int(labels[i]) for i in usable)):
        vals = [truth[i] for i in usable if int(labels[i]) == lab]
        total += Counter(vals).most_common(1)[0][1]
    return total / len(usable)


def gt_owner_code(rec: dict[str, Any], gt: dict[str, list[dict[str, Any]]]) -> str | None:
    best_code = None
    best_score = -1.0
    for row in gt.get(rec["session_id"], []):
        score = overlap_seconds(rec["start"], rec["end"], row["start"], row["end"])
        # Prefer actual overlap; for an exact point, containment is also represented.
        if score > best_score:
            best_score = score
            best_code = row.get("process_code")
    return best_code if best_score > 0 else None


def stability(X: np.ndarray, records: list[dict[str, Any]], threshold: float) -> float:
    if len(X) < 2:
        return 1.0
    order = list(range(len(records)))
    random.Random(42).shuffle(order)
    ref = cluster_matrix(X, threshold)
    shuf = cluster_matrix(X[order], threshold)
    back = np.empty(len(order), dtype=int)
    for j, original in enumerate(order):
        back[original] = shuf[j]
    return float(adjusted_rand_score(ref, back))


def pick_threshold(X: np.ndarray, records: list[dict[str, Any]], grid: list[float]) -> tuple[float, dict[str, Any]]:
    candidates: list[tuple[float, float, float, int, float]] = []
    sample_n = min(len(X), SILHOUETTE_SAMPLE)
    sample_idx = np.linspace(0, len(X) - 1, sample_n, dtype=int) if sample_n else np.array([], dtype=int)
    for threshold in grid:
        labels = cluster_matrix(X, threshold)
        k = len(set(labels.tolist()))
        if k < MIN_CLUSTERS or k > MAX_CLUSTERS:
            continue
        try:
            sil = float(silhouette_score(X[sample_idx], labels[sample_idx], metric="cosine"))
        except Exception:
            continue
        stab = stability(X, records, threshold)
        sizes = Counter(labels.tolist())
        singleton_fraction = sum(1 for size in sizes.values() if size == 1) / max(1, k)
        # Internal-only objective: good separation + stable clustering, with
        # strong penalties for hundreds of tiny clusters.
        score = sil + 0.15 * stab - 0.30 * singleton_fraction
        if k < 8:
            score -= 0.05 * (8 - k)
        if k > 30:
            score -= 0.01 * (k - 30)
        candidates.append((score, threshold, sil, k, singleton_fraction))
    if not candidates:
        threshold = grid[len(grid) // 2]
        labels = cluster_matrix(X, threshold)
        return threshold, {"selection": "fallback", "cluster_count": int(len(set(labels.tolist())))}
    best = max(candidates)
    score, threshold, sil, k, singleton_fraction = best
    stab = stability(X, records, threshold)
    return threshold, {
        "selection": "internal_validation",
        "score": float(score),
        "silhouette": float(sil),
        "stability_ari": float(stab),
        "cluster_count": int(k),
        "singleton_cluster_fraction": float(singleton_fraction),
    }


def label_and_report(records: list[dict[str, Any]], labels: np.ndarray, prefix: str) -> list[dict[str, Any]]:
    labels = remap_labels(labels, records)
    out = []
    for rec, lab in zip(records, labels.tolist()):
        row = dict(rec)
        row["cluster_id"] = int(lab)
        row["label"] = f"{prefix}_{int(lab):03d}"
        out.append(row)
    return out


def cluster_summary(labeled: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in labeled:
        groups[row["cluster_id"]].append(row)
    report = []
    for cid in sorted(groups):
        rows = groups[cid]
        rep = max(rows, key=lambda r: (r["activity_count"], r["duration_seconds"], -r["segment_index"]))
        report.append({
            "cluster_id": cid,
            "label": f"{prefix}_{cid:03d}",
            "count": len(rows),
            "sessions": len({r["session_id"] for r in rows}),
            "median_duration_seconds": float(np.median([r["duration_seconds"] for r in rows])),
            "median_activity_count": float(np.median([r["activity_count"] for r in rows])),
            "representative_activity_types": rep["types"][:40],
            "representative_apps": rep["apps"][:20],
            "representative_entity_types": rep["entity_types"],
            "representative_text_excerpt": rep["doc_text"][:500],
        })
    return report


def preflight() -> None:
    synthetic = [
        {
            "activity_id": "a1", "session_id": "s1", "start": 0, "end": 0, "_start": 0.0, "_end": 0.0,
            "type": "CLICK", "app": "portal", "window": "Tax Portal",
            "target_field": "", "text": "", "screen_text": "住民税 通知確認",
            "entities": [{"type": "CASE_ID", "value": "C1"}],
        },
        {
            "activity_id": "a2", "session_id": "s1", "start": 1, "end": 1, "_start": 1.0, "_end": 1.0,
            "type": "COPY", "app": "portal", "window": "Tax Portal",
            "target_field": "", "text": "", "screen_text": "住民税 通知確認",
            "entities": [{"type": "CASE_ID", "value": "C1"}],
        },
        {
            "activity_id": "b1", "session_id": "s1", "start": 10, "end": 10, "_start": 10.0, "_end": 10.0,
            "type": "CLICK", "app": "finance", "window": "Bank Reconciliation",
            "target_field": "", "text": "", "screen_text": "銀行 勘定照合",
            "entities": [{"type": "BANK_ID", "value": "B1"}],
        },
        {
            "activity_id": "b2", "session_id": "s1", "start": 11, "end": 11, "_start": 11.0, "_end": 11.0,
            "type": "COPY", "app": "finance", "window": "Bank Reconciliation",
            "target_field": "", "text": "", "screen_text": "銀行 勘定照合",
            "entities": [{"type": "BANK_ID", "value": "B1"}],
        },
    ]
    docs, meta = build_signature(synthetic)
    assert set(docs) == {"struct", "entity", "text"}
    assert "T2::CLICK>COPY" in docs["struct"]
    assert "ET::CLICK::CASE_ID" in docs["entity"]
    X = feature_matrix([
        {"doc_struct": docs["struct"], "doc_entity": docs["entity"], "doc_text": docs["text"], **{**meta, "start": 0, "end": 1, "session_id": "s"}},
        {"doc_struct": docs["struct"], "doc_entity": docs["entity"], "doc_text": docs["text"], **{**meta, "start": 2, "end": 3, "session_id": "s"}},
    ])
    assert X.shape[0] == 2 and np.all(np.isfinite(X))
    assert stability(X, [{"session_id": "s", "start": 0}, {"session_id": "s", "start": 2}], 0.5) == 1.0
    print("Preflight process-discovery-v2 self-test: PASS (8 assertions)", flush=True)


def run_cluster(args: argparse.Namespace) -> int:
    preflight()
    activities = load_activities(Path(args.activities))
    segments = load_segments(Path(args.segments))
    records = build_records(activities, segments)
    if not records:
        raise RuntimeError("No segments contained any activity evidence")
    print(f"[DISCOVERY] segments with activity evidence: {len(records):,}", flush=True)
    X = feature_matrix(records)
    print(f"[DISCOVERY] representation dimensions: {X.shape[1]}", flush=True)
    threshold, selection = pick_threshold(X, records, args.threshold_grid)
    print(f"[DISCOVERY] selected cosine distance threshold: {threshold:.2f}", flush=True)
    print(f"[DISCOVERY] internal selection: {json.dumps(selection, sort_keys=True)}", flush=True)
    raw_labels = cluster_matrix(X, threshold)
    labeled = label_and_report(records, raw_labels, args.label_prefix)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "segments_labeled.jsonl").open("w", encoding="utf-8") as handle:
        for row in labeled:
            handle.write(json.dumps({
                "session_id": row["session_id"],
                "start": row["start_iso"],
                "end": row["end_iso"],
                "label": row["label"],
            }, ensure_ascii=False) + "\n")

    report: dict[str, Any] = {
        "segments_with_activity_evidence": len(records),
        "cluster_count": int(len(set(int(x) for x in remap_labels(raw_labels, records).tolist()))),
        "threshold": threshold,
        "selection": selection,
        "clusters": cluster_summary(labeled, args.label_prefix),
    }

    if args.gt:
        gt = load_gt_codes(Path(args.gt))
        truth = [gt_owner_code(row, gt) for row in records]
        usable = [i for i, t in enumerate(truth) if t is not None]
        final_labels = remap_labels(raw_labels, records)
        if usable:
            report["dataset_a_validation"] = {
                "segments_with_gt_overlap": len(usable),
                "purity": float(purity(final_labels, truth)),
                "adjusted_rand_index": float(adjusted_rand_score([truth[i] for i in usable], [int(final_labels[i]) for i in usable])),
            }
            print(f"[DISCOVERY] GT validation: purity={report['dataset_a_validation']['purity']:.4f}, ARI={report['dataset_a_validation']['adjusted_rand_index']:.4f}", flush=True)

    stable = stability(X, records, threshold)
    print(f"[DISCOVERY] reorder stability: ARI={stable:.6f}", flush=True)
    report["reorder_stability_ari"] = stable
    (out / "discovery_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote: {out / 'segments_labeled.jsonl'}", flush=True)
    print(f"Wrote: {out / 'discovery_report.json'}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sequence-first unsupervised workflow discovery")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cluster")
    c.add_argument("--activities", required=True)
    c.add_argument("--segments", required=True)
    c.add_argument("--out-dir", required=True)
    c.add_argument("--gt", default=None)
    c.add_argument("--label-prefix", default="PROCESS")
    c.add_argument("--threshold-grid", type=float, nargs="+", default=DEFAULT_DISTANCE_GRID)
    args = parser.parse_args(argv)
    try:
        return run_cluster(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
