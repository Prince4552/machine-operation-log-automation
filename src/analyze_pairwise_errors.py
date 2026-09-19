#!/usr/bin/env python3
"""Diagnose why T0 pairwise grouping makes wrong decisions.

Inputs:
  activities.jsonl
  predicted executions.jsonl
  ground_truth.json
  relationships.jsonl
  pairwise_session_metrics.csv

It reports:
  - per-session pairwise distribution
  - top sessions by FP/FN/F1
  - relationship-evidence signatures behind false-positive (merge) pairs
  - relationship-evidence signatures behind false-negative (split) pairs

The script imports the already-tested pairwise evaluator for GT assignment so
its ownership definition stays identical to the T0 metric.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from pairwise_evaluation import (
    assign_activity_to_gt,
    load_activities,
    load_gt,
    load_predicted_owners,
)

FLAGS = (
    "same_entity",
    "triggered_by",
    "same_window",
    "same_app",
    "same_browser_tab",
    "semantic_match",
    "close_in_time",
    "large_time_gap",
)


def load_relationships(path: Path) -> dict[str, dict[str, dict[str, Any]]]:
    index: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    seen: set[tuple[str, str]] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line:
                continue
            row = json.loads(line)
            a = row["activity_a"]
            b = row["activity_b"]
            pair = tuple(sorted((a, b)))
            if pair in seen:
                raise ValueError(f"Duplicate relationship at line {line_no}: {pair}")
            seen.add(pair)
            features = row["features"]
            index[a][b] = features
            index[b][a] = features
    return dict(index)


def signature(features: dict[str, Any] | None) -> str:
    if not features:
        return "NO_RELATION"
    active = [flag for flag in FLAGS if bool(features.get(flag))]
    if not active:
        return "RELATION_WITH_NO_FLAGS"
    return "+".join(active)


def owner_maps(
    activities_by_session: dict[str, list[dict[str, Any]]],
    gt_by_session: dict[str, list[dict[str, Any]]],
    pred_owner: dict[str, str],
) -> tuple[
    dict[str, str],
    dict[str, str],
    dict[str, list[str]],
    dict[str, list[str]],
]:
    global_pred: dict[str, str] = {}
    global_gt: dict[str, str] = {}
    pred_groups: dict[str, list[str]] = defaultdict(list)
    gt_groups: dict[str, list[str]] = defaultdict(list)

    for sid, activities in sorted(activities_by_session.items()):
        gt_segments = gt_by_session[sid]
        for activity in activities:
            aid = activity["activity_id"]
            p = pred_owner.get(aid, f"__PRED_UNASSIGNED__:{aid}")
            g, _ = assign_activity_to_gt(activity, gt_segments)
            if g is None:
                g = f"__GT_UNASSIGNED__:{aid}"
            global_pred[aid] = p
            global_gt[aid] = g
            if not p.startswith("__PRED_UNASSIGNED__:"):
                pred_groups[f"{sid}::{p}"].append(aid)
            if not g.startswith("__GT_UNASSIGNED__:"):
                gt_groups[f"{sid}::{g}"].append(aid)

    return global_pred, global_gt, dict(pred_groups), dict(gt_groups)


def aggregate_error_signatures(
    groups: dict[str, list[str]],
    pred_owner: dict[str, str],
    gt_owner: dict[str, str],
    rel_index: dict[str, dict[str, dict[str, Any]]],
    want: str,
) -> Counter[str]:
    counts: Counter[str] = Counter()
    for members in groups.values():
        for a, b in itertools.combinations(members, 2):
            same_gt = gt_owner[a] == gt_owner[b]
            same_pred = pred_owner[a] == pred_owner[b]
            is_error = (
                want == "FP" and same_pred and not same_gt
            ) or (
                want == "TP" and same_pred and same_gt
            )
            if is_error:
                counts[signature(rel_index.get(a, {}).get(b))] += 1
    return counts


def aggregate_fn_signatures(
    groups: dict[str, list[str]],
    pred_owner: dict[str, str],
    gt_owner: dict[str, str],
    rel_index: dict[str, dict[str, dict[str, Any]]],
) -> Counter[str]:
    counts: Counter[str] = Counter()
    for members in groups.values():
        for a, b in itertools.combinations(members, 2):
            if gt_owner[a] == gt_owner[b] and pred_owner[a] != pred_owner[b]:
                counts[signature(rel_index.get(a, {}).get(b))] += 1
    return counts


def load_session_csv(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            numeric = dict(row)
            for key, value in list(numeric.items()):
                if key == "session_id":
                    continue
                try:
                    numeric[key] = float(value)
                except (TypeError, ValueError):
                    pass
            rows.append(numeric)
    return rows


def percent(n: int, d: int) -> float:
    return 100.0 * n / d if d else 0.0


def print_signature_table(title: str, counts: Counter[str], limit: int = 12) -> None:
    total = sum(counts.values())
    print(f"\n{title}")
    print("-" * 90)
    print(f"{'signature':55s} {'count':>12s} {'share':>10s}")
    for key, count in counts.most_common(limit):
        print(f"{key:55s} {count:12d} {percent(count, total):9.2f}%")
    if total == 0:
        print("(none)")


def self_test() -> None:
    assert signature(None) == "NO_RELATION"
    assert signature({}) == "NO_RELATION"
    assert signature({"same_window": True, "close_in_time": True}) == "same_window+close_in_time"
    assert signature({"same_entity": True, "same_app": True}) == "same_entity+same_app"
    assert percent(1, 4) == 25.0
    print("Preflight pairwise error-analysis self-test: PASS (5 cases)")


def main() -> int:
    self_test()

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--activities", required=True, type=Path)
    ap.add_argument("--predicted-executions", required=True, type=Path)
    ap.add_argument("--gt", required=True, type=Path)
    ap.add_argument("--relationships", required=True, type=Path)
    ap.add_argument("--session-metrics", required=True, type=Path)
    args = ap.parse_args()

    activities_by_session = load_activities(args.activities)
    gt_by_session = load_gt(args.gt)
    pred_owner, _, _ = load_predicted_owners(args.predicted_executions)
    rel_index = load_relationships(args.relationships)
    session_rows = load_session_csv(args.session_metrics)

    pred_map, gt_map, pred_groups, gt_groups = owner_maps(
        activities_by_session, gt_by_session, pred_owner
    )

    fp_sigs = aggregate_error_signatures(pred_groups, pred_map, gt_map, rel_index, "FP")
    tp_sigs = aggregate_error_signatures(pred_groups, pred_map, gt_map, rel_index, "TP")
    fn_sigs = aggregate_fn_signatures(gt_groups, pred_map, gt_map, rel_index)

    print("\nPAIRWISE ERROR ANALYSIS")
    print("=" * 90)
    print(f"Sessions:                 {len(activities_by_session)}")
    print(f"Activities:               {sum(map(len, activities_by_session.values()))}")
    print(f"Relationship pairs:       {sum(len(v) for v in rel_index.values()) // 2}")

    f1s = [float(r["f1"]) for r in session_rows]
    precisions = [float(r["precision"]) for r in session_rows]
    recalls = [float(r["recall"]) for r in session_rows]
    print("\nPER-SESSION DISTRIBUTION")
    print("-" * 90)
    for name, values in (("precision", precisions), ("recall", recalls), ("f1", f1s)):
        print(
            f"{name:10s} mean={statistics.mean(values):.4f} "
            f"median={statistics.median(values):.4f} "
            f"min={min(values):.4f} max={max(values):.4f}"
        )
    print(f"sessions F1 < 0.25: {sum(v < 0.25 for v in f1s)}")
    print(f"sessions F1 < 0.50: {sum(v < 0.50 for v in f1s)}")
    print(f"sessions F1 >= 0.75: {sum(v >= 0.75 for v in f1s)}")

    def show_ranked(title: str, key: str, reverse: bool = True) -> None:
        print(f"\n{title}")
        print("-" * 90)
        rows = sorted(session_rows, key=lambda r: float(r[key]), reverse=reverse)[:10]
        for r in rows:
            print(
                f"{r['session_id']}  "
                f"P={float(r['precision']):.3f} "
                f"R={float(r['recall']):.3f} "
                f"F1={float(r['f1']):.3f} "
                f"TP={int(float(r['true_positive_pairs']))} "
                f"FP={int(float(r['false_positive_pairs']))} "
                f"FN={int(float(r['false_negative_pairs']))}"
            )

    show_ranked("10 LOWEST-F1 SESSIONS", "f1", reverse=False)
    show_ranked("10 HIGHEST-FP SESSIONS (MERGE PRESSURE)", "false_positive_pairs")
    show_ranked("10 HIGHEST-FN SESSIONS (SPLIT PRESSURE)", "false_negative_pairs")

    print_signature_table("FALSE-POSITIVE PAIRS: WHAT EVIDENCE CONNECTED THEM?", fp_sigs)
    print_signature_table("TRUE-POSITIVE PAIRS: WHAT EVIDENCE CONNECTED THEM?", tp_sigs)
    print_signature_table("FALSE-NEGATIVE PAIRS: WHAT EVIDENCE WAS MISSING?", fn_sigs)

    print("\nINTERPRETATION FLAGS")
    print("-" * 90)
    fp_total = sum(fp_sigs.values())
    fp_weak_time_context = fp_sigs["same_window+close_in_time"] + fp_sigs["same_app+close_in_time"]
    tp_total = sum(tp_sigs.values())
    print(
        f"FP pairs explained by exact same-window/app + time-only signatures: "
        f"{fp_weak_time_context}/{fp_total} ({percent(fp_weak_time_context, fp_total):.2f}%)"
    )
    no_rel_fp = fp_sigs["NO_RELATION"]
    print(
        f"FP pairs with no stored relationship edge: "
        f"{no_rel_fp}/{fp_total} ({percent(no_rel_fp, fp_total):.2f}%)"
    )
    print(
        "A high first percentage is evidence that the context-continuation rule is too permissive."
    )
    print(
        "A high NO_RELATION share in FN errors points toward missing candidate generation / evidence,"
        "not merely a bad grouping threshold."
    )

    print("\nDONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
