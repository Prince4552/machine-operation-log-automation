#!/usr/bin/env python3
"""
Controlled ablation of the T0 grouping algorithm.

Experiment:
    Disable ONLY context-only continuation and keep strong evidence unchanged.

This is a DIAGNOSTIC experiment for logical execution grouping.
It must NOT be treated as a final segments.jsonl producer because disabling
context continuation can expose overlapping activity intervals that the normal
T0 output contract rejects.

The experiment is useful because the pairwise evaluator operates on logical
execution membership, not on non-overlapping segment geometry.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
import sys
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{line_no}: expected JSON object")
            rows.append(obj)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def make_activity(aid: str, start_second: int, end_second: int) -> dict[str, Any]:
    return {
        "activity_id": aid,
        "session_id": "ses_ablation",
        "start": f"2026-01-01T00:00:{start_second:02d}.000+00:00",
        "end": f"2026-01-01T00:00:{end_second:02d}.000+00:00",
        "type": "CLICK",
        "app": "app",
        "window": "window",
        "browser_tab": "tab",
        "browser_url": "",
        "entities": [],
        "source_layers": ["L2"],
    }


def run_case(
    pg,
    activities: list[dict[str, Any]],
    relationship_rows: list[dict[str, Any]],
):
    by_session = pg.validate_activities(activities)
    relationship_index = pg.build_relationship_index(relationship_rows)

    for row in relationship_rows:
        a = row["activity_a"]
        b = row["activity_b"]
        assert b in relationship_index[a], (
            f"relationship index missing forward link {a} -> {b}"
        )
        assert a in relationship_index[b], (
            f"relationship index missing reverse link {b} -> {a}"
        )

    return pg.reconstruct_session(
        "ses_ablation",
        by_session["ses_ablation"],
        relationship_index,
    )


def preflight(pg) -> None:
    """
    Five deterministic cases:
      1. strong same-entity relation still joins;
      2. context-only relation does not join after ablation;
      3. strong relation still bridges a long interruption;
      4. no relation starts a new execution;
      5. overlapping activity intervals are allowed by the diagnostic layer.
    """
    pg.CONTEXT_CONTINUATION_MAX_SECONDS = -1.0

    # Case 1: strong evidence preserved.
    acts = [make_activity("a1", 0, 1), make_activity("a2", 1, 2)]
    for item in acts:
        item["entities"] = [{"type": "CASE_ID", "value": "CASE-0001-01"}]
    rel = [{
        "activity_a": "a1",
        "activity_b": "a2",
        "features": {"score": 5, "same_entity": True, "triggered_by": False},
    }]
    executions, _ = run_case(pg, acts, rel)
    assert [e.activity_ids for e in executions] == [["a1", "a2"]], (
        f"case 1 failed: {[e.activity_ids for e in executions]}"
    )

    # Case 2: context-only relation must not join.
    acts = [make_activity("b1", 0, 1), make_activity("b2", 1, 2)]
    rel = [{
        "activity_a": "b1",
        "activity_b": "b2",
        "features": {
            "score": 3,
            "same_entity": False,
            "triggered_by": False,
            "same_window": True,
            "same_app": True,
            "same_browser_tab": True,
            "close_in_time": True,
        },
    }]
    executions, _ = run_case(pg, acts, rel)
    assert [e.activity_ids for e in executions] == [["b1"], ["b2"]], (
        f"case 2 failed: {[e.activity_ids for e in executions]}"
    )

    # Case 3: strong relation can bridge a longer interruption.
    acts = [make_activity("c1", 0, 1), make_activity("c2", 10, 11)]
    for item in acts:
        item["entities"] = [{"type": "CASE_ID", "value": "CASE-0002-01"}]
    rel = [{
        "activity_a": "c1",
        "activity_b": "c2",
        "features": {"score": 5, "same_entity": True, "triggered_by": False},
    }]
    executions, _ = run_case(pg, acts, rel)
    assert len(executions) == 1, f"case 3 failed: {len(executions)} executions"

    # Case 4: no relation stays split even under identical context.
    acts = [make_activity("d1", 0, 1), make_activity("d2", 1, 2)]
    executions, _ = run_case(pg, acts, [])
    assert [e.activity_ids for e in executions] == [["d1"], ["d2"]], (
        f"case 4 failed: {[e.activity_ids for e in executions]}"
    )

    # Case 5: the diagnostic must not call the normal non-overlap invariant
    # here; overlapping activity intervals can legitimately expose themselves
    # under an ablation. We only verify that both activities remain assigned.
    acts = [make_activity("e1", 0, 3), make_activity("e2", 1, 4)]
    executions, _ = run_case(pg, acts, [])
    assert sorted(aid for e in executions for aid in e.activity_ids) == ["e1", "e2"]

    print("Preflight ablation self-test: PASS (5 cases)")


def interval_seconds(value: str) -> float:
    from datetime import datetime
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError(f"Timestamp missing timezone: {value!r}")
    return dt.timestamp()


def validate_diagnostic_execution_membership(
    by_session: dict[str, list[dict[str, Any]]],
    executions_by_session: dict[str, list[Any]],
    segments: list[dict[str, Any]],
) -> int:
    """
    Validate the properties needed by the pairwise diagnostic.

    Unlike process_groups.self_check(), this intentionally does NOT reject
    overlapping candidate segments. We count them and report them as a
    diagnostic consequence of the ablation.
    """
    overlap_count = 0

    for session_id, activities in by_session.items():
        all_ids = [a["activity_id"] for a in activities]
        if len(all_ids) != len(set(all_ids)):
            raise AssertionError(f"Duplicate activity IDs in {session_id}")

        assigned: list[str] = []
        for execution in executions_by_session.get(session_id, []):
            if not execution.activity_ids:
                raise AssertionError(
                    f"Empty execution {execution.execution_id} in {session_id}"
                )
            assigned.extend(execution.activity_ids)

        assigned_set = set(assigned)
        missing = set(all_ids) - assigned_set
        unexpected_missing = {
            aid for aid in missing
            if not any(
                activity["activity_id"] == aid
                and execution_is_system_unassigned(activity)
                for activity in activities
            )
        }
        if unexpected_missing:
            raise AssertionError(
                f"Unexpected unassigned activities in {session_id}: "
                f"{sorted(unexpected_missing)[:5]}"
            )

        if len(assigned) != len(set(assigned)):
            raise AssertionError(
                f"Activity assigned to multiple logical executions in {session_id}"
            )

    by_session_segments: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for segment in segments:
        start = interval_seconds(segment["start"])
        end = interval_seconds(segment["end"])
        if end <= start:
            raise AssertionError(f"Non-positive diagnostic segment: {segment}")
        by_session_segments[segment["session_id"]].append(segment)

    for session_id, rows in by_session_segments.items():
        rows.sort(key=lambda row: (interval_seconds(row["start"]), interval_seconds(row["end"])))
        for previous, current in zip(rows, rows[1:]):
            if interval_seconds(current["start"]) < interval_seconds(previous["end"]):
                overlap_count += 1

    return overlap_count


def execution_is_system_unassigned(activity: dict[str, Any]) -> bool:
    layers = {
        str(value).upper()
        for value in activity.get("source_layers", [])
        if isinstance(value, str)
    }
    return (
        str(activity.get("type", "")).upper() in {"OTHER"}
        and layers
        and layers.issubset({"SYSTEM"})
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a diagnostic no-context-continuation ablation of "
            "process_groups.py."
        )
    )
    parser.add_argument("--activities", required=True, type=Path)
    parser.add_argument("--relationships", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

    src_dir = Path(__file__).resolve().parent
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    import process_groups as pg

    preflight(pg)

    activity_records = load_jsonl(args.activities)
    relationship_records = load_jsonl(args.relationships)

    by_session = pg.validate_activities(activity_records)
    relationship_index = pg.build_relationship_index(relationship_records)

    executions_by_session: dict[str, list[Any]] = {}
    all_execution_records: list[dict[str, Any]] = []
    all_segments: list[dict[str, Any]] = []
    session_summaries: list[dict[str, Any]] = []

    # Safety: this experiment must operate with context continuation disabled.
    pg.CONTEXT_CONTINUATION_MAX_SECONDS = -1.0

    for session_id, activities in sorted(by_session.items()):
        executions, summary = pg.reconstruct_session(
            session_id,
            activities,
            relationship_index,
        )
        executions_by_session[session_id] = executions
        session_summaries.append(summary)

        for execution in executions:
            all_execution_records.append(pg.execution_record(execution, activities))

        all_segments.extend(pg.build_segment_records(executions, activities))

    overlap_count = validate_diagnostic_execution_membership(
        by_session,
        executions_by_session,
        all_segments,
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "experiment": "context_only_continuation_disabled",
        "diagnostic_only": True,
        "do_not_use_as_final_segments": True,
        "context_continuation_max_seconds": -1.0,
        "sessions": len(by_session),
        "activities": len(activity_records),
        "logical_executions": len(all_execution_records),
        "candidate_segments": len(all_segments),
        "overlapping_candidate_segment_boundaries": overlap_count,
        "unassigned_activities": sum(
            row["unassigned_activities"] for row in session_summaries
        ),
        "singleton_executions": sum(
            row["singleton_executions"] for row in session_summaries
        ),
        "membership_self_check": "PASS",
    }

    write_jsonl(args.out_dir / "executions.jsonl", all_execution_records)
    write_jsonl(args.out_dir / "segments_candidates.jsonl", all_segments)
    (args.out_dir / "grouping_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print()
    print("CONTEXT-CONTINUATION ABLATION")
    print("=" * 78)
    print("Context-only continuation: DISABLED (threshold = -1s)")
    print("Experiment type:          DIAGNOSTIC ONLY")
    print(f"Sessions:                 {summary['sessions']}")
    print(f"Activities:               {summary['activities']}")
    print(f"Logical executions:       {summary['logical_executions']}")
    print(f"Candidate segments:       {summary['candidate_segments']}")
    print(f"Overlapping segment pairs: {summary['overlapping_candidate_segment_boundaries']}")
    print(f"UNASSIGNED activities:    {summary['unassigned_activities']}")
    print(f"Singleton executions:     {summary['singleton_executions']}")
    print("Membership self-check:    PASS")
    print()
    print(f"Wrote: {args.out_dir / 'executions.jsonl'}")
    print(f"Wrote: {args.out_dir / 'segments_candidates.jsonl'}")
    print(f"Wrote: {args.out_dir / 'grouping_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
