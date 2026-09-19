#!/usr/bin/env python3
"""
Final semantic-first workflow discovery for the operation-log task.

Purpose
-------
Cluster recovered contiguous segments into workflow/process types without
importing Dataset-A labels into Dataset B.

Design is based on the comprehensive Dataset-A diagnosis:
- semantic evidence was the strongest representation by ARI and leave-session
  out 1NN accuracy;
- pure activity order, entity-type and relation-only representations were weak;
- adding weak structural features to semantic TF-IDF hurt on the diagnostic;
- internal cluster selection was already aligned with the best semantic k.

Therefore this version deliberately keeps process discovery semantic-first,
while using structural metadata only for reporting/inspection rather than as a
strong clustering feature.

No GT is used to fit clusters. GT is optional and used only for Dataset-A
validation. Dataset B is clustered independently.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import normalize


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

THRESHOLD_GRID = [0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75]
MIN_CLUSTERS = 5
MAX_CLUSTERS = 45
MAX_SINGLETON_FRACTION = 0.55
SILHOUETTE_SAMPLE = 600

# Channel weights. These are intentionally semantic-first.
WINDOW_WEIGHT = 4
TARGET_WEIGHT = 3
TEXT_WEIGHT = 2
SCREEN_WEIGHT = 1

# Dynamic values that should not dominate workflow similarity.
DYNAMIC_PATTERNS = [
    re.compile(r"https?://\S+", re.I),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    re.compile(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b"),
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"),
    re.compile(r"\b\d{6,}\b"),
    re.compile(r"\b[A-Z]{1,8}[-_][A-Z0-9]{2,}[-_][A-Z0-9]{2,}\b"),
]


# ---------------------------------------------------------------------------
# Generic utilities
# ---------------------------------------------------------------------------


def parse_ts(value: Any) -> float:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid timestamp: {value!r}")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError(f"Timestamp must contain timezone information: {value!r}")
    return dt.timestamp()


def norm_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.replace("\x07", " ").replace("\r", "\n")
    value = value.casefold()
    for pattern in DYNAMIC_PATTERNS:
        value = pattern.sub(" <DYN> ", value)
    # Keep Unicode content, including Japanese, but collapse whitespace.
    return " ".join(value.split())


def compact(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and (not out or out[-1] != value):
            out.append(value)
    return out


def safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------


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
            activity_id = row.get("activity_id")
            session_id = row.get("session_id")
            if not isinstance(activity_id, str) or not activity_id:
                raise ValueError(f"activities line {line_no}: missing activity_id")
            if not isinstance(session_id, str) or not session_id:
                raise ValueError(f"activities line {line_no}: missing session_id")
            if activity_id in seen:
                raise ValueError(f"duplicate activity_id: {activity_id}")
            seen.add(activity_id)
            start = parse_ts(row.get("start"))
            end = parse_ts(row.get("end"))
            if end < start:
                raise ValueError(f"activity {activity_id}: end < start")
            row["_start"] = start
            row["_end"] = end
            by_sid[session_id].append(row)
    for rows in by_sid.values():
        rows.sort(key=lambda r: (r["_start"], r["_end"], r["activity_id"]))
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
            session_id = row.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                raise ValueError(f"segments line {line_no}: missing session_id")
            start = parse_ts(row.get("start"))
            end = parse_ts(row.get("end"))
            if end < start:
                raise ValueError(f"segment line {line_no}: end < start")
            key = (session_id, start, end)
            if key in seen:
                raise ValueError(f"duplicate segment interval: {key}")
            seen.add(key)
            row["_start"] = start
            row["_end"] = end
            by_sid[session_id].append(row)
    for session_id, rows in by_sid.items():
        rows.sort(key=lambda r: (r["_start"], r["_end"], r.get("label", "")))
        for left, right in zip(rows, rows[1:]):
            if right["_start"] < left["_end"]:
                raise ValueError(f"overlapping segments in session {session_id}")
    return dict(by_sid)


def load_gt(path: Path) -> dict[str, list[dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, list[dict[str, Any]]] = {}
    for session in data.get("sessions", []):
        sid = session.get("session_id")
        if not isinstance(sid, str):
            continue
        rows: list[dict[str, Any]] = []
        executions = session.get("executions", [])
        for execution in executions:
            execution_id = execution.get("execution_id")
            process_code = execution.get("process_code")
            for segment in session.get("segments", []):
                if segment.get("execution_id") != execution_id:
                    continue
                rows.append({
                    "start": parse_ts(segment["start"]),
                    "end": parse_ts(segment["end"]),
                    "process_code": process_code,
                    "execution_id": execution_id,
                })
        if not rows:
            for segment in session.get("segments", []):
                rows.append({
                    "start": parse_ts(segment["start"]),
                    "end": parse_ts(segment["end"]),
                    "process_code": segment.get("process_code"),
                    "execution_id": segment.get("execution_id"),
                })
        rows.sort(key=lambda r: (r["start"], r["end"], str(r["execution_id"])))
        out[sid] = rows
    return out


# ---------------------------------------------------------------------------
# Segment activity evidence
# ---------------------------------------------------------------------------


def segment_activities(
    activities: list[dict[str, Any]],
    segment: dict[str, Any],
) -> list[dict[str, Any]]:
    start = segment["_start"]
    end = segment["_end"]
    result = []
    for activity in activities:
        # Point activities are included by timestamp containment.
        if activity["_end"] < start or activity["_start"] > end:
            continue
        result.append(activity)
    result.sort(key=lambda r: (r["_start"], r["_end"], r["activity_id"]))
    return result


# ---------------------------------------------------------------------------
# Semantic signature
# ---------------------------------------------------------------------------


def activity_semantic_parts(activity: dict[str, Any]) -> list[str]:
    window = norm_text(activity.get("window"))
    target = norm_text(activity.get("target_field"))
    text = norm_text(activity.get("text"))
    screen = norm_text(activity.get("screen_text"))

    # Window title and target field are more stable workflow hints than a large
    # screen dump, so they receive repeated tokens as explicit channel weights.
    parts: list[str] = []
    if window:
        parts.extend([f"WIN::{window}"] * WINDOW_WEIGHT)
    if target:
        parts.extend([f"TARGET::{target}"] * TARGET_WEIGHT)
    if text:
        parts.extend([f"TEXT::{text}"] * TEXT_WEIGHT)
    if screen:
        # Keep the first 2200 chars plus a final tail. This reduces repeated
        # boilerplate while retaining likely page/task headers and completion
        # messages.
        clipped = screen[:1700]
        if len(screen) > 2000:
            clipped += " " + screen[-300:]
        parts.extend([f"SCREEN::{clipped}"] * SCREEN_WEIGHT)
    return parts


def build_semantic_document(activities: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    ordered = sorted(activities, key=lambda r: (r["_start"], r["_end"], r["activity_id"]))
    channel_parts: list[str] = []
    types: list[str] = []
    apps: list[str] = []
    entity_types: set[str] = set()

    for activity in ordered:
        types.append(str(activity.get("type") or "UNKNOWN"))
        app = norm_text(activity.get("app"))
        if app:
            apps.append(app)
        for entity in safe_list(activity.get("entities")):
            if isinstance(entity, dict):
                et = entity.get("type")
                if isinstance(et, str) and et:
                    entity_types.add(et)
        channel_parts.extend(activity_semantic_parts(activity))

    # Add weak action markers only as tie-breakers. Do not let them dominate.
    for pair in zip(types, types[1:]):
        channel_parts.append(f"ACTIONPAIR::{pair[0]}>{pair[1]}")

    # Include a coarse duration marker only as text; exact duration is reported,
    # not used as the core semantic identity.
    if ordered:
        duration = max(0.0, ordered[-1]["_end"] - ordered[0]["_start"])
        if duration < 15:
            channel_parts.append("DUR::SHORT")
        elif duration < 45:
            channel_parts.append("DUR::MEDIUM")
        else:
            channel_parts.append("DUR::LONG")
    else:
        duration = 0.0

    document = " ".join(channel_parts) if channel_parts else "EMPTY"
    meta = {
        "activity_count": len(ordered),
        "duration_seconds": duration,
        "activity_types": compact(types),
        "apps": compact(apps),
        "entity_types": sorted(entity_types),
        "text_activity_count": sum(
            1 for a in ordered if norm_text(a.get("text")) or norm_text(a.get("screen_text"))
        ),
    }
    return document, meta


def build_records(
    activities_by_sid: dict[str, list[dict[str, Any]]],
    segments_by_sid: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for sid in sorted(segments_by_sid):
        activities = activities_by_sid.get(sid, [])
        for index, segment in enumerate(segments_by_sid[sid], 1):
            segment_acts = segment_activities(activities, segment)
            if not segment_acts:
                continue
            document, meta = build_semantic_document(segment_acts)
            records.append({
                "session_id": sid,
                "segment_index": index,
                "start": segment["_start"],
                "end": segment["_end"],
                "start_iso": segment.get("start"),
                "end_iso": segment.get("end"),
                "execution_id": segment.get("execution_id"),
                "original_label": segment.get("label", ""),
                "doc": document,
                **meta,
            })
    records.sort(key=lambda r: (r["session_id"], r["start"], r["end"], r["segment_index"]))
    return records


# ---------------------------------------------------------------------------
# Representation and clustering
# ---------------------------------------------------------------------------


def feature_matrix(records: list[dict[str, Any]]) -> np.ndarray:
    docs = [record["doc"] for record in records]
    vectorizer = TfidfVectorizer(
        analyzer="char",
        ngram_range=(2, 6),
        min_df=2,
        max_df=0.70,
        sublinear_tf=True,
        lowercase=False,
        dtype=np.float32,
    )
    X = vectorizer.fit_transform(docs)
    X = normalize(X, norm="l2", copy=False)
    return X.toarray().astype(np.float32, copy=False)


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


def stability(X: np.ndarray, records: list[dict[str, Any]], threshold: float) -> float:
    if len(X) < 2:
        return 1.0
    order = list(range(len(records)))
    random.Random(42).shuffle(order)
    ref = cluster_matrix(X, threshold)
    shuffled = cluster_matrix(X[order], threshold)
    restored = np.empty(len(order), dtype=int)
    for shuffled_index, original_index in enumerate(order):
        restored[original_index] = shuffled[shuffled_index]
    return float(adjusted_rand_score(ref, restored))


def select_threshold(X: np.ndarray, records: list[dict[str, Any]]) -> tuple[float, dict[str, Any]]:
    sample_n = min(len(X), SILHOUETTE_SAMPLE)
    sample_idx = np.linspace(0, len(X) - 1, sample_n, dtype=int) if sample_n else np.array([], dtype=int)
    candidates = []
    for threshold in THRESHOLD_GRID:
        labels = cluster_matrix(X, threshold)
        sizes = Counter(labels.tolist())
        k = len(sizes)
        singleton_fraction = sum(1 for size in sizes.values() if size == 1) / max(1, k)
        if k < MIN_CLUSTERS or k > MAX_CLUSTERS:
            continue
        if singleton_fraction > MAX_SINGLETON_FRACTION:
            continue
        try:
            silhouette = float(silhouette_score(X[sample_idx], labels[sample_idx], metric="cosine"))
        except Exception:
            continue
        stab = stability(X, records, threshold)
        # Internal objective: useful separation, perfect-ish reordering, and
        # explicit resistance to an explosion of singleton clusters.
        score = silhouette + 0.10 * stab - 0.20 * singleton_fraction
        candidates.append((score, threshold, silhouette, stab, k, singleton_fraction))
    if not candidates:
        threshold = 0.55
        labels = cluster_matrix(X, threshold)
        return threshold, {
            "selection": "fallback",
            "threshold": threshold,
            "cluster_count": int(len(set(labels.tolist()))),
        }
    best = max(candidates)
    score, threshold, silhouette, stab, k, singleton_fraction = best
    return threshold, {
        "selection": "internal_validation",
        "score": float(score),
        "threshold": float(threshold),
        "cluster_count": int(k),
        "silhouette": float(silhouette),
        "stability_ari": float(stab),
        "singleton_cluster_fraction": float(singleton_fraction),
    }


# ---------------------------------------------------------------------------
# Validation and stable labels
# ---------------------------------------------------------------------------


def gt_owner_code(record: dict[str, Any], gt: dict[str, list[dict[str, Any]]]) -> str | None:
    best_code = None
    best_score = 0.0
    for row in gt.get(record["session_id"], []):
        a0, a1 = record["start"], record["end"]
        b0, b1 = row["start"], row["end"]
        if a0 == a1:
            score = 1.0 if b0 <= a0 <= b1 else 0.0
        else:
            score = max(0.0, min(a1, b1) - max(a0, b0))
        if score > best_score:
            best_score = score
            best_code = row.get("process_code")
    return best_code


def purity(labels: np.ndarray, truth: list[str | None]) -> float:
    usable = [i for i, value in enumerate(truth) if value is not None]
    if not usable:
        return 0.0
    total = 0
    for cluster in sorted(set(int(labels[i]) for i in usable)):
        members = [truth[i] for i in usable if int(labels[i]) == cluster]
        total += Counter(members).most_common(1)[0][1]
    return total / len(usable)


def remap_labels(labels: np.ndarray, records: list[dict[str, Any]]) -> np.ndarray:
    members: dict[int, list[int]] = defaultdict(list)
    for index, label in enumerate(labels.tolist()):
        members[int(label)].append(index)
    ordered = sorted(
        members,
        key=lambda label: (
            min(records[i]["session_id"] for i in members[label]),
            min(records[i]["start"] for i in members[label]),
            -len(members[label]),
            label,
        ),
    )
    mapping = {old: new for new, old in enumerate(ordered, 1)}
    return np.asarray([mapping[int(label)] for label in labels], dtype=int)


def validate_stability(X: np.ndarray, records: list[dict[str, Any]], threshold: float) -> float:
    raw = cluster_matrix(X, threshold)
    order = list(range(len(records)))
    random.Random(42).shuffle(order)
    shuffled = cluster_matrix(X[order], threshold)
    restored = np.empty(len(order), dtype=int)
    for j, original_index in enumerate(order):
        restored[original_index] = shuffled[j]
    return float(adjusted_rand_score(raw, restored))


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def make_labels(records: list[dict[str, Any]], raw_labels: np.ndarray) -> list[dict[str, Any]]:
    stable = remap_labels(raw_labels, records)
    result = []
    for record, label in zip(records, stable.tolist()):
        row = {
            "session_id": record["session_id"],
            "start": record["start_iso"],
            "end": record["end_iso"],
            "label": f"WORKFLOW_{int(label):03d}",
            "cluster_id": int(label),
        }
        result.append(row)
    return result


def cluster_report(records: list[dict[str, Any]], labels: np.ndarray) -> list[dict[str, Any]]:
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for record, label in zip(records, labels.tolist()):
        groups[int(label)].append(record)
    output = []
    for cluster_id in sorted(groups):
        rows = groups[cluster_id]
        representative = max(
            rows,
            key=lambda row: (row["activity_count"], row["duration_seconds"], row["text_activity_count"]),
        )
        output.append({
            "cluster_id": cluster_id,
            "label": f"WORKFLOW_{cluster_id:03d}",
            "segment_count": len(rows),
            "session_count": len({row["session_id"] for row in rows}),
            "median_duration_seconds": float(np.median([row["duration_seconds"] for row in rows])),
            "median_activity_count": float(np.median([row["activity_count"] for row in rows])),
            "representative_activity_types": representative["activity_types"][:50],
            "representative_apps": representative["apps"][:25],
            "representative_entity_types": representative["entity_types"],
            "representative_start": representative["start_iso"],
        })
    return output


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def preflight() -> None:
    synthetic = [
        {
            "activity_id": "a1", "session_id": "s1", "start": "1970-01-01T00:00:00Z", "end": "1970-01-01T00:00:00Z",
            "_start": 0.0, "_end": 0.0, "type": "CLICK", "app": "x", "window": "住民税通知確認",
            "target_field": "", "text": "", "screen_text": "住民税 通知確認",
            "entities": [{"type": "CASE_ID", "value": "C1"}],
        },
        {
            "activity_id": "a2", "session_id": "s1", "start": "1970-01-01T00:00:01Z", "end": "1970-01-01T00:00:01Z",
            "_start": 1.0, "_end": 1.0, "type": "COPY", "app": "x", "window": "住民税通知確認",
            "target_field": "employee", "text": "", "screen_text": "住民税 通知確認 完了",
            "entities": [{"type": "CASE_ID", "value": "C1"}],
        },
        {
            "activity_id": "b1", "session_id": "s1", "start": "1970-01-01T00:00:10Z", "end": "1970-01-01T00:00:10Z",
            "_start": 10.0, "_end": 10.0, "type": "CLICK", "app": "y", "window": "銀行勘定照合",
            "target_field": "", "text": "", "screen_text": "銀行 勘定照合",
            "entities": [{"type": "BANK_ID", "value": "B1"}],
        },
        {
            "activity_id": "b2", "session_id": "s1", "start": "1970-01-01T00:00:11Z", "end": "1970-01-01T00:00:11Z",
            "_start": 11.0, "_end": 11.0, "type": "COPY", "app": "y", "window": "銀行勘定照合",
            "target_field": "", "text": "", "screen_text": "銀行 勘定照合 完了",
            "entities": [{"type": "BANK_ID", "value": "B1"}],
        },
    ]
    doc_a, meta_a = build_semantic_document(synthetic[:2])
    doc_b, meta_b = build_semantic_document(synthetic[2:])
    assert "住民税" in doc_a
    assert "銀行" in doc_b
    assert meta_a["activity_count"] == 2 and meta_b["activity_count"] == 2
    records = [
        {"session_id": "s1", "start": 0.0, "end": 1.0, "start_iso": "x", "end_iso": "y", "doc": doc_a, **meta_a},
        {"session_id": "s2", "start": 2.0, "end": 3.0, "start_iso": "x", "end_iso": "y", "doc": doc_b, **meta_b},
        {"session_id": "s3", "start": 4.0, "end": 5.0, "start_iso": "x", "end_iso": "y", "doc": doc_a, **meta_a},
        {"session_id": "s4", "start": 6.0, "end": 7.0, "start_iso": "x", "end_iso": "y", "doc": doc_b, **meta_b},
    ]
    X = feature_matrix(records)
    assert X.shape[0] == 4 and X.shape[1] > 0
    assert np.all(np.isfinite(X))
    labels = cluster_matrix(X, 0.55)
    assert len(labels) == 4
    assert validate_stability(X, records, 0.55) == 1.0
    print("Preflight final process-discovery self-test: PASS (8 assertions)", flush=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    preflight()
    activities = load_activities(Path(args.activities))
    segments = load_segments(Path(args.segments))
    records = build_records(activities, segments)
    if not records:
        raise RuntimeError("No segments contain activity evidence")

    print(f"[DISCOVERY] segments with activity evidence: {len(records):,}", flush=True)
    print(f"[DISCOVERY] sessions: {len({r['session_id'] for r in records})}", flush=True)

    X = feature_matrix(records)
    print(f"[DISCOVERY] semantic representation dimensions: {X.shape[1]}", flush=True)

    threshold, selection = select_threshold(X, records)
    print(f"[DISCOVERY] selected threshold: {threshold:.2f}", flush=True)
    print(f"[DISCOVERY] internal selection: {json.dumps(selection, sort_keys=True)}", flush=True)

    raw_labels = cluster_matrix(X, threshold)
    stable_labels = remap_labels(raw_labels, records)
    stability_ari = validate_stability(X, records, threshold)
    print(f"[DISCOVERY] reorder stability: ARI={stability_ari:.6f}", flush=True)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    labeled = make_labels(records, raw_labels)
    report = {
        "method": "semantic_first_workflow_discovery",
        "segment_count": len(records),
        "session_count": len({r["session_id"] for r in records}),
        "cluster_count": int(len(set(stable_labels.tolist()))),
        "selected_threshold": float(threshold),
        "internal_selection": selection,
        "reorder_stability_ari": stability_ari,
        "clusters": cluster_report(records, stable_labels),
    }

    if args.gt:
        gt = load_gt(Path(args.gt))
        truth = [gt_owner_code(record, gt) for record in records]
        usable = [i for i, value in enumerate(truth) if value is not None]
        if usable:
            validation_purity = purity(stable_labels, truth)
            validation_ari = adjusted_rand_score(
                [truth[i] for i in usable],
                [int(stable_labels[i]) for i in usable],
            )
            report["dataset_a_validation"] = {
                "segments_with_gt_overlap": len(usable),
                "purity": float(validation_purity),
                "adjusted_rand_index": float(validation_ari),
                "gt_process_codes": sorted(set(truth[i] for i in usable)),
            }
            print(
                f"[DISCOVERY] GT validation: purity={validation_purity:.4f}, ARI={validation_ari:.4f}",
                flush=True,
            )

    segments_path = out / "segments_labeled.jsonl"
    with segments_path.open("w", encoding="utf-8") as handle:
        for row in labeled:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    report_path = out / "discovery_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote: {segments_path}", flush=True)
    print(f"Wrote: {report_path}", flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Semantic-first process/workflow discovery")
    sub = parser.add_subparsers(dest="command", required=True)
    cluster = sub.add_parser("cluster")
    cluster.add_argument("--activities", required=True)
    cluster.add_argument("--segments", required=True)
    cluster.add_argument("--gt")
    cluster.add_argument("--out-dir", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "cluster":
        return run(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
