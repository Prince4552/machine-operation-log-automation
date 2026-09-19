
#!/usr/bin/env python3
"""
T0 pairwise same-process evaluation for Dataset A.

Question:
    For every pair of activities in a session, do prediction and GT agree
    on whether the two activities belong to the same process execution?

Inputs:
    --activities
        Atomic activity JSONL. Required fields include:
        activity_id, session_id, start, end.

    --predicted-executions
        process_groups.py executions.jsonl. Each execution contains:
        execution_id, session_id, activity_ids.

    --gt
        evaluation.py / ground_truth.py output:
        {"sessions": [{"session_id": ..., "segments": [...]}]}

GT activity assignment:
    Each activity is assigned to the GT segment with the largest positive
    temporal overlap. If it overlaps no GT segment, it gets a unique
    UNASSIGNED owner, so non-business activities cannot accidentally count
    as a true same-process pair.

Predicted activity assignment:
    Activity IDs listed in one predicted execution share that execution.
    Activities absent from all predicted executions get a unique UNASSIGNED
    owner.

Pairwise evaluation does NOT materialize O(N^2) pairs. It uses contingency
counts:
    TP = sum over (pred_owner, gt_owner) C(intersection_count, 2)
         minus any pair counted under different predicted/GT owners.
More directly, for each predicted cluster p and GT cluster g:
    n = |p ∩ g|
    TP += C(n, 2)

Predicted positive pairs:
    sum_p C(|p|, 2)

GT positive pairs:
    sum_g C(|g|, 2)

Then:
    precision = TP / predicted_positive_pairs
    recall    = TP / gt_positive_pairs
    F1        = harmonic mean

Additional diagnostics:
    activity assignment coverage
    GT ambiguity count (activity overlaps multiple GT segments)
    predicted execution coverage
    number of predicted/GT execution groups
    pairwise Jaccard
    per-session metrics
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def parse_ts(value: str) -> float:
    from datetime import datetime
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError(f"Timestamp must include timezone: {value!r}")
    return dt.timestamp()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line:
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{line_no} is not a JSON object")
            rows.append(obj)
    return rows


def load_gt(path: Path) -> dict[str, list[dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("sessions"), list):
        raise ValueError("GT must contain a top-level 'sessions' list")

    result: dict[str, list[dict[str, Any]]] = {}
    for session in data["sessions"]:
        if not isinstance(session, dict):
            raise ValueError("GT session is not an object")
        sid = session.get("session_id")
        segments = session.get("segments")
        if not isinstance(sid, str) or not sid:
            raise ValueError("GT session has invalid session_id")
        if not isinstance(segments, list):
            raise ValueError(f"GT session {sid!r} has no segments list")

        cleaned = []
        for seg in segments:
            if not isinstance(seg, dict):
                raise ValueError(f"GT segment in {sid!r} is not an object")
            start = parse_ts(seg["start"])
            end = parse_ts(seg["end"])
            if end <= start:
                raise ValueError(f"GT segment has non-positive duration in {sid!r}")
            cleaned.append(
                {
                    **seg,
                    "_start": start,
                    "_end": end,
                    "_owner": str(seg.get("execution_id") or seg.get("segment_id")),
                }
            )
        cleaned.sort(key=lambda x: (x["_start"], x["_end"]))
        result[sid] = cleaned
    return result


def load_activities(path: Path) -> dict[str, list[dict[str, Any]]]:
    rows = load_jsonl(path)
    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_ids: set[str] = set()

    for row in rows:
        aid = row.get("activity_id")
        sid = row.get("session_id")
        if not isinstance(aid, str) or not aid:
            raise ValueError("Activity missing activity_id")
        if aid in seen_ids:
            raise ValueError(f"Duplicate activity_id: {aid}")
        if not isinstance(sid, str) or not sid:
            raise ValueError(f"Activity {aid!r} missing session_id")

        start = parse_ts(row["start"])
        end = parse_ts(row["end"])
        if end < start:
            raise ValueError(f"Activity has end before start: {aid}")

        by_session[sid].append(
            {
                **row,
                "_start": start,
                "_end": end,
            }
        )
        seen_ids.add(aid)

    for rows_for_session in by_session.values():
        rows_for_session.sort(key=lambda x: (x["_start"], x["_end"], x["activity_id"]))

    return dict(by_session)


def load_predicted_owners(
    path: Path,
) -> tuple[dict[str, str], Counter[str], set[str]]:
    rows = load_jsonl(path)
    activity_owner: dict[str, str] = {}
    execution_counts: Counter[str] = Counter()
    execution_sessions: dict[str, str] = {}

    for row in rows:
        execution_id = row.get("execution_id")
        session_id = row.get("session_id")
        activity_ids = row.get("activity_ids")

        if not isinstance(execution_id, str) or not execution_id:
            raise ValueError("Predicted execution missing execution_id")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError(f"Predicted execution {execution_id!r} missing session_id")
        if not isinstance(activity_ids, list):
            raise ValueError(f"Predicted execution {execution_id!r} missing activity_ids list")

        execution_counts[session_id] += 1
        execution_sessions[execution_id] = session_id

        for activity_id in activity_ids:
            if not isinstance(activity_id, str):
                raise ValueError(f"Invalid activity ID under {execution_id!r}")
            previous = activity_owner.get(activity_id)
            if previous is not None and previous != execution_id:
                raise ValueError(
                    f"Activity {activity_id!r} assigned to multiple predicted executions: "
                    f"{previous!r}, {execution_id!r}"
                )
            activity_owner[activity_id] = execution_id

    return activity_owner, execution_counts, set(execution_sessions)


def overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def assign_activity_to_gt(
    activity: dict[str, Any],
    gt_segments: list[dict[str, Any]],
) -> tuple[str | None, bool]:
    """
    Return (owner, ambiguous).

    The activity is assigned to the GT execution with greatest positive
    temporal overlap. If multiple segments tie for the maximum overlap,
    choose deterministically by:
      1. earliest GT start
      2. execution_id
    """
    candidates = []
    for seg in gt_segments:
        ov = overlap(activity["_start"], activity["_end"], seg["_start"], seg["_end"])

        # Instantaneous activities: treat exact containment at the timestamp
        # as overlap. This keeps click/app-switch activities evaluable.
        if ov == 0.0 and activity["_start"] == activity["_end"]:
            if seg["_start"] <= activity["_start"] <= seg["_end"]:
                ov = 1e-12

        if ov > 0:
            candidates.append((ov, seg["_start"], seg["_owner"], seg))

    if not candidates:
        return None, False

    candidates.sort(key=lambda x: (-x[0], x[1], x[2]))
    best_overlap = candidates[0][0]
    tied = sum(math.isclose(c[0], best_overlap, rel_tol=0.0, abs_tol=1e-12) for c in candidates)
    ambiguous = len(candidates) > 1 and tied > 1

    return candidates[0][2], ambiguous


def choose2(n: int) -> int:
    if n < 2:
        return 0
    return n * (n - 1) // 2


def pairwise_from_assignments(
    pred_owner: dict[str, str],
    gt_owner: dict[str, str],
    activity_ids: list[str],
) -> dict[str, Any]:
    pred_sizes: Counter[str] = Counter()
    gt_sizes: Counter[str] = Counter()
    intersections: Counter[tuple[str, str]] = Counter()

    for aid in activity_ids:
        p = pred_owner[aid]
        g = gt_owner[aid]
        pred_sizes[p] += 1
        gt_sizes[g] += 1
        intersections[(p, g)] += 1

    predicted_positive = sum(choose2(n) for n in pred_sizes.values())
    gt_positive = sum(choose2(n) for n in gt_sizes.values())
    tp = sum(choose2(n) for n in intersections.values())

    fp = predicted_positive - tp
    fn = gt_positive - tp

    precision = tp / predicted_positive if predicted_positive else 0.0
    recall = tp / gt_positive if gt_positive else 0.0
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    union = tp + fp + fn
    jaccard = tp / union if union else 0.0

    return {
        "activities_evaluated": len(activity_ids),
        "predicted_positive_pairs": predicted_positive,
        "ground_truth_positive_pairs": gt_positive,
        "true_positive_pairs": tp,
        "false_positive_pairs": fp,
        "false_negative_pairs": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "jaccard": jaccard,
        "predicted_execution_groups": len(pred_sizes),
        "gt_execution_groups": len(gt_sizes),
        "max_pred_group_size": max(pred_sizes.values(), default=0),
        "max_gt_group_size": max(gt_sizes.values(), default=0),
    }


def run_evaluation(
    activities_by_session: dict[str, list[dict[str, Any]]],
    gt_by_session: dict[str, list[dict[str, Any]]],
    pred_activity_owner: dict[str, str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    session_rows = []
    global_pred_owner: dict[str, str] = {}
    global_gt_owner: dict[str, str] = {}

    total_ambiguous = 0
    total_gt_assigned = 0
    total_pred_assigned = 0
    total_activity_count = 0

    for sid in sorted(activities_by_session):
        activities = activities_by_session[sid]
        gt_segments = gt_by_session.get(sid, [])
        p_owners: dict[str, str] = {}
        g_owners: dict[str, str] = {}

        for activity in activities:
            aid = activity["activity_id"]
            total_activity_count += 1

            pred = pred_activity_owner.get(aid)
            if pred is None:
                pred = f"__PRED_UNASSIGNED__:{aid}"
            p_owners[aid] = pred

            gt, ambiguous = assign_activity_to_gt(activity, gt_segments)
            if gt is None:
                gt = f"__GT_UNASSIGNED__:{aid}"
            else:
                total_gt_assigned += 1
            total_ambiguous += int(ambiguous)

            if aid in pred_activity_owner:
                total_pred_assigned += 1

            g_owners[aid] = gt
            global_pred_owner[aid] = pred
            global_gt_owner[aid] = gt

        m = pairwise_from_assignments(
            p_owners,
            g_owners,
            list(p_owners),
        )
        m["session_id"] = sid
        m["gt_assigned_activity_count"] = sum(
            not owner.startswith("__GT_UNASSIGNED__:") for owner in g_owners.values()
        )
        m["pred_assigned_activity_count"] = sum(
            aid in pred_activity_owner for aid in p_owners
        )
        m["gt_ambiguous_activity_count"] = sum(
            assign_activity_to_gt(a, gt_segments)[1]
            for a in activities
        )
        session_rows.append(m)

    global_metrics = pairwise_from_assignments(
        global_pred_owner,
        global_gt_owner,
        list(global_pred_owner),
    )
    global_metrics.update(
        {
            "sessions": len(session_rows),
            "total_activities": total_activity_count,
            "gt_assigned_activities": total_gt_assigned,
            "pred_assigned_activities": total_pred_assigned,
            "gt_assignment_coverage": (
                total_gt_assigned / total_activity_count
                if total_activity_count
                else 0.0
            ),
            "pred_assignment_coverage": (
                total_pred_assigned / total_activity_count
                if total_activity_count
                else 0.0
            ),
            "gt_ambiguous_activities": total_ambiguous,
            "gt_ambiguous_rate": (
                total_ambiguous / total_activity_count
                if total_activity_count
                else 0.0
            ),
        }
    )

    return global_metrics, session_rows


def self_test() -> None:
    # 1. Perfect two clusters.
    pred = {"a": "P1", "b": "P1", "c": "P2", "d": "P2"}
    gt = {"a": "G1", "b": "G1", "c": "G2", "d": "G2"}
    m = pairwise_from_assignments(pred, gt, ["a", "b", "c", "d"])
    assert m["true_positive_pairs"] == 2
    assert m["false_positive_pairs"] == 0
    assert m["false_negative_pairs"] == 0
    assert m["f1"] == 1.0

    # 2. All merged: two GT positives, two cross-cluster false positives.
    pred = {"a": "P1", "b": "P1", "c": "P1", "d": "P1"}
    gt = {"a": "G1", "b": "G1", "c": "G2", "d": "G2"}
    m = pairwise_from_assignments(pred, gt, ["a", "b", "c", "d"])
    assert m["true_positive_pairs"] == 2
    assert m["false_positive_pairs"] == 4
    assert m["false_negative_pairs"] == 0

    # 3. All split: GT positives become false negatives.
    pred = {"a": "P1", "b": "P2", "c": "P3", "d": "P4"}
    gt = {"a": "G1", "b": "G1", "c": "G2", "d": "G2"}
    m = pairwise_from_assignments(pred, gt, ["a", "b", "c", "d"])
    assert m["true_positive_pairs"] == 0
    assert m["false_positive_pairs"] == 0
    assert m["false_negative_pairs"] == 2

    # 4. Unassigned unique owners cannot create positive pairs.
    pred = {"a": "P1", "b": "P1", "c": "U:c", "d": "U:d"}
    gt = {"a": "G1", "b": "G1", "c": "UG:c", "d": "UG:d"}
    m = pairwise_from_assignments(pred, gt, ["a", "b", "c", "d"])
    assert m["true_positive_pairs"] == 1
    assert m["false_positive_pairs"] == 0
    assert m["false_negative_pairs"] == 0

    # 5. Larger combinatorial count.
    pred = {str(i): "P" for i in range(5)}
    gt = {str(i): "G" for i in range(5)}
    m = pairwise_from_assignments(pred, gt, list(pred))
    assert m["true_positive_pairs"] == 10
    assert m["predicted_positive_pairs"] == 10
    assert m["ground_truth_positive_pairs"] == 10

    # 6. Timestamp parser.
    assert isinstance(parse_ts("2026-01-01T00:00:00Z"), float)

    # 7-12. Interval overlap edge cases.
    assert overlap(0, 10, 2, 8) == 6
    assert overlap(0, 10, 10, 20) == 0
    assert overlap(0, 10, -5, 5) == 5
    assert overlap(0, 10, 0, 10) == 10
    assert overlap(5, 5, 0, 10) == 0
    assert overlap(0, 1, 2, 3) == 0

    # 13. Choose2 edge cases.
    assert choose2(0) == 0
    assert choose2(1) == 0
    assert choose2(2) == 1
    assert choose2(5) == 10

    print("Preflight pairwise self-test: PASS (13 cases)")


def main() -> int:
    self_test()

    ap = argparse.ArgumentParser(
        description="Evaluate pairwise same-process F1 for Dataset A."
    )
    ap.add_argument("--activities", required=True, type=Path)
    ap.add_argument("--predicted-executions", required=True, type=Path)
    ap.add_argument("--gt", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    args = ap.parse_args()

    activities_by_session = load_activities(args.activities)
    gt_by_session = load_gt(args.gt)
    pred_owner, pred_execution_counts, pred_execution_ids = load_predicted_owners(
        args.predicted_executions
    )

    known_activity_ids = {
        activity["activity_id"]
        for rows in activities_by_session.values()
        for activity in rows
    }
    unknown_predicted_ids = sorted(set(pred_owner) - known_activity_ids)
    if unknown_predicted_ids:
        raise ValueError(
            f"Predicted executions reference {len(unknown_predicted_ids)} unknown "
            f"activity IDs; first examples: {unknown_predicted_ids[:5]}"
        )

    # Every GT session represented in activities should exist in GT, otherwise
    # we cannot assign a meaningful ground-truth owner.
    missing_gt_sessions = sorted(set(activities_by_session) - set(gt_by_session))
    if missing_gt_sessions:
        raise ValueError(
            f"Activities contain {len(missing_gt_sessions)} sessions absent from GT; "
            f"examples: {missing_gt_sessions[:5]}"
        )

    metrics, session_rows = run_evaluation(
        activities_by_session,
        gt_by_session,
        pred_owner,
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "evaluation": {
            "definition": (
                "Same-process activity pairs. GT ownership is assigned by "
                "maximum temporal overlap with GT contiguous segments. "
                "Activities outside GT process intervals receive unique "
                "UNASSIGNED owners. Predicted owners come from predicted "
                "execution membership; predicted-unassigned activities also "
                "receive unique owners."
            ),
            "sessions": metrics["sessions"],
            "total_activities": metrics["total_activities"],
            "gt_execution_groups": metrics["gt_execution_groups"],
            "predicted_execution_groups": metrics["predicted_execution_groups"],
            "gt_assignment_coverage": metrics["gt_assignment_coverage"],
            "pred_assignment_coverage": metrics["pred_assignment_coverage"],
            "gt_ambiguous_activities": metrics["gt_ambiguous_activities"],
            "gt_ambiguous_rate": metrics["gt_ambiguous_rate"],
            "predicted_positive_pairs": metrics["predicted_positive_pairs"],
            "ground_truth_positive_pairs": metrics["ground_truth_positive_pairs"],
            "true_positive_pairs": metrics["true_positive_pairs"],
            "false_positive_pairs": metrics["false_positive_pairs"],
            "false_negative_pairs": metrics["false_negative_pairs"],
            "precision": metrics["precision"],
            "recall": metrics["recall"],
            "f1": metrics["f1"],
            "jaccard": metrics["jaccard"],
            "max_pred_group_size": metrics["max_pred_group_size"],
            "max_gt_group_size": metrics["max_gt_group_size"],
        }
    }

    (args.out_dir / "pairwise_summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    with (args.out_dir / "pairwise_session_metrics.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        fields = list(session_rows[0].keys()) if session_rows else ["session_id"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(session_rows)

    print()
    print("DATASET A PAIRWISE SAME-PROCESS EVALUATION")
    print("=" * 78)
    print(f"Sessions:                     {metrics['sessions']}")
    print(f"Activities evaluated:         {metrics['total_activities']}")
    print(f"GT execution groups:          {metrics['gt_execution_groups']}")
    print(f"Predicted execution groups:   {metrics['predicted_execution_groups']}")
    print(f"GT assignment coverage:       {metrics['gt_assignment_coverage']:.4f}")
    print(f"Pred assignment coverage:     {metrics['pred_assignment_coverage']:.4f}")
    print(f"GT ambiguous activities:      {metrics['gt_ambiguous_activities']}")
    print(f"GT ambiguous rate:            {metrics['gt_ambiguous_rate']:.4f}")
    print()
    print("PAIRWISE METRICS")
    print("-" * 78)
    print(f"Predicted positive pairs:     {metrics['predicted_positive_pairs']}")
    print(f"Ground-truth positive pairs:  {metrics['ground_truth_positive_pairs']}")
    print(f"True-positive pairs:          {metrics['true_positive_pairs']}")
    print(f"False-positive pairs:         {metrics['false_positive_pairs']}")
    print(f"False-negative pairs:         {metrics['false_negative_pairs']}")
    print(f"Precision:                    {metrics['precision']:.6f}")
    print(f"Recall:                       {metrics['recall']:.6f}")
    print(f"F1:                           {metrics['f1']:.6f}")
    print(f"Jaccard:                      {metrics['jaccard']:.6f}")
    print()
    print("OUTPUTS")
    print("-" * 78)
    print(args.out_dir / "pairwise_summary.json")
    print(args.out_dir / "pairwise_session_metrics.csv")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
