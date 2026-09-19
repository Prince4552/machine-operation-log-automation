#!/usr/bin/env python3
"""
Process/workflow discovery from recovered contiguous segments.

Input:
  - activities.jsonl from the frozen activity extractor
  - segments.jsonl produced by the frozen boundary segmentation model

Core idea:
  segment -> compact structural signature -> TF-IDF/SVD representation
          -> deterministic agglomerative clustering with a distance threshold
          -> stable workflow labels

The clustering is fitted independently on the supplied dataset. It never
imports Dataset-A process labels into Dataset B.

A GT file may optionally be supplied for validation only. It is never used to
fit the clustering.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler


ENTITY_TYPES = {
    "INVOICE_ID", "EMPLOYEE_ID", "CASE_ID", "DOCUMENT_ID", "CUSTOMER_ID",
    "ORDER_ID", "PO_ID", "TRANSACTION_ID", "BANK_ID", "ID_CANDIDATE",
    "EMAIL", "FILENAME",
}

DEFAULT_DISTANCE_GRID = [0.35, 0.45, 0.55, 0.65, 0.75, 0.85]
MAX_CLUSTERS = 60
MIN_CLUSTER_SIZE_FOR_INTERNAL_SCORE = 2
SILHOUETTE_SAMPLE = 600


def parse_ts(v: Any) -> float:
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"Invalid timestamp: {v!r}")
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError(f"Timestamp must contain timezone: {v!r}")
    return dt.timestamp()


def norm(v: Any) -> str:
    if not isinstance(v, str):
        return ""
    return " ".join(v.casefold().strip().split())


def safe_list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else []


def normalize_trigger_token(v: Any) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        for key in ("activity_id", "event_id", "source_event_id", "id"):
            value = v.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def load_activities(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.exists():
        raise FileNotFoundError(path)
    by_sid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
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
            start = parse_ts(row["start"])
            end = parse_ts(row["end"])
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
    seen = set()
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            sid = row.get("session_id")
            if not isinstance(sid, str) or not sid:
                raise ValueError(f"segments line {line_no}: missing session_id")
            start = parse_ts(row["start"])
            end = parse_ts(row["end"])
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
        for a, b in zip(rows, rows[1:]):
            if b["_start"] < a["_end"]:
                raise ValueError(f"overlapping segments in session {sid}")
    return dict(by_sid)


def load_gt_codes(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Load GT segments with execution/process codes for validation only."""
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, list[dict[str, Any]]] = {}
    for session in data.get("sessions", []):
        sid = session.get("session_id")
        if not isinstance(sid, str):
            continue
        rows = []
        for ex in session.get("executions", []):
            code = ex.get("process_code")
            for seg in session.get("segments", []):
                if seg.get("execution_id") != ex.get("execution_id"):
                    continue
                rows.append({
                    "start": parse_ts(seg["start"]),
                    "end": parse_ts(seg["end"]),
                    "process_code": code,
                    "execution_id": ex.get("execution_id"),
                })
        # Some GT files keep segments independently of the execution loop.
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


def interval_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    if a0 == a1:
        return 1.0 if b0 <= a0 <= b1 else 0.0
    if b0 == b1:
        return 1.0 if a0 <= b0 <= a1 else 0.0
    return max(0.0, min(a1, b1) - max(a0, b0))


def segment_activities(
    activities: list[dict[str, Any]],
    segment: dict[str, Any],
) -> list[dict[str, Any]]:
    s0, s1 = segment["_start"], segment["_end"]
    rows = []
    for a in activities:
        if a["_end"] < s0 or a["_start"] > s1:
            continue
        rows.append(a)
    rows.sort(key=lambda x: (x["_start"], x["_end"], x["activity_id"]))
    return rows


def compact_sequence(values: list[str]) -> list[str]:
    out = []
    for value in values:
        if not value:
            continue
        if not out or out[-1] != value:
            out.append(value)
    return out


def entity_type_tokens(activity: dict[str, Any]) -> list[str]:
    out = []
    for entity in safe_list(activity.get("entities")):
        if not isinstance(entity, dict):
            continue
        et = entity.get("type")
        if isinstance(et, str) and et in ENTITY_TYPES:
            out.append(et)
    return sorted(set(out))


def signature_tokens(activities: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    types = compact_sequence([str(a.get("type", "UNKNOWN")) for a in activities])
    apps = compact_sequence([norm(a.get("app")) for a in activities])
    app_transitions = []
    for left, right in zip(apps, apps[1:]):
        if left and right and left != right:
            app_transitions.append(f"APPTRANS::{left}>>{right}")
    entity_pattern = []
    for a in activities:
        for et in entity_type_tokens(a):
            entity_pattern.append(f"ENTITY::{et}")
    type_bigrams = [f"TBIG::{x}>>{y}" for x, y in zip(types, types[1:])]
    tokens = []
    tokens.extend(f"TYPE::{x}" for x in types)
    tokens.extend(type_bigrams)
    tokens.extend(app_transitions)
    tokens.extend(entity_pattern)
    # Preserve multiplicity where it carries structural information.
    tokens.extend(f"COUNT_TYPE::{k}::{v}" for k, v in sorted(Counter(a.get("type", "UNKNOWN") for a in activities).items()))
    tokens.extend(f"APPCOUNT::{k}" for k, v in sorted(Counter(apps).items()) if k for _ in range(min(v, 3)))
    tokens = [t for t in tokens if t]
    doc = " ".join(tokens) if tokens else "EMPTY"
    duration = max(0.0, activities[-1]["_end"] - activities[0]["_start"]) if activities else 0.0
    meta = {
        "activity_count": len(activities),
        "duration_seconds": duration,
        "activity_types": types,
        "apps": apps,
        "entity_types": sorted({et for a in activities for et in entity_type_tokens(a)}),
        "token_count": len(tokens),
    }
    return doc, meta


def choose_feature_matrix(docs: list[str], metas: list[dict[str, Any]]) -> np.ndarray:
    vectorizer = TfidfVectorizer(token_pattern=r"(?u)\S+", lowercase=False, min_df=1, sublinear_tf=True)
    X = vectorizer.fit_transform(docs)
    max_components = min(64, X.shape[0] - 1, X.shape[1] - 1)
    if max_components >= 2 and X.shape[1] > 2:
        Xd = TruncatedSVD(n_components=max_components, random_state=42).fit_transform(X)
    else:
        Xd = X.toarray()
    numeric = np.asarray([[math.log1p(m["duration_seconds"]), math.log1p(m["activity_count"])] for m in metas], dtype=float)
    if len(numeric):
        numeric = StandardScaler().fit_transform(numeric)
        numeric *= 0.20
        Xd = np.hstack([Xd, numeric])
    Xd = np.asarray(Xd, dtype=float)
    return Xd


def cluster_matrix(X: np.ndarray, distance_threshold: float) -> np.ndarray:
    if len(X) == 0:
        return np.zeros(0, dtype=int)
    if len(X) == 1:
        return np.zeros(1, dtype=int)
    model = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=float(distance_threshold),
        linkage="average",
        metric="cosine",
    )
    return model.fit_predict(X)


def remap_labels(labels: np.ndarray, metas: list[dict[str, Any]]) -> np.ndarray:
    # Canonical order by a cluster's earliest member start, then size, then old id.
    members: dict[int, list[int]] = defaultdict(list)
    for i, lab in enumerate(labels.tolist()):
        members[int(lab)].append(i)
    ordering = sorted(
        members,
        key=lambda lab: (
            min(metas[i]["start_ts"] for i in members[lab]),
            -len(members[lab]),
            lab,
        ),
    )
    mapping = {old: new for new, old in enumerate(ordering, 1)}
    return np.asarray([mapping[int(x)] for x in labels], dtype=int)


def purity(labels: np.ndarray, truth: list[str | None]) -> float:
    usable = [i for i, t in enumerate(truth) if t is not None]
    if not usable:
        return 0.0
    total = 0
    for lab in sorted(set(int(labels[i]) for i in usable)):
        vals = [truth[i] for i in usable if int(labels[i]) == lab and truth[i] is not None]
        if vals:
            total += Counter(vals).most_common(1)[0][1]
    return total / len(usable)


def gt_owner_code(segment: dict[str, Any], gt_by_sid: dict[str, list[dict[str, Any]]]) -> str | None:
    sid = segment["session_id"]
    best = None
    best_ov = -1.0
    for gt in gt_by_sid.get(sid, []):
        ov = interval_overlap(segment["_start"], segment["_end"], gt["start"], gt["end"])
        if ov > best_ov:
            best_ov = ov
            best = gt
    if best is None or best_ov <= 0:
        return None
    return best.get("process_code")


def build_dataset(activities_by_sid, segments_by_sid):
    records = []
    for sid in sorted(segments_by_sid):
        acts = activities_by_sid.get(sid, [])
        for idx, seg in enumerate(segments_by_sid[sid], 1):
            seg_acts = segment_activities(acts, seg)
            if not seg_acts:
                continue
            doc, meta = signature_tokens(seg_acts)
            meta.update({
                "session_id": sid,
                "segment_index": idx,
                "start_ts": seg["_start"],
                "end_ts": seg["_end"],
                "start": seg["start"],
                "end": seg["end"],
                "original_label": seg.get("label", ""),
                "doc": doc,
            })
            records.append(meta)
    return records


def stable_label_records(records, labels, prefix):
    labels = remap_labels(labels, records)
    out = []
    for rec, lab in zip(records, labels.tolist()):
        row = dict(rec)
        row["cluster_id"] = int(lab)
        row["label"] = f"{prefix}_{int(lab):03d}"
        out.append(row)
    return out, labels


def validate_stability(records, docs, X, threshold, seed=42):
    if len(records) < 2:
        return 1.0
    rng = random.Random(seed)
    order = list(range(len(records)))
    rng.shuffle(order)
    X_shuf = X[order]
    labels_shuf = cluster_matrix(X_shuf, threshold)
    # Compare cluster co-membership, which is invariant to numeric label IDs.
    back = np.empty(len(order), dtype=int)
    for j, original_i in enumerate(order):
        back[original_i] = labels_shuf[j]
    labels_ref = cluster_matrix(X, threshold)
    return float(adjusted_rand_score(labels_ref, back))


def pick_threshold(X, records, candidate_grid):
    best = None
    sample_n = min(len(X), SILHOUETTE_SAMPLE)
    sample_idx = np.arange(sample_n)
    for threshold in candidate_grid:
        labels = cluster_matrix(X, threshold)
        k = len(set(labels.tolist()))
        if k < 2 or k > MAX_CLUSTERS:
            continue
        if sample_n < len(X):
            # deterministic sample: evenly spaced indices
            sample_idx = np.linspace(0, len(X) - 1, sample_n, dtype=int)
        try:
            sil = float(silhouette_score(X[sample_idx], labels[sample_idx], metric="cosine"))
        except Exception:
            continue
        stab = validate_stability(records, [r["doc"] for r in records], X, threshold)
        # Prefer good silhouette and stability, but strongly avoid singleton-heavy overclustering.
        sizes = Counter(labels.tolist())
        singleton_fraction = sum(1 for v in sizes.values() if v == 1) / max(1, k)
        score = sil + 0.15 * stab - 0.20 * singleton_fraction - 0.0015 * max(0, k - 25)
        candidate = (score, threshold, sil, stab, k, singleton_fraction)
        if best is None or candidate > best:
            best = candidate
    if best is None:
        return candidate_grid[2], {"selection": "fallback"}
    _, threshold, sil, stab, k, singleton_fraction = best
    return threshold, {
        "selection": "internal_validation",
        "silhouette": sil,
        "stability_ari": stab,
        "cluster_count": k,
        "singleton_cluster_fraction": singleton_fraction,
    }


def run_cluster(args):
    preflight()
    activities = load_activities(Path(args.activities))
    segments = load_segments(Path(args.segments))
    records = build_dataset(activities, segments)
    if not records:
        raise RuntimeError("No segments contained any activities")
    docs = [r["doc"] for r in records]
    X = choose_feature_matrix(docs, records)
    print(f"[DISCOVERY] segments with activity evidence: {len(records):,}")
    print(f"[DISCOVERY] representation dimensions: {X.shape[1]}")
    threshold, selection = pick_threshold(X, records, args.threshold_grid)
    print(f"[DISCOVERY] selected cosine distance threshold: {threshold:.2f}")
    print(f"[DISCOVERY] internal selection: {json.dumps(selection, sort_keys=True)}")
    labels = cluster_matrix(X, threshold)
    labeled, labels = stable_label_records(records, labels, args.label_prefix)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "segments_labeled.jsonl").open("w", encoding="utf-8") as f:
        for rec in labeled:
            f.write(json.dumps({
                "session_id": rec["session_id"],
                "start": rec["start"],
                "end": rec["end"],
                "label": rec["label"],
            }, ensure_ascii=False) + "\n")

    report = {
        "segments_input": len(sum(segments.values(), [])),
        "segments_with_activity_evidence": len(records),
        "cluster_count": int(len(set(labels.tolist()))),
        "threshold": threshold,
        "selection": selection,
        "clusters": [],
    }
    members = defaultdict(list)
    for rec in labeled:
        members[rec["cluster_id"]].append(rec)
    for cid in sorted(members):
        group = members[cid]
        rep = max(group, key=lambda r: (r["activity_count"], r["duration_seconds"], -r["segment_index"]))
        report["clusters"].append({
            "cluster_id": cid,
            "label": f"{args.label_prefix}_{cid:03d}",
            "count": len(group),
            "sessions": len({r["session_id"] for r in group}),
            "median_duration_seconds": float(np.median([r["duration_seconds"] for r in group])),
            "median_activity_count": float(np.median([r["activity_count"] for r in group])),
            "representative_activity_types": rep["activity_types"],
            "representative_apps": rep["apps"],
            "representative_entity_types": rep["entity_types"],
        })
    (out / "discovery_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.gt:
        gt = load_gt_codes(Path(args.gt))
        truth = [gt_owner_code({"session_id": r["session_id"], "_start": r["start_ts"], "_end": r["end_ts"]}, gt) for r in labeled]
        usable = [i for i, t in enumerate(truth) if t is not None]
        if usable:
            ari = adjusted_rand_score([truth[i] for i in usable], [int(labels[i]) for i in usable])
            pur = purity(labels, truth)
            report["dataset_a_validation"] = {
                "segments_with_gt_overlap": len(usable),
                "purity": pur,
                "adjusted_rand_index": float(ari),
            }
            (out / "discovery_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"[DISCOVERY] GT validation: purity={pur:.4f}, ARI={ari:.4f}")

    # Stability under shuffled input, required by the solution design.
    stable = validate_stability(records, docs, X, threshold)
    if stable < 0.999999:
        raise AssertionError(f"Cluster labels are not stable under input reordering (ARI={stable:.6f})")
    print(f"[DISCOVERY] reorder stability: ARI={stable:.6f}")
    print(f"Wrote: {out/'segments_labeled.jsonl'}")
    print(f"Wrote: {out/'discovery_report.json'}")
    return 0


def preflight():
    docs = ["TYPE::CLICK TBIG::CLICK>>TEXT ENTITY::CASE_ID", "TYPE::APP_SWITCH TBIG::APP_SWITCH>>CLICK ENTITY::INVOICE_ID"]
    metas = [
        {"activity_count": 3, "duration_seconds": 2.0, "start_ts": 1.0},
        {"activity_count": 3, "duration_seconds": 3.0, "start_ts": 2.0},
    ]
    X = choose_feature_matrix(docs, metas)
    assert X.shape[0] == 2
    labels = cluster_matrix(X, 0.65)
    assert len(labels) == 2
    assert remap_labels(labels, metas).tolist() in ([1, 2], [2, 1], [1, 1])
    # Trigger normalization regression.
    assert normalize_trigger_token({"event_id": "evt1"}) == "evt1"
    assert normalize_trigger_token({"activity_id": "act1"}) == "act1"
    assert normalize_trigger_token({"id": "x"}) == "x"
    assert normalize_trigger_token("evt2") == "evt2"
    print("Preflight process-discovery self-test: PASS (6 assertions)", flush=True)


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cluster")
    c.add_argument("--activities", required=True)
    c.add_argument("--segments", required=True)
    c.add_argument("--out-dir", required=True)
    c.add_argument("--gt", default=None)
    c.add_argument("--label-prefix", default="PROCESS")
    c.add_argument("--threshold-grid", type=float, nargs="+", default=DEFAULT_DISTANCE_GRID)
    args = p.parse_args(argv)
    try:
        if args.cmd == "cluster":
            return run_cluster(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
