#!/usr/bin/env python3
"""
Task 2 workflow/execution enrichment and analysis.

This script intentionally does NOT modify outputs/segments.jsonl.

Inputs:
  --activities : Dataset B activities.jsonl from the frozen activities.py
  --segments   : final validated outputs/segments.jsonl

Outputs:
  workflow_summary.csv
  execution_map.jsonl
  workflow_evidence.jsonl
  task2_report.json
  task2_anomalies.json

What it does:
  1. Treats each final segment as ONE inferred workflow occurrence.
     It assigns a deterministic inferred_execution_id.
     This is NOT an original business execution ID from the source logs.
  2. Joins activities into each segment using time containment/overlap.
  3. Recovers EXPLICIT entities only from the activity `entities` field.
     It never invents employee/case/document IDs from arbitrary text.
  4. Extracts application/window/text evidence for human process naming.
  5. Computes workflow-level frequency, duration, session/actor coverage,
     app complexity, variant counts and repeatability.
  6. Writes defensive diagnostics so missing/odd fields become visible
     instead of crashing on real data.

No external dependencies; standard library only.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

SESSION_RE = re.compile(r"^ses_(\d{8}-\d{6})-(.+)$")
WS_RE = re.compile(r"\s+")
SENSITIVE_KEYWORDS = {
    "activity_id", "source_event_id", "event_id", "chunk_id",
    "session_id", "triggered_by"
}
ENTITY_KIND_KEYS = ("type", "entity_type", "kind", "label", "category")
ENTITY_VALUE_KEYS = ("value", "text", "normalized", "name", "id", "entity")

TEXT_KEYS = ("text", "screen_text", "window", "browser_tab", "target_field")
APP_KEYS = ("app", "browser_url")
MAX_EVIDENCE_CHARS = 420
MAX_SAMPLE_ITEMS = 8
MAX_REP_OCCURRENCES = 3


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def parse_ts(value: Any) -> float:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid timestamp: {value!r}")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError(f"timestamp has no timezone: {value!r}")
    return dt.timestamp()


def fmt_seconds(x: float) -> float:
    return round(float(x), 3)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return WS_RE.sub(" ", value.strip())
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        parts = []
        # Keep useful human-facing target fields, but avoid dumping arbitrary IDs.
        for key in ("name", "title", "control_type", "class_name", "automation_id"):
            v = value.get(key)
            if isinstance(v, (str, int, float)) and str(v).strip():
                parts.append(f"{key}={v}")
        return WS_RE.sub(" ", " ".join(parts).strip())
    if isinstance(value, list):
        return WS_RE.sub(" ", " ".join(clean_text(v) for v in value).strip())
    return str(value)


def trunc(value: str, limit: int = MAX_EVIDENCE_CHARS) -> str:
    value = clean_text(value)
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def actor_or_machine(session_id: str) -> str:
    m = SESSION_RE.match(session_id)
    return m.group(2) if m else session_id


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        die(f"file not found: {path}")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                die(f"{path}:{line_no}: invalid JSON ({exc})")
            if not isinstance(row, dict):
                die(f"{path}:{line_no}: expected JSON object")
            rows.append(row)
    if not rows:
        die(f"{path}: no records")
    return rows


def validate_segments(rows: list[dict[str, Any]]) -> None:
    required = {"session_id", "start", "end", "label"}
    seen = set()
    per_session = defaultdict(list)

    for i, row in enumerate(rows, 1):
        missing = required - row.keys()
        if missing:
            die(f"segments line {i}: missing fields {sorted(missing)}")

        extra = set(row) - required
        if extra:
            # The final deliverable is required to contain exactly four fields.
            die(f"segments line {i}: unexpected fields {sorted(extra)}")

        sid = row["session_id"]
        label = row["label"]
        if not isinstance(sid, str) or not sid:
            die(f"segments line {i}: invalid session_id")
        if not isinstance(label, str) or not label:
            die(f"segments line {i}: invalid label")

        start = parse_ts(row["start"])
        end = parse_ts(row["end"])
        if end <= start:
            die(f"segments line {i}: non-positive duration")

        key = (sid, row["start"], row["end"])
        if key in seen:
            die(f"segments line {i}: duplicate interval {key}")
        seen.add(key)
        per_session[sid].append((start, end, label, i))

    for sid, items in per_session.items():
        items.sort()
        prev_end = None
        for start, end, _label, line_no in items:
            if prev_end is not None and start < prev_end - 1e-9:
                die(f"segments overlap in session {sid} near line {line_no}")
            prev_end = end


def validate_activities(rows: list[dict[str, Any]]) -> None:
    required = {"activity_id", "session_id", "start", "end", "type"}
    seen = set()
    for i, row in enumerate(rows, 1):
        missing = required - row.keys()
        if missing:
            die(f"activities line {i}: missing fields {sorted(missing)}")
        aid = row["activity_id"]
        if not isinstance(aid, str) or not aid:
            die(f"activities line {i}: invalid activity_id")
        if aid in seen:
            die(f"activities line {i}: duplicate activity_id {aid}")
        seen.add(aid)
        parse_ts(row["start"])
        parse_ts(row["end"])
        if parse_ts(row["end"]) < parse_ts(row["start"]):
            die(f"activities line {i}: end before start")


def interval_relation(a0: float, a1: float, s0: float, s1: float) -> bool:
    # For point activities, timestamp containment is the correct ownership rule.
    if abs(a1 - a0) <= 1e-9:
        return s0 - 1e-9 <= a0 <= s1 + 1e-9
    return max(a0, s0) <= min(a1, s1) + 1e-9


def extract_explicit_entities(activity: dict[str, Any]) -> list[dict[str, str]]:
    raw = activity.get("entities")
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    out: list[dict[str, str]] = []

    for item in items:
        if isinstance(item, str):
            value = clean_text(item)
            if value:
                out.append({"type": "UNSPECIFIED", "value": value})
            continue

        if not isinstance(item, dict):
            continue

        kind = ""
        for key in ENTITY_KIND_KEYS:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                kind = clean_text(value)
                break

        entity_value = ""
        for key in ENTITY_VALUE_KEYS:
            value = item.get(key)
            if isinstance(value, (str, int, float)) and str(value).strip():
                entity_value = clean_text(value)
                break

        if not entity_value:
            continue

        # Avoid counting implementation/provenance identifiers as business entities.
        lower_kind = kind.casefold()
        if lower_kind in {"", "id", "identifier"} and entity_value.startswith(("act_", "evt_", "event_")):
            continue

        out.append({
            "type": kind or "UNSPECIFIED",
            "value": entity_value,
        })

    # deterministic unique order
    seen = set()
    deduped = []
    for item in out:
        key = (item["type"], item["value"])
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def activity_text_evidence(activity: dict[str, Any]) -> list[str]:
    vals: list[str] = []
    for key in TEXT_KEYS:
        value = activity.get(key)
        text = clean_text(value)
        if text:
            vals.append(f"{key}={trunc(text)}")
    return vals


def activity_apps(activity: dict[str, Any]) -> list[str]:
    apps = []
    app = clean_text(activity.get("app"))
    if app:
        apps.append(app)
    tab = clean_text(activity.get("browser_tab"))
    if tab:
        apps.append(f"browser:{tab}")
    return apps


def variant_signature(activities: list[dict[str, Any]]) -> str:
    # Structural variant: activity-type sequence only.
    # This is intentionally stable and does not embed A-specific vocabulary.
    return " > ".join(str(a.get("type", "OTHER")) for a in activities)


def compress_variant(activities: list[dict[str, Any]]) -> str:
    # A coarse variant useful for human inspection: type runs collapsed.
    out = []
    last = None
    count = 0
    for activity in activities:
        t = str(activity.get("type", "OTHER"))
        if t == last:
            count += 1
        else:
            if last is not None:
                out.append(f"{last}x{count}" if count > 1 else last)
            last = t
            count = 1
    if last is not None:
        out.append(f"{last}x{count}" if count > 1 else last)
    return " > ".join(out)


def assign_activities_to_segments(
    segments: list[dict[str, Any]],
    activities: list[dict[str, Any]],
) -> tuple[dict[int, list[dict[str, Any]]], dict[str, int]]:
    """
    Assign each activity to at most ONE final segment.

    Rules:
      - point activity: choose the containing segment; if it lands exactly on a
        shared boundary, prefer the preceding segment because v6 places a
        boundary at the previous activity end.
      - duration activity: choose the segment with the largest temporal overlap;
        ties go to the earlier segment.
      - activity outside the segment union remains unassigned.

    This prevents double-counting when an activity interval straddles a
    segmentation boundary.
    """
    seg_by_session: dict[str, list[tuple[int, float, float]]] = defaultdict(list)
    for idx, seg in enumerate(segments):
        seg_by_session[seg["_sid"]].append((idx, seg["_start"], seg["_end"]))
    for sid in seg_by_session:
        seg_by_session[sid].sort(key=lambda x: (x[1], x[2], x[0]))

    act_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for a in activities:
        act_by_session[a["_sid"]].append(a)
    for sid in act_by_session:
        act_by_session[sid].sort(key=lambda a: (a["_start"], a["_end"], a["activity_id"]))

    assigned: dict[int, list[dict[str, Any]]] = defaultdict(list)
    counters = {
        "activities_total": len(activities),
        "assigned_once": 0,
        "unassigned": 0,
        "boundary_tie_to_previous": 0,
        "multi_overlap_resolved": 0,
    }

    for sid, acts in act_by_session.items():
        segs = seg_by_session.get(sid, [])
        if not segs:
            counters["unassigned"] += len(acts)
            continue

        for a in acts:
            a0, a1 = a["_start"], a["_end"]
            candidates: list[tuple[int, float, float, int]] = []

            for seg_idx, s0, s1 in segs:
                if s1 < a0 - 1e-9:
                    continue
                if s0 > a1 + 1e-9:
                    break
                overlap = max(0.0, min(a1, s1) - max(a0, s0))
                candidates.append((seg_idx, s0, s1, overlap))

            if abs(a1 - a0) <= 1e-9:
                containing = [c for c in candidates if c[1] - 1e-9 <= a0 <= c[2] + 1e-9]
                if not containing:
                    counters["unassigned"] += 1
                    continue

                previous = [c for c in containing if abs(c[2] - a0) <= 1e-9]
                if previous:
                    chosen = sorted(previous, key=lambda c: c[0])[0]
                    if len(containing) > 1:
                        counters["boundary_tie_to_previous"] += 1
                else:
                    chosen = sorted(containing, key=lambda c: c[0])[0]

                assigned[chosen[0]].append(a)
                counters["assigned_once"] += 1
                continue

            if not candidates:
                counters["unassigned"] += 1
                continue

            positive = [c for c in candidates if c[3] > 1e-12]
            if not positive:
                counters["unassigned"] += 1
                continue

            best_overlap = max(c[3] for c in positive)
            best = [c for c in positive if abs(c[3] - best_overlap) <= 1e-12]
            chosen = sorted(best, key=lambda c: c[0])[0]
            if len(positive) > 1:
                counters["multi_overlap_resolved"] += 1

            assigned[chosen[0]].append(a)
            counters["assigned_once"] += 1

    return assigned, counters


def build_records(
    segments_raw: list[dict[str, Any]],
    activities_raw: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    segments = []
    for row in segments_raw:
        s = dict(row)
        s["_sid"] = row["session_id"]
        s["_start"] = parse_ts(row["start"])
        s["_end"] = parse_ts(row["end"])
        segments.append(s)

    activities = []
    for row in activities_raw:
        a = dict(row)
        a["_sid"] = row["session_id"]
        a["_start"] = parse_ts(row["start"])
        a["_end"] = parse_ts(row["end"])
        activities.append(a)

    assigned, assignment_diag = assign_activities_to_segments(segments, activities)

    # Global deterministic order: session, start, end, label.
    segments_sorted = sorted(
        enumerate(segments),
        key=lambda pair: (pair[1]["_sid"], pair[1]["_start"], pair[1]["_end"], pair[1]["label"])
    )

    occurrence_counter: defaultdict[str, int] = defaultdict(int)
    execution_map = []

    workflow_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "segments": [],
        "sessions": set(),
        "actors": set(),
        "entities": Counter(),
        "entity_values": set(),
        "apps": Counter(),
        "activity_types": Counter(),
        "variants": Counter(),
        "total_duration_s": 0.0,
        "activity_count": 0,
        "app_switches": 0,
    })

    unmapped_activity_count = len(activities)

    for sorted_pos, (original_idx, seg) in enumerate(segments_sorted, 1):
        label = seg["label"]
        occurrence_counter[label] += 1
        local_no = occurrence_counter[label]
        inferred_execution_id = f"{label}_EXEC_{local_no:04d}"
        acts = sorted(
            assigned.get(original_idx, []),
            key=lambda a: (a["_start"], a["_end"], a["activity_id"])
        )

        if acts:
            unmapped_activity_count -= len(acts)

        entities = []
        entity_types = Counter()
        entity_values = []
        apps = []
        activity_types = Counter()
        evidence = []

        prev_app = None
        switches = 0

        for a in acts:
            a_entities = extract_explicit_entities(a)
            entities.extend(a_entities)
            for e in a_entities:
                entity_types[e["type"]] += 1
                entity_values.append(f"{e['type']}={e['value']}")

            for app_name in activity_apps(a):
                apps.append(app_name)
                if prev_app is not None and app_name != prev_app:
                    switches += 1
                prev_app = app_name

            t = str(a.get("type", "OTHER"))
            activity_types[t] += 1
            evidence.extend(activity_text_evidence(a))

        unique_entities = sorted(set(entity_values))
        unique_apps = sorted(set(apps))
        uniq_evidence = list(dict.fromkeys(evidence))[:MAX_SAMPLE_ITEMS]

        compact = compress_variant(acts)
        exact_variant = variant_signature(acts)

        record = {
            "workflow_id": label,
            "inferred_execution_id": inferred_execution_id,
            "execution_status": "inferred_segment_occurrence",
            "session_id": seg["session_id"],
            "actor_or_machine": actor_or_machine(seg["session_id"]),
            "start": seg["start"],
            "end": seg["end"],
            "duration_s": fmt_seconds(seg["_end"] - seg["_start"]),
            "activity_count": len(acts),
            "activity_types": dict(activity_types),
            "apps": unique_apps,
            "app_count": len(unique_apps),
            "app_switches": switches,
            "explicit_entity_count": len(unique_entities),
            "explicit_entities": unique_entities[:MAX_SAMPLE_ITEMS],
            "explicit_entity_types": dict(entity_types),
            "variant_signature": exact_variant,
            "variant_signature_compact": compact,
            "evidence": uniq_evidence,
        }
        execution_map.append(record)

        st = workflow_stats[label]
        st["segments"].append(record)
        st["sessions"].add(seg["session_id"])
        st["actors"].add(actor_or_machine(seg["session_id"]))
        st["total_duration_s"] += seg["_end"] - seg["_start"]
        st["activity_count"] += len(acts)
        st["app_switches"] += switches
        for e in unique_entities:
            st["entity_values"].add(e)
            kind = e.split("=", 1)[0] if "=" in e else "UNSPECIFIED"
            st["entities"][kind] += 1
        for app in unique_apps:
            st["apps"][app] += 1
        for t, count in activity_types.items():
            st["activity_types"][t] += count
        st["variants"][exact_variant] += 1

    return execution_map, {
        "workflow_stats": workflow_stats,
        "total_activities": len(activities),
        "assigned_activities": assignment_diag["assigned_once"],
        "unassigned_activities": assignment_diag["unassigned"],
        "assignment_diag": assignment_diag,
    }


def build_workflow_summary(
    workflow_stats: dict[str, dict[str, Any]],
    total_duration: float,
) -> list[dict[str, Any]]:
    rows = []
    for label in sorted(workflow_stats):
        st = workflow_stats[label]
        count = len(st["segments"])
        sessions = len(st["sessions"])
        actors = len(st["actors"])
        variants = len(st["variants"])
        dominant_variant_count = max(st["variants"].values()) if st["variants"] else 0
        repeatability = dominant_variant_count / count if count else 0.0

        # A descriptive screen, not a claim of automation value.
        # It simply surfaces repetition + volume + time for human review.
        total_dur = st["total_duration_s"]
        duration_share = total_dur / total_duration if total_duration else 0.0

        rows.append({
            "workflow_id": label,
            "execution_count": count,
            "session_count": sessions,
            "actor_or_machine_count": actors,
            "total_duration_s": fmt_seconds(total_dur),
            "mean_duration_s": fmt_seconds(total_dur / count if count else 0),
            "median_duration_s": fmt_seconds(sorted(r["duration_s"] for r in st["segments"])[count // 2 - (1 if count % 2 == 0 else 0)] if count else 0),
            "duration_share": round(duration_share, 6),
            "total_activity_count": st["activity_count"],
            "mean_activity_count": round(st["activity_count"] / count, 2) if count else 0,
            "unique_apps": len(st["apps"]),
            "total_app_switches": st["app_switches"],
            "unique_variants": variants,
            "dominant_variant_count": dominant_variant_count,
            "dominant_variant_share": round(repeatability, 6),
            "explicit_entity_value_count": len(st["entity_values"]),
            "explicit_entity_type_count": len(st["entities"]),
            # Kept neutral: these are observations to prioritize human inspection.
            "screening_volume_score": round(math.log1p(count), 4),
            "screening_time_score": round(math.log1p(total_dur), 4),
            "screening_repeatability_score": round(repeatability, 4),
        })
    rows.sort(
        key=lambda r: (
            -r["execution_count"],
            -r["total_duration_s"],
            -r["dominant_variant_share"],
            r["workflow_id"],
        )
    )
    return rows


def make_evidence(
    execution_map: list[dict[str, Any]],
    workflow_stats: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    by_workflow = defaultdict(list)
    for row in execution_map:
        by_workflow[row["workflow_id"]].append(row)

    out = []
    for label in sorted(by_workflow):
        rows = by_workflow[label]
        st = workflow_stats[label]

        representative = sorted(
            rows,
            key=lambda r: (
                -r["activity_count"],
                -r["duration_s"],
                r["session_id"],
                r["start"],
            ),
        )[:MAX_REP_OCCURRENCES]

        all_evidence = []
        for r in representative:
            all_evidence.extend(r["evidence"])
        all_evidence = list(dict.fromkeys(all_evidence))

        common_apps = st["apps"].most_common(8)
        common_activity_types = st["activity_types"].most_common(8)

        out.append({
            "workflow_id": label,
            "process_name_status": "requires_human_semantic_naming",
            "note": (
                "Workflow ID is an unsupervised Dataset-B cluster. "
                "The script does not invent a business-process name."
            ),
            "execution_count": len(rows),
            "session_count": len(st["sessions"]),
            "actor_or_machine_count": len(st["actors"]),
            "total_duration_s": fmt_seconds(st["total_duration_s"]),
            "unique_variants": len(st["variants"]),
            "dominant_variant_share": round(
                max(st["variants"].values()) / len(rows), 6
            ) if rows else 0.0,
            "common_apps": common_apps,
            "common_activity_types": common_activity_types,
            "explicit_entity_types_seen": sorted(st["entities"]),
            "explicit_entity_examples": sorted(st["entity_values"])[:MAX_SAMPLE_ITEMS],
        "strong_entity_examples": sorted(
            e for e in st["entity_values"]
            if not e.startswith("NUMBER_CANDIDATE=")
        )[:MAX_SAMPLE_ITEMS],
            "representative_occurrences": [
                {
                    "inferred_execution_id": r["inferred_execution_id"],
                    "session_id": r["session_id"],
                    "start": r["start"],
                    "end": r["end"],
                    "duration_s": r["duration_s"],
                    "activity_count": r["activity_count"],
                    "apps": r["apps"],
                    "explicit_entities": r["explicit_entities"],
                    "evidence": r["evidence"],
                }
                for r in representative
            ],
            "evidence_samples": all_evidence[:MAX_SAMPLE_ITEMS],
        })
    return out



def build_semantic_cues(
    execution_map: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    assigned: dict[int, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """
    Produce compact human-inspection cues for naming workflow clusters.
    This is deliberately descriptive; it never invents a process name.
    """
    by_workflow: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    # execution_map already contains evidence but not frequency of individual
    # window/text cues, so use the embedded evidence fields.
    for row in execution_map:
        by_workflow[row["workflow_id"]].append(row)

    out = []
    for label in sorted(by_workflow):
        window_counter = Counter()
        text_counter = Counter()
        entity_counter = Counter()
        for row in by_workflow[label]:
            for ev in row.get("evidence", []):
                if ev.startswith("window="):
                    window_counter[ev[len("window="):]] += 1
                elif ev.startswith("browser_tab="):
                    window_counter[ev[len("browser_tab="):]] += 1
                elif ev.startswith("text="):
                    text_counter[ev[len("text="):]] += 1
            for entity in row.get("explicit_entities", []):
                if not entity.startswith("NUMBER_CANDIDATE="):
                    entity_counter[entity] += 1

        out.append({
            "workflow_id": label,
            "process_name": None,
            "process_name_status": "human_review_required",
            "n_occurrences": len(by_workflow[label]),
            "top_window_or_tab_cues": window_counter.most_common(12),
            "top_text_cues": text_counter.most_common(12),
            "strong_entity_cues": entity_counter.most_common(12),
            "interpretation_rule": (
                "Use these cues plus the workflow-level application and activity "
                "statistics to assign a human-readable process type. Do not "
                "treat WORKFLOW_* itself as a business-process name."
            ),
        })
    return out


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_self_test() -> None:
    segments = [
        {
            "session_id": "ses_20260701-100000-TEST",
            "start": "2026-07-01T10:00:00+00:00",
            "end": "2026-07-01T10:00:10+00:00",
            "label": "WORKFLOW_001",
        },
        {
            "session_id": "ses_20260701-100000-TEST",
            "start": "2026-07-01T10:00:10+00:00",
            "end": "2026-07-01T10:00:20+00:00",
            "label": "WORKFLOW_001",
        },
    ]
    activities = [
        {
            "activity_id": "act1",
            "session_id": "ses_20260701-100000-TEST",
            "start": "2026-07-01T10:00:00+00:00",
            "end": "2026-07-01T10:00:00+00:00",
            "type": "CLICK",
            "app": "AppA",
            "window": "Employee Registration",
            "entities": [{"type": "EMPLOYEE_ID", "value": "EMP001"}],
            "text": "",
            "screen_text": "Register employee",
        },
        {
            "activity_id": "act2",
            "session_id": "ses_20260701-100000-TEST",
            "start": "2026-07-01T10:00:11+00:00",
            "end": "2026-07-01T10:00:12+00:00",
            "type": "TEXT_ENTRY",
            "app": "AppA",
            "window": "Employee Registration",
            "entities": [{"type": "EMPLOYEE_ID", "value": "EMP001"}],
            "text": "Alice",
            "screen_text": "",
        },
    ]

    validate_segments(segments)
    validate_activities(activities)
    mapped, diag = build_records(segments, activities)

    assert len(mapped) == 2
    assert mapped[0]["inferred_execution_id"] == "WORKFLOW_001_EXEC_0001"
    assert mapped[1]["inferred_execution_id"] == "WORKFLOW_001_EXEC_0002"
    assert mapped[0]["explicit_entities"] == ["EMPLOYEE_ID=EMP001"]
    assert mapped[1]["activity_count"] == 1
    assert diag["assigned_activities"] == 2
    assert diag["unassigned_activities"] == 0

    boundary_segments = [
        {
            "_sid": "ses_boundary",
            "_start": 0.0,
            "_end": 10.0,
            "session_id": "ses_boundary",
            "start": "2026-01-01T00:00:00+00:00",
            "end": "2026-01-01T00:00:10+00:00",
            "label": "W",
        },
        {
            "_sid": "ses_boundary",
            "_start": 10.0,
            "_end": 20.0,
            "session_id": "ses_boundary",
            "start": "2026-01-01T00:00:10+00:00",
            "end": "2026-01-01T00:00:20+00:00",
            "label": "W",
        },
    ]
    boundary_activities = [
        {"activity_id":"p0","_sid":"ses_boundary","_start":10.0,"_end":10.0},
        {"activity_id":"d1","_sid":"ses_boundary","_start":9.0,"_end":11.0},
    ]
    mapped2, diag2 = assign_activities_to_segments(boundary_segments, boundary_activities)
    assert sum(len(v) for v in mapped2.values()) == 2
    assert diag2["assigned_once"] == 2
    assert diag2["unassigned"] == 0
    assert diag2["boundary_tie_to_previous"] == 1

    print("Preflight task2 enrichment self-test: PASS (9 assertions)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enrich final Dataset B segments with execution-level and evidence-level analysis."
    )
    parser.add_argument("--activities", required=False)
    parser.add_argument("--segments", required=False)
    parser.add_argument("--out-dir", required=False)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        return 0

    if not args.activities or not args.segments or not args.out_dir:
        die("--activities, --segments and --out-dir are required unless --self-test is used")

    activities_path = Path(args.activities)
    segments_path = Path(args.segments)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    segments_raw = load_jsonl(segments_path)
    activities_raw = load_jsonl(activities_path)

    validate_segments(segments_raw)
    validate_activities(activities_raw)

    execution_map, diag = build_records(segments_raw, activities_raw)
    workflow_stats = diag["workflow_stats"]

    total_duration = sum(
        parse_ts(s["end"]) - parse_ts(s["start"]) for s in segments_raw
    )

    summary_rows = build_workflow_summary(workflow_stats, total_duration)
    evidence_rows = make_evidence(execution_map, workflow_stats)

    write_jsonl(out_dir / "execution_map.jsonl", execution_map)
    write_jsonl(out_dir / "workflow_evidence.jsonl", evidence_rows)
    write_jsonl(out_dir / "workflow_semantic_cues.jsonl", build_semantic_cues(execution_map, activities_raw))

    with (out_dir / "workflow_summary.csv").open("w", encoding="utf-8", newline="") as f:
        if summary_rows:
            writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
            writer.writeheader()
            writer.writerows(summary_rows)

    anomalies = {
        "activities_total": diag["total_activities"],
        "activities_assigned_to_segments": diag["assigned_activities"],
        "activities_unassigned_to_any_segment": diag["unassigned_activities"],
        "assignment_diagnostics": diag.get("assignment_diag", {}),
        "workflows": len(summary_rows),
        "segments": len(segments_raw),
        "sessions_in_segments": len({s["session_id"] for s in segments_raw}),
        "labels_starting_with_WORK_": sum(
            1 for s in segments_raw if str(s["label"]).startswith("WORK_")
        ),
        "warnings": [],
    }
    if anomalies["activities_assigned_to_segments"] > anomalies["activities_total"]:
        die("internal assignment invariant failed: assigned activity count exceeds total")
    if anomalies["activities_unassigned_to_any_segment"] > 0:
        anomalies["warnings"].append(
            "Some activities did not fall inside any final segment. This may reflect "
            "activity evidence outside inferred work segments and should be reported, "
            "not silently assigned."
        )
    if anomalies["labels_starting_with_WORK_"] > 0:
        anomalies["warnings"].append(
            "Some final labels still start with WORK_. Check whether process discovery was skipped."
        )

    (out_dir / "task2_anomalies.json").write_text(
        json.dumps(anomalies, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    report = {
        "analysis_scope": "Dataset B final segments",
        "segments": len(segments_raw),
        "activities": len(activities_raw),
        "sessions": len({s["session_id"] for s in segments_raw}),
        "workflow_count": len(summary_rows),
        "execution_id_definition": (
            "Each final contiguous segment is represented as one inferred workflow "
            "occurrence. The generated inferred_execution_id is deterministic and "
            "does not claim to be an original source-system execution/case ID."
        ),
        "entity_definition": (
            "Only explicit entries present in the activity `entities` field are "
            "treated as business entities. No IDs are invented from free text."
        ),
        "activity_assignment": {
            "assigned": diag["assigned_activities"],
            "unassigned": diag["unassigned_activities"],
        },
        "workflow_summary_top10": summary_rows[:10],
        "files": {
            "workflow_summary_csv": "workflow_summary.csv",
            "execution_map_jsonl": "execution_map.jsonl",
            "workflow_evidence_jsonl": "workflow_evidence.jsonl",
            "workflow_semantic_cues_jsonl": "workflow_semantic_cues.jsonl",
            "task2_anomalies_json": "task2_anomalies.json",
        },
    }
    (out_dir / "task2_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("TASK-2 WORKFLOW / EXECUTION ENRICHMENT")
    print("=" * 78)
    print(f"Activities:                 {len(activities_raw)}")
    print(f"Final segments:             {len(segments_raw)}")
    print(f"Sessions:                   {len({s['session_id'] for s in segments_raw})}")
    print(f"Workflow clusters:          {len(summary_rows)}")
    print(f"Activities assigned once:   {diag['assigned_activities']}")
    print(f"Activities unassigned:      {diag['unassigned_activities']}")
    print(f"Assignment boundary ties:   {diag.get('assignment_diag', {}).get('boundary_tie_to_previous', 0)}")
    print(f"Multi-overlap resolutions:  {diag.get('assignment_diag', {}).get('multi_overlap_resolved', 0)}")
    print()
    print("Top workflows by occurrence count:")
    for row in summary_rows[:10]:
        print(
            f"  {row['workflow_id']}: "
            f"{row['execution_count']} occurrences | "
            f"{row['total_duration_s']:.1f}s | "
            f"{row['session_count']} sessions | "
            f"{row['unique_variants']} variants | "
            f"dominant={row['dominant_variant_share']:.2f}"
        )
    print()
    print(f"Wrote: {out_dir / 'workflow_summary.csv'}")
    print(f"Wrote: {out_dir / 'execution_map.jsonl'}")
    print(f"Wrote: {out_dir / 'workflow_evidence.jsonl'}")
    print(f"Wrote: {out_dir / 'workflow_semantic_cues.jsonl'}")
    print(f"Wrote: {out_dir / 'task2_report.json'}")
    print(f"Wrote: {out_dir / 'task2_anomalies.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
