
#!/usr/bin/env python3
"""
Controlled parameter sweep for Dataset A process grouping.

IMPORTANT:
- Does NOT modify src/process_groups.py.
- Does NOT modify activities.jsonl or relationships.jsonl.
- Runs reconstruction in memory for each configuration.
- Writes only diagnostic sweep results.

Dimension A: context continuation gap
    5, 10, 15, 20, 30, 45 seconds

Dimension B: minimum context relationship score
    3, 4, 5

The current system is A=12s, B=3. That exact configuration is also
evaluated as the baseline row, so the sweep can be compared against the
currently committed result.

For each configuration we calculate:
- boundary Precision / Recall / F1 at ±0.5, ±1, ±2, ±5s
- predicted/GT segment-count ratio
- temporal precision / recall / F1
- GT fragmentation rate
- predicted merge rate
- IoU diagnostics
- predicted duration median / p25 / p75
- logical execution count
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path


TOLS = (0.5, 1.0, 2.0, 5.0)
A_VALUES = (5.0, 10.0, 15.0, 20.0, 30.0, 45.0)
B_VALUES = (3, 4, 5)


def load_module(module_path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def parse_ts(value: str) -> float:
    from datetime import datetime
    text = value
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).timestamp()


def boundary_list(segments):
    """Return sorted numeric boundary timestamps from normalized segments."""
    values = []
    for segment in segments:
        values.append(float(segment["_start"]))
        values.append(float(segment["_end"]))
    return sorted(set(values))


def match_boundaries(pred, gt, tol):
    i = j = 0
    tp = 0
    fp = 0
    fn = 0
    while i < len(pred) and j < len(gt):
        d = pred[i] - gt[j]
        if abs(d) <= tol:
            tp += 1
            i += 1
            j += 1
        elif pred[i] < gt[j]:
            fp += 1
            i += 1
        else:
            fn += 1
            j += 1
    fp += len(pred) - i
    fn += len(gt) - j
    return tp, fp, fn


def union_duration(intervals):
    rows = sorted((a, b) for a, b in intervals if b > a)
    if not rows:
        return 0.0
    total = 0.0
    a, b = rows[0]
    for x, y in rows[1:]:
        if x <= b:
            b = max(b, y)
        else:
            total += b - a
            a, b = x, y
    return total + b - a


def intersection_duration(pred, gt):
    p = sorted((s["_start"], s["_end"]) for s in pred if s["_end"] > s["_start"])
    g = sorted((s["_start"], s["_end"]) for s in gt if s["_end"] > s["_start"])
    i = j = 0
    total = 0.0
    while i < len(p) and j < len(g):
        x1, x2 = p[i]
        y1, y2 = g[j]
        left = max(x1, y1)
        right = min(x2, y2)
        if right > left:
            total += right - left
        if x2 <= y2:
            i += 1
        else:
            j += 1
    return total


def iou(a, b):
    inter = max(0.0, min(a["_end"], b["_end"]) - max(a["_start"], b["_start"]))
    union = max(a["_end"], b["_end"]) - min(a["_start"], b["_start"])
    return inter / union if union > 0 else 0.0


def greedy_iou_matches(pred, gt):
    pairs = []
    for pi, p in enumerate(pred):
        for gi, g in enumerate(gt):
            v = iou(p, g)
            if v > 0:
                pairs.append((v, pi, gi))
    pairs.sort(key=lambda x: (-x[0], x[1], x[2]))
    used_p = set()
    used_g = set()
    out = []
    for v, pi, gi in pairs:
        if pi in used_p or gi in used_g:
            continue
        used_p.add(pi)
        used_g.add(gi)
        out.append(v)
    return out


def percentile(values, p):
    if not values:
        return None
    vals = sorted(values)
    x = (len(vals) - 1) * p
    lo = int(x)
    hi = min(lo + 1, len(vals) - 1)
    if lo == hi:
        return vals[lo]
    return vals[lo] + (vals[hi] - vals[lo]) * (x - lo)


def evaluate(pred_by, gt_by):
    sessions = sorted(set(pred_by) | set(gt_by))

    pred_total = sum(len(pred_by.get(s, [])) for s in sessions)
    gt_total = sum(len(gt_by.get(s, [])) for s in sessions)

    result = {
        "pred_segments": pred_total,
        "gt_segments": gt_total,
        "segment_count_ratio": pred_total / gt_total if gt_total else None,
        "segment_count_delta": pred_total - gt_total,
    }

    for tol in TOLS:
        tp = fp = fn = 0
        for sid in sessions:
            p = boundary_list(pred_by.get(sid, []))
            g = boundary_list(gt_by.get(sid, []))
            a, b, c = match_boundaries(p, g, tol)
            tp += a
            fp += b
            fn += c
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        result[f"tp_{tol}s"] = tp
        result[f"fp_{tol}s"] = fp
        result[f"fn_{tol}s"] = fn
        result[f"precision_{tol}s"] = precision
        result[f"recall_{tol}s"] = recall
        result[f"f1_{tol}s"] = f1

    pred_union = 0.0
    gt_union = 0.0
    overlap = 0.0
    pred_durations = []

    gt_split = 0
    gt_with_2plus = 0
    pred_merge = 0
    pred_with_2plus = 0
    all_ious = []

    for sid in sessions:
        ps = pred_by.get(sid, [])
        gs = gt_by.get(sid, [])

        pred_union += union_duration((x["_start"], x["_end"]) for x in ps)
        gt_union += union_duration((x["_start"], x["_end"]) for x in gs)
        overlap += intersection_duration(ps, gs)

        pred_durations.extend(max(0.0, x["_end"] - x["_start"]) for x in ps)

        for g in gs:
            n = sum(
                min(g["_end"], p["_end"]) > max(g["_start"], p["_start"])
                for p in ps
            )
            if n >= 2:
                gt_split += 1
            if n > 0:
                gt_with_2plus += 1

        for p in ps:
            n = sum(
                min(p["_end"], g["_end"]) > max(p["_start"], g["_start"])
                for g in gs
            )
            if n >= 2:
                pred_merge += 1
            if n > 0:
                pred_with_2plus += 1

        all_ious.extend(greedy_iou_matches(ps, gs))

    tp = overlap / pred_union if pred_union else 0.0
    tr = overlap / gt_union if gt_union else 0.0
    tf1 = 2 * tp * tr / (tp + tr) if tp + tr else 0.0

    result.update({
        "temporal_precision": tp,
        "temporal_recall": tr,
        "temporal_f1": tf1,
        "pred_duration_p25": percentile(pred_durations, 0.25),
        "pred_duration_median": percentile(pred_durations, 0.50),
        "pred_duration_p75": percentile(pred_durations, 0.75),
        "gt_segments_split_2plus": gt_split,
        "gt_fragmentation_rate": gt_split / gt_total if gt_total else 0.0,
        "pred_segments_span_2plus_gt": pred_merge,
        "pred_merge_rate": pred_merge / pred_total if pred_total else 0.0,
        "iou_mean": statistics.mean(all_ious) if all_ious else None,
        "iou_median": statistics.median(all_ious) if all_ious else None,
        "iou_ge_0_25": sum(v >= 0.25 for v in all_ious),
        "iou_ge_0_50": sum(v >= 0.50 for v in all_ious),
        "iou_ge_0_75": sum(v >= 0.75 for v in all_ious),
    })
    return result


def _self_test():
    """Comprehensive deterministic metric tests; no project files touched."""
    import math

    # 1. Numeric boundary normalization / uniqueness.
    pred = [
        {"start": "x", "end": "y", "_start": 10.0, "_end": 20.0},
        {"start": "z", "end": "q", "_start": 20.0, "_end": 30.0},
    ]
    gt = [
        {"start": "a", "end": "b", "_start": 10.4, "_end": 20.2},
        {"start": "c", "end": "d", "_start": 20.2, "_end": 30.6},
    ]
    assert boundary_list(pred) == [10.0, 20.0, 30.0]
    assert boundary_list(gt) == [10.4, 20.2, 30.6]

    # 2. Exact boundary matches.
    assert match_boundaries([0.0, 10.0], [0.0, 10.0], 0.5) == (2, 0, 0)

    # 3. Boundary exactly on tolerance is a match.
    assert match_boundaries([0.0], [0.5], 0.5) == (1, 0, 0)

    # 4. Boundary just outside tolerance is not a match.
    assert match_boundaries([0.0], [0.500001], 0.5) == (0, 1, 1)

    # 5. One-to-one rule: three predictions cannot all match one GT boundary.
    assert match_boundaries([0.0, 0.1, 0.2], [0.0], 0.5) == (1, 2, 0)

    # 6. Order/greedy behavior with nearby multiple boundaries.
    assert match_boundaries([0.0, 1.0], [0.4, 1.4], 0.5) == (2, 0, 0)

    # 7. IoU exact overlap.
    exact_a = {"_start": 0.0, "_end": 10.0}
    exact_b = {"_start": 0.0, "_end": 10.0}
    assert math.isclose(iou(exact_a, exact_b), 1.0, rel_tol=0.0, abs_tol=1e-12)

    # 8. IoU partial overlap: [10,20] ∩ [10.4,20.2] = 9.6, union 10.2.
    partial_a = {"_start": 10.0, "_end": 20.0}
    partial_b = {"_start": 10.4, "_end": 20.2}
    assert math.isclose(iou(partial_a, partial_b), 9.6 / 10.2, rel_tol=0.0, abs_tol=1e-12)

    # 9. IoU disjoint.
    dis_a = {"_start": 0.0, "_end": 1.0}
    dis_b = {"_start": 2.0, "_end": 3.0}
    assert iou(dis_a, dis_b) == 0.0

    # 10. IoU containment.
    con_a = {"_start": 0.0, "_end": 10.0}
    con_b = {"_start": 2.0, "_end": 8.0}
    assert math.isclose(iou(con_a, con_b), 0.6, rel_tol=0.0, abs_tol=1e-12)

    # 11. Union duration with overlapping intervals.
    assert math.isclose(
        union_duration([(0.0, 10.0), (5.0, 15.0), (20.0, 25.0)]),
        20.0,
        rel_tol=0.0,
        abs_tol=1e-12,
    )

    # 12. Intersection duration with partial overlap.
    p1 = [{"_start": 0.0, "_end": 10.0}]
    g1 = [{"_start": 5.0, "_end": 15.0}]
    assert math.isclose(intersection_duration(p1, g1), 5.0, rel_tol=0.0, abs_tol=1e-12)

    # 13. Empty union/intersection.
    assert union_duration([]) == 0.0
    assert intersection_duration([], g1) == 0.0

    # 14. Perfect evaluate case: everything exact.
    perfect_pred = {"S": [{"_start": 0.0, "_end": 10.0}]}
    perfect_gt = {"S": [{"_start": 0.0, "_end": 10.0}]}
    perfect = evaluate(perfect_pred, perfect_gt)
    for tol in TOLS:
        assert perfect[f"f1_{tol}s"] == 1.0
    assert perfect["temporal_precision"] == 1.0
    assert perfect["temporal_recall"] == 1.0
    assert perfect["temporal_f1"] == 1.0
    assert perfect["gt_fragmentation_rate"] == 0.0
    assert perfect["pred_merge_rate"] == 0.0
    assert perfect["iou_median"] == 1.0

    # 15. Pure fragmentation: one GT interval split into two predictions.
    split_pred = {"S": [
        {"_start": 0.0, "_end": 5.0},
        {"_start": 5.0, "_end": 10.0},
    ]}
    one_gt = {"S": [{"_start": 0.0, "_end": 10.0}]}
    split = evaluate(split_pred, one_gt)
    assert split["gt_segments_split_2plus"] == 1
    assert split["gt_fragmentation_rate"] == 1.0
    assert split["pred_segments_span_2plus_gt"] == 0
    assert split["temporal_precision"] == 1.0
    assert split["temporal_recall"] == 1.0

    # 16. Pure merging: two GT intervals joined into one prediction.
    one_pred = {"S": [{"_start": 0.0, "_end": 10.0}]}
    split_gt = {"S": [
        {"_start": 0.0, "_end": 5.0},
        {"_start": 5.0, "_end": 10.0},
    ]}
    merge = evaluate(one_pred, split_gt)
    assert merge["gt_segments_split_2plus"] == 0
    assert merge["pred_segments_span_2plus_gt"] == 1
    assert merge["pred_merge_rate"] == 1.0
    assert merge["temporal_precision"] == 1.0
    assert merge["temporal_recall"] == 1.0

    # 17. Partial overlap: temporal precision/recall must be asymmetric.
    partial_eval = evaluate(
        {"S": [{"_start": 0.0, "_end": 5.0}]},
        {"S": [{"_start": 0.0, "_end": 10.0}]},
    )
    assert math.isclose(partial_eval["temporal_precision"], 1.0, abs_tol=1e-12)
    assert math.isclose(partial_eval["temporal_recall"], 0.5, abs_tol=1e-12)
    assert math.isclose(partial_eval["temporal_f1"], 2.0 / 3.0, abs_tol=1e-12)

    # 18. Session mismatch must contribute FP/FN through the union of sessions.
    mismatch = evaluate(
        {"P": [{"_start": 0.0, "_end": 1.0}]},
        {"G": [{"_start": 0.0, "_end": 1.0}]},
    )
    assert mismatch["f1_0.5s"] == 0.0
    assert mismatch["f1_5.0s"] == 0.0

    print("Preflight metric self-test: PASS (18 cases)")

def main():
    _self_test()
    ap = argparse.ArgumentParser()
    ap.add_argument("--activities", required=True, type=Path)
    ap.add_argument("--relationships", required=True, type=Path)
    ap.add_argument("--gt", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    args = ap.parse_args()

    # src is the parent directory of this script.
    src_dir = Path(__file__).resolve().parent
    pg = load_module(src_dir / "process_groups.py", "process_groups_for_sweep")

    # Load inputs once.
    activity_records = pg.load_jsonl(args.activities)
    relationship_records = pg.load_jsonl(args.relationships)
    by_session = pg.validate_activities(activity_records)
    relationship_index = pg.build_relationship_index(relationship_records)

    # Reuse the already-validated evaluator GT loader. Dataset-A GT is
    # organized as {"sessions": [{"session_id": ..., "segments": [...]}]}.
    ev = load_module(src_dir / "evaluation.py", "evaluation_for_sweep")
    gt_sessions = ev.load_ground_truth(args.gt)

    gt_by = defaultdict(list)
    for session_id, session_record in gt_sessions.items():
        for row in session_record["segments"]:
            x = dict(row)
            x["_start"] = parse_ts(x["start"])
            x["_end"] = parse_ts(x["end"])
            gt_by[session_id].append(x)

    gt_segment_count = sum(len(v) for v in gt_by.values())
    if gt_segment_count == 0:
        raise ValueError(
            "Ground truth loaded successfully but contains zero segments. "
            "Refusing to run an invalid sweep."
        )

    # Preflight: every value used in numeric metric calculations must already
    # be normalized to float seconds. This prevents silent string arithmetic
    # bugs from reaching the sweep.
    for session_id, rows in gt_by.items():
        for row in rows:
            if not isinstance(row["_start"], float) or not isinstance(row["_end"], float):
                raise TypeError(
                    f"GT timestamp normalization failed for {session_id}: "
                    f"{row['_start']!r}, {row['_end']!r}"
                )

    print(f"GT segments loaded: {gt_segment_count}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    results = []

    # Save/restore module parameters so the process_groups implementation itself
    # remains untouched.
    original_a = pg.CONTEXT_CONTINUATION_MAX_SECONDS
    original_b = pg.CONTEXT_SCORE_MIN

    configs = [(a, b) for a in A_VALUES for b in B_VALUES]
    configs.append((12.0, 3))
    # Stable unique ordering with current baseline at the end.
    configs = list(dict.fromkeys(configs))

    try:
        for idx, (a_value, b_value) in enumerate(configs, start=1):
            pg.CONTEXT_CONTINUATION_MAX_SECONDS = a_value
            pg.CONTEXT_SCORE_MIN = b_value

            all_segments = []
            logical_executions = 0

            for session_id, activities in sorted(by_session.items()):
                executions, _ = pg.reconstruct_session(
                    session_id,
                    activities,
                    relationship_index,
                )
                logical_executions += len(executions)
                all_segments.extend(
                    pg.build_segment_records(executions, activities)
                )

            pred_by = defaultdict(list)
            for row in all_segments:
                x = dict(row)
                x["_start"] = parse_ts(x["start"])
                x["_end"] = parse_ts(x["end"])
                pred_by[x["session_id"]].append(x)

            metrics = evaluate(pred_by, gt_by)
            row = {
                "config_id": idx,
                "context_max_seconds": a_value,
                "context_score_min": b_value,
                "is_current_baseline": (a_value == 12.0 and b_value == 3),
                "logical_executions": logical_executions,
                **metrics,
            }
            results.append(row)

            print(
                f"[{idx:02d}/{len(configs)}] "
                f"A={a_value:>4.0f}s B={b_value} "
                f"segments={metrics['pred_segments']:>4} "
                f"F1@1={metrics['f1_1.0s']:.4f} "
                f"F1@2={metrics['f1_2.0s']:.4f} "
                f"F1@5={metrics['f1_5.0s']:.4f} "
                f"tempF1={metrics['temporal_f1']:.4f}"
            )

    finally:
        pg.CONTEXT_CONTINUATION_MAX_SECONDS = original_a
        pg.CONTEXT_SCORE_MIN = original_b

    csv_path = args.out_dir / "grouping_sweep.csv"
    fieldnames = list(results[0].keys())
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(results)

    # Technical prioritization, not a claim of universal optimality:
    # 1. Prefer higher boundary F1 at 2s.
    # 2. Prefer higher boundary F1 at 5s.
    # 3. Prefer higher temporal recall.
    # 4. Prefer lower fragmentation and merge rate.
    # 5. Prefer lower absolute segment-count error.
    ranked = sorted(
        results,
        key=lambda r: (
            -r["f1_2.0s"],
            -r["f1_5.0s"],
            -r["temporal_recall"],
            r["gt_fragmentation_rate"],
            r["pred_merge_rate"],
            abs((r["segment_count_ratio"] if r["segment_count_ratio"] is not None else float("inf")) - 1.0),
        ),
    )

    top_path = args.out_dir / "top_configs.json"
    top_path.write_text(
        json.dumps(ranked[:10], indent=2),
        encoding="utf-8",
    )

    baseline = next(
        r for r in results if r["is_current_baseline"]
    )

    print()
    print("GROUPING PARAMETER SWEEP")
    print("=" * 78)
    print(f"Configurations tested: {len(results)}")
    print(f"GT segments loaded:     {sum(len(v) for v in gt_by.values())}")
    print()
    print("CURRENT BASELINE (A=12s, B=3)")
    print("-" * 78)
    for key in (
        "pred_segments",
        "segment_count_ratio",
        "f1_0.5s",
        "f1_1.0s",
        "f1_2.0s",
        "f1_5.0s",
        "temporal_precision",
        "temporal_recall",
        "temporal_f1",
        "gt_fragmentation_rate",
        "pred_merge_rate",
        "iou_median",
    ):
        print(f"{key:28s}: {baseline[key]}")

    print()
    print("TOP 10 CONFIGURATIONS BY 2s BOUNDARY F1")
    print("-" * 78)
    print(
        f"{'A(s)':>6} {'B':>4} {'segments':>9} {'ratio':>8} "
        f"{'F1@1':>8} {'F1@2':>8} {'F1@5':>8} {'tempF1':>9} "
        f"{'frag':>8} {'merge':>8}"
    )
    for r in ranked[:10]:
        print(
            f"{r['context_max_seconds']:>6.0f} "
            f"{r['context_score_min']:>4} "
            f"{r['pred_segments']:>9} "
            f"{r['segment_count_ratio']:>8.3f} "
            f"{r['f1_1.0s']:>8.4f} "
            f"{r['f1_2.0s']:>8.4f} "
            f"{r['f1_5.0s']:>8.4f} "
            f"{r['temporal_f1']:>9.4f} "
            f"{r['gt_fragmentation_rate']:>8.3f} "
            f"{r['pred_merge_rate']:>8.3f}"
        )

    print()
    print("OUTPUTS")
    print("-" * 78)
    print(csv_path)
    print(top_path)


if __name__ == "__main__":
    main()
