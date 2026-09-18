
#!/usr/bin/env python3
"""
Dataset A segmentation error analysis.

Purpose:
  Diagnose over-segmentation and under-segmentation before changing rules.

Inputs:
  --predicted : JSONL predicted candidate segments
  --gt        : JSONL or JSON ground-truth segments

Outputs:
  --out-dir:
    summary.json
    session_summary.csv
    boundary_errors.csv
    segment_matches.csv

The loader is deliberately tolerant of common GT/output wrappers:
  - JSONL: one segment object per line
  - JSON: list of segment objects
  - JSON: {"segments": [...]}
  - JSONL/JSON records containing a nested "segments" list

Expected segment fields:
  session_id, start, end
  optional: label, execution_id, activity_count

This is diagnostic code. It does not modify any input.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable


TOLS = (0.5, 1.0, 2.0, 5.0)


@dataclass(frozen=True)
class Segment:
    session_id: str
    start: float
    end: float
    label: str = ""
    execution_id: str = ""
    activity_count: int | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def _as_float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # Handles common ISO timestamp variants and numeric strings.
        s = value.strip()
        try:
            return float(s)
        except ValueError:
            pass
        try:
            from datetime import datetime, timezone
            z = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(z)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError as exc:
            raise ValueError(f"Cannot parse timestamp: {value!r}") from exc
    raise ValueError(f"Unsupported timestamp value: {value!r}")


def _read_json_or_jsonl(path: Path) -> list[Any]:
    text = path.read_text(encoding="utf-8")
    stripped = text.lstrip()
    if not stripped:
        return []

    if path.suffix.lower() == ".json" or stripped[0] in "[{":
        try:
            return [json.loads(text)]
        except json.JSONDecodeError:
            pass

    rows = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: invalid JSON on line {line_no}: {exc}") from exc
    return rows


def _looks_like_segment(obj: Any) -> bool:
    return (
        isinstance(obj, dict)
        and "session_id" in obj
        and "start" in obj
        and "end" in obj
    )


def _collect_segment_objects(obj: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        if _looks_like_segment(obj):
            found.append(obj)
            return found

        for key in ("segments", "predictions", "ground_truth", "data", "records"):
            value = obj.get(key)
            if isinstance(value, list):
                for item in value:
                    found.extend(_collect_segment_objects(item))
                if found:
                    return found

        # Last resort: recursively inspect values.
        for value in obj.values():
            if isinstance(value, (dict, list)):
                found.extend(_collect_segment_objects(value))

    elif isinstance(obj, list):
        for item in obj:
            found.extend(_collect_segment_objects(item))

    return found


def load_segments(path_str: str) -> list[Segment]:
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(path)

    raw_rows = _read_json_or_jsonl(path)
    raw_segments: list[dict[str, Any]] = []
    for row in raw_rows:
        raw_segments.extend(_collect_segment_objects(row))

    segments: list[Segment] = []
    for obj in raw_segments:
        try:
            start = _as_float(obj["start"])
            end = _as_float(obj["end"])
            session_id = str(obj["session_id"])
            activity_count = obj.get("activity_count")
            if activity_count is not None:
                activity_count = int(activity_count)

            segments.append(
                Segment(
                    session_id=session_id,
                    start=start,
                    end=end,
                    label=str(obj.get("label", "")),
                    execution_id=str(obj.get("execution_id", "")),
                    activity_count=activity_count,
                )
            )
        except Exception as exc:
            raise ValueError(f"{path}: bad segment object: {obj!r}; {exc}") from exc

    # Stable deterministic ordering.
    segments.sort(key=lambda s: (s.session_id, s.start, s.end, s.execution_id))
    return segments


def percentiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"p10": None, "p25": None, "median": None, "p75": None, "p90": None}
    vals = sorted(values)

    def q(p: float) -> float:
        if len(vals) == 1:
            return vals[0]
        x = (len(vals) - 1) * p
        lo = math.floor(x)
        hi = math.ceil(x)
        if lo == hi:
            return vals[lo]
        return vals[lo] + (vals[hi] - vals[lo]) * (x - lo)

    return {
        "p10": q(0.10),
        "p25": q(0.25),
        "median": q(0.50),
        "p75": q(0.75),
        "p90": q(0.90),
    }


def boundary_list(segments: Iterable[Segment]) -> list[float]:
    return sorted({x for s in segments for x in (s.start, s.end)})


def match_boundaries(pred: list[float], gt: list[float], tol: float):
    """
    Maximum-cardinality one-dimensional matching within tolerance.
    Greedy scan is optimal for sorted points under |p-g| <= tol.
    Returns:
      matches: (pred_value, gt_value, absolute_error)
      unmatched_pred
      unmatched_gt
    """
    i = j = 0
    matches = []
    unmatched_pred = []
    unmatched_gt = []

    while i < len(pred) and j < len(gt):
        d = pred[i] - gt[j]
        if abs(d) <= tol:
            matches.append((pred[i], gt[j], abs(d)))
            i += 1
            j += 1
        elif pred[i] < gt[j]:
            unmatched_pred.append(pred[i])
            i += 1
        else:
            unmatched_gt.append(gt[j])
            j += 1

    unmatched_pred.extend(pred[i:])
    unmatched_gt.extend(gt[j:])
    return matches, unmatched_pred, unmatched_gt


def intervals_duration(intervals: Iterable[tuple[float, float]]) -> float:
    ordered = sorted((a, b) for a, b in intervals if b > a)
    if not ordered:
        return 0.0
    total = 0.0
    cur_a, cur_b = ordered[0]
    for a, b in ordered[1:]:
        if a <= cur_b:
            cur_b = max(cur_b, b)
        else:
            total += cur_b - cur_a
            cur_a, cur_b = a, b
    return total + (cur_b - cur_a)


def intersection_duration(pred: list[Segment], gt: list[Segment]) -> float:
    total = 0.0
    i = j = 0
    p = sorted((s.start, s.end) for s in pred if s.end > s.start)
    g = sorted((s.start, s.end) for s in gt if s.end > s.start)

    while i < len(p) and j < len(g):
        a1, a2 = p[i]
        b1, b2 = g[j]
        left = max(a1, b1)
        right = min(a2, b2)
        if right > left:
            total += right - left
        if a2 <= b2:
            i += 1
        else:
            j += 1
    return total


def interval_iou(a: Segment, b: Segment) -> float:
    inter = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    union = max(a.end, b.end) - min(a.start, b.start)
    return inter / union if union > 0 else 0.0


def greedy_iou_matches(pred: list[Segment], gt: list[Segment]):
    pairs = []
    for pi, p in enumerate(pred):
        for gi, g in enumerate(gt):
            iou = interval_iou(p, g)
            if iou > 0:
                pairs.append((iou, pi, gi))
    pairs.sort(key=lambda x: (-x[0], x[1], x[2]))

    used_p = set()
    used_g = set()
    chosen = []
    for iou, pi, gi in pairs:
        if pi in used_p or gi in used_g:
            continue
        used_p.add(pi)
        used_g.add(gi)
        chosen.append((iou, pi, gi))
    chosen.sort(key=lambda x: (x[1], x[2]))
    return chosen


def session_metrics(pred: list[Segment], gt: list[Segment]) -> dict[str, Any]:
    pred_dur = intervals_duration((s.start, s.end) for s in pred)
    gt_dur = intervals_duration((s.start, s.end) for s in gt)
    inter = intersection_duration(pred, gt)

    temporal_precision = inter / pred_dur if pred_dur else 0.0
    temporal_recall = inter / gt_dur if gt_dur else 0.0
    temporal_f1 = (
        2 * temporal_precision * temporal_recall / (temporal_precision + temporal_recall)
        if temporal_precision + temporal_recall
        else 0.0
    )

    iou_matches = greedy_iou_matches(pred, gt)
    ious = [x[0] for x in iou_matches]

    return {
        "pred_segments": len(pred),
        "gt_segments": len(gt),
        "segment_count_delta": len(pred) - len(gt),
        "segment_count_ratio": (len(pred) / len(gt)) if gt else None,
        "pred_duration_s": pred_dur,
        "gt_duration_s": gt_dur,
        "overlap_duration_s": inter,
        "temporal_precision": temporal_precision,
        "temporal_recall": temporal_recall,
        "temporal_f1": temporal_f1,
        "iou_pairs": len(iou_matches),
        "iou_mean": statistics.mean(ious) if ious else None,
        "iou_median": statistics.median(ious) if ious else None,
        "iou_ge_0_25": sum(x >= 0.25 for x in ious),
        "iou_ge_0_50": sum(x >= 0.50 for x in ious),
        "iou_ge_0_75": sum(x >= 0.75 for x in ious),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--predicted", required=True)
    ap.add_argument("--gt", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pred = load_segments(args.predicted)
    gt = load_segments(args.gt)

    pred_by = defaultdict(list)
    gt_by = defaultdict(list)
    for s in pred:
        pred_by[s.session_id].append(s)
    for s in gt:
        gt_by[s.session_id].append(s)

    sessions = sorted(set(pred_by) | set(gt_by))

    # ---------- global structure ----------
    pred_durations = [s.duration for s in pred]
    gt_durations = [s.duration for s in gt]
    zero_pred = sum(s.duration <= 0 for s in pred)
    zero_gt = sum(s.duration <= 0 for s in gt)

    summary: dict[str, Any] = {
        "inputs": {
            "predicted": str(Path(args.predicted)),
            "ground_truth": str(Path(args.gt)),
        },
        "counts": {
            "sessions": len(sessions),
            "prediction_sessions": len(pred_by),
            "gt_sessions": len(gt_by),
            "prediction_only_sessions": len(set(pred_by) - set(gt_by)),
            "gt_only_sessions": len(set(gt_by) - set(pred_by)),
            "pred_segments": len(pred),
            "gt_segments": len(gt),
            "segment_count_delta": len(pred) - len(gt),
            "segment_count_ratio": len(pred) / len(gt) if gt else None,
        },
        "duration_distributions": {
            "predicted": {
                **percentiles(pred_durations),
                "mean": statistics.mean(pred_durations) if pred_durations else None,
                "min": min(pred_durations) if pred_durations else None,
                "max": max(pred_durations) if pred_durations else None,
                "zero_or_negative": zero_pred,
            },
            "ground_truth": {
                **percentiles(gt_durations),
                "mean": statistics.mean(gt_durations) if gt_durations else None,
                "min": min(gt_durations) if gt_durations else None,
                "max": max(gt_durations) if gt_durations else None,
                "zero_or_negative": zero_gt,
            },
        },
        "boundary_metrics": {},
    }

    boundary_error_rows = []
    for tol in TOLS:
        tp = fp = fn = 0
        errors = []
        for sid in sessions:
            pb = boundary_list(pred_by.get(sid, []))
            gb = boundary_list(gt_by.get(sid, []))
            matches, up, ug = match_boundaries(pb, gb, tol)
            tp += len(matches)
            fp += len(up)
            fn += len(ug)

            for p, g, e in matches:
                boundary_error_rows.append(
                    {
                        "session_id": sid,
                        "tolerance_s": tol,
                        "kind": "matched",
                        "pred_boundary": p,
                        "gt_boundary": g,
                        "abs_error_s": e,
                    }
                )
                errors.append(e)

            for p in up:
                # nearest GT boundary for diagnosis (even if outside tolerance)
                nearest = min((abs(p - g) for g in gb), default=None)
                boundary_error_rows.append(
                    {
                        "session_id": sid,
                        "tolerance_s": tol,
                        "kind": "unmatched_prediction",
                        "pred_boundary": p,
                        "gt_boundary": "",
                        "abs_error_s": nearest if nearest is not None else "",
                    }
                )

            for g in ug:
                nearest = min((abs(g - p) for p in pb), default=None)
                boundary_error_rows.append(
                    {
                        "session_id": sid,
                        "tolerance_s": tol,
                        "kind": "unmatched_ground_truth",
                        "pred_boundary": "",
                        "gt_boundary": g,
                        "abs_error_s": nearest if nearest is not None else "",
                    }
                )

        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

        summary["boundary_metrics"][str(tol)] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "matched_error_distribution_s": percentiles(errors),
            "matched_error_mean_s": statistics.mean(errors) if errors else None,
            "matched_error_max_s": max(errors) if errors else None,
        }

    # ---------- per-session diagnostics ----------
    session_rows = []
    top_fragmented = []
    top_merged = []

    for sid in sessions:
        ps = sorted(pred_by.get(sid, []), key=lambda s: (s.start, s.end))
        gs = sorted(gt_by.get(sid, []), key=lambda s: (s.start, s.end))
        row = {"session_id": sid, **session_metrics(ps, gs)}

        # Boundary counts at 1s and 5s for prioritization.
        for tol in (1.0, 5.0):
            pb = boundary_list(ps)
            gb = boundary_list(gs)
            matches, up, ug = match_boundaries(pb, gb, tol)
            row[f"boundary_tp_{tol}s"] = len(matches)
            row[f"boundary_fp_{tol}s"] = len(up)
            row[f"boundary_fn_{tol}s"] = len(ug)

        # Fragmentation: how many predicted segments overlap each GT segment.
        gt_overlap_counts = []
        for g in gs:
            n = sum(max(0.0, min(g.end, p.end) - max(g.start, p.start)) > 0 for p in ps)
            gt_overlap_counts.append(n)
        row["gt_segments_with_prediction_overlap"] = sum(n > 0 for n in gt_overlap_counts)
        row["gt_segments_split_across_2plus_pred"] = sum(n >= 2 for n in gt_overlap_counts)
        row["gt_fragmentation_rate"] = (
            row["gt_segments_split_across_2plus_pred"] / len(gs) if gs else 0.0
        )
        row["max_predictions_overlapping_one_gt"] = max(gt_overlap_counts, default=0)

        # Merging: how many GT segments overlap each predicted segment.
        pred_overlap_counts = []
        for p in ps:
            n = sum(max(0.0, min(g.end, p.end) - max(g.start, p.start)) > 0 for g in gs)
            pred_overlap_counts.append(n)
        row["pred_segments_overlapping_gt"] = sum(n > 0 for n in pred_overlap_counts)
        row["pred_segments_spanning_2plus_gt"] = sum(n >= 2 for n in pred_overlap_counts)
        row["pred_merge_rate"] = (
            row["pred_segments_spanning_2plus_gt"] / len(ps) if ps else 0.0
        )
        row["max_gt_overlapping_one_prediction"] = max(pred_overlap_counts, default=0)

        session_rows.append(row)

        top_fragmented.append(
            (
                row["gt_segments_split_across_2plus_pred"],
                row["segment_count_delta"],
                sid,
            )
        )
        top_merged.append(
            (
                row["pred_segments_spanning_2plus_gt"],
                row["segment_count_delta"],
                sid,
            )
        )

    session_rows.sort(key=lambda r: (r["segment_count_delta"], r["session_id"]), reverse=True)

    # Global temporal overlap.
    all_pred_duration = 0.0
    all_gt_duration = 0.0
    all_intersection = 0.0
    for sid in sessions:
        ps = pred_by.get(sid, [])
        gs = gt_by.get(sid, [])
        all_pred_duration += intervals_duration((s.start, s.end) for s in ps)
        all_gt_duration += intervals_duration((s.start, s.end) for s in gs)
        all_intersection += intersection_duration(ps, gs)

    temporal_precision = all_intersection / all_pred_duration if all_pred_duration else 0.0
    temporal_recall = all_intersection / all_gt_duration if all_gt_duration else 0.0
    temporal_f1 = (
        2 * temporal_precision * temporal_recall / (temporal_precision + temporal_recall)
        if temporal_precision + temporal_recall
        else 0.0
    )

    # Global IoU diagnostic.
    all_iou = []
    matched_iou_count = 0
    for sid in sessions:
        pairs = greedy_iou_matches(pred_by.get(sid, []), gt_by.get(sid, []))
        all_iou.extend(x[0] for x in pairs)
        matched_iou_count += len(pairs)

    summary["temporal_overlap"] = {
        "predicted_union_duration_s": all_pred_duration,
        "gt_union_duration_s": all_gt_duration,
        "overlap_duration_s": all_intersection,
        "precision": temporal_precision,
        "recall": temporal_recall,
        "f1": temporal_f1,
    }

    summary["segment_iou_diagnostic"] = {
        "one_to_one_greedy_matches": matched_iou_count,
        "mean_iou": statistics.mean(all_iou) if all_iou else None,
        "median_iou": statistics.median(all_iou) if all_iou else None,
        "p25_p75": {
            "p25": percentiles(all_iou)["p25"],
            "p75": percentiles(all_iou)["p75"],
        },
        "matches_iou_ge_0_25": sum(x >= 0.25 for x in all_iou),
        "matches_iou_ge_0_50": sum(x >= 0.50 for x in all_iou),
        "matches_iou_ge_0_75": sum(x >= 0.75 for x in all_iou),
    }

    # Candidate labels, if available.
    pred_labels = Counter(s.label for s in pred if s.label)
    gt_labels = Counter(s.label for s in gt if s.label)
    summary["labels"] = {
        "predicted_nonempty_label_counts": dict(pred_labels),
        "ground_truth_nonempty_label_counts": dict(gt_labels),
        "predicted_empty_labels": sum(not s.label for s in pred),
        "ground_truth_empty_labels": sum(not s.label for s in gt),
    }

    # Strong prioritization lists.
    summary["top_sessions"] = {
        "most_over_segmented": [
            r["session_id"]
            for r in session_rows[:10]
        ],
        "most_fragmented_ground_truth": [
            sid for _, _, sid in sorted(top_fragmented, reverse=True)[:10]
        ],
        "most_merged_predictions": [
            sid for _, _, sid in sorted(top_merged, reverse=True)[:10]
        ],
        "best_count_ratio_match": [
            r["session_id"]
            for r in sorted(
                session_rows,
                key=lambda r: abs((r["segment_count_ratio"] or 0.0) - 1.0)
            )[:10]
        ],
    }

    # ---------- unmatched-boundary nearest-distance summaries ----------
    nearest_pred_to_gt = []
    nearest_gt_to_pred = []
    for sid in sessions:
        pb = boundary_list(pred_by.get(sid, []))
        gb = boundary_list(gt_by.get(sid, []))
        for p in pb:
            if gb:
                nearest_pred_to_gt.append(min(abs(p - g) for g in gb))
        for g in gb:
            if pb:
                nearest_gt_to_pred.append(min(abs(g - p) for p in pb))

    summary["nearest_boundary_distance_distributions"] = {
        "pred_to_nearest_gt_s": percentiles(nearest_pred_to_gt),
        "gt_to_nearest_pred_s": percentiles(nearest_gt_to_pred),
    }

    summary["self_checks"] = {
        "pred_segments_loaded": len(pred),
        "gt_segments_loaded": len(gt),
        "all_pred_session_ids_present": all(s.session_id in pred_by for s in pred),
        "all_gt_session_ids_present": all(s.session_id in gt_by for s in gt),
    }

    # ---------- write ----------
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    fieldnames = sorted({k for row in session_rows for k in row})
    with (out_dir / "session_summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(session_rows)

    with (out_dir / "boundary_errors.csv").open("w", newline="", encoding="utf-8") as f:
        fields = ["session_id", "tolerance_s", "kind", "pred_boundary", "gt_boundary", "abs_error_s"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(boundary_error_rows)

    # Segment-pair diagnostics, kept compact enough for inspection.
    with (out_dir / "segment_matches.csv").open("w", newline="", encoding="utf-8") as f:
        fields = [
            "session_id",
            "pred_index",
            "gt_index",
            "pred_start",
            "pred_end",
            "gt_start",
            "gt_end",
            "iou",
            "pred_duration_s",
            "gt_duration_s",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for sid in sessions:
            ps = pred_by.get(sid, [])
            gs = gt_by.get(sid, [])
            for iou, pi, gi in greedy_iou_matches(ps, gs):
                p = ps[pi]
                g = gs[gi]
                w.writerow(
                    {
                        "session_id": sid,
                        "pred_index": pi,
                        "gt_index": gi,
                        "pred_start": p.start,
                        "pred_end": p.end,
                        "gt_start": g.start,
                        "gt_end": g.end,
                        "iou": iou,
                        "pred_duration_s": p.duration,
                        "gt_duration_s": g.duration,
                    }
                )

    # Human-readable console summary.
    print("DATASET A ERROR ANALYSIS")
    print("=" * 78)
    print(f"Sessions:                  {len(sessions)}")
    print(f"Predicted segments:        {len(pred)}")
    print(f"Ground-truth segments:     {len(gt)}")
    print(f"Count delta:               {len(pred) - len(gt)}")
    print(f"Count ratio:               {len(pred) / len(gt):.4f}" if gt else "Count ratio:               n/a")
    print()
    print("BOUNDARY METRICS")
    print("-" * 78)
    print(f"{'Tol':>8} {'TP':>8} {'FP':>8} {'FN':>8} {'Prec':>10} {'Recall':>10} {'F1':>10}")
    for tol in TOLS:
        m = summary["boundary_metrics"][str(tol)]
        print(
            f"{tol:>7.1f}s {m['tp']:>8} {m['fp']:>8} {m['fn']:>8} "
            f"{m['precision']:>10.4f} {m['recall']:>10.4f} {m['f1']:>10.4f}"
        )

    print()
    print("TEMPORAL COVERAGE")
    print("-" * 78)
    print(f"Intersection duration (s): {all_intersection:.3f}")
    print(f"Temporal precision:         {temporal_precision:.4f}")
    print(f"Temporal recall:            {temporal_recall:.4f}")
    print(f"Temporal F1:                {temporal_f1:.4f}")

    print()
    print("SEGMENT IoU DIAGNOSTIC")
    print("-" * 78)
    iou_summary = summary["segment_iou_diagnostic"]
    print(f"Greedy one-to-one pairs:    {iou_summary['one_to_one_greedy_matches']}")
    print(f"Mean IoU:                   {iou_summary['mean_iou']}")
    print(f"Median IoU:                 {iou_summary['median_iou']}")
    print(f"IoU >= 0.25:                {iou_summary['matches_iou_ge_0_25']}")
    print(f"IoU >= 0.50:                {iou_summary['matches_iou_ge_0_50']}")
    print(f"IoU >= 0.75:                {iou_summary['matches_iou_ge_0_75']}")

    print()
    print("FRAGMENTATION / MERGING")
    print("-" * 78)
    print(
        "GT segments split across 2+ predictions: "
        f"{sum(r['gt_segments_split_across_2plus_pred'] for r in session_rows)}"
    )
    print(
        "Predictions spanning 2+ GT segments:     "
        f"{sum(r['pred_segments_spanning_2plus_gt'] for r in session_rows)}"
    )

    print()
    print("TOP OVER-SEGMENTED SESSIONS")
    print("-" * 78)
    for row in session_rows[:10]:
        print(
            f"{row['session_id']}: pred={row['pred_segments']} "
            f"gt={row['gt_segments']} delta={row['segment_count_delta']} "
            f"fragment_rate={row['gt_fragmentation_rate']:.3f}"
        )

    print()
    print("OUTPUTS")
    print("-" * 78)
    print(out_dir / "summary.json")
    print(out_dir / "session_summary.csv")
    print(out_dir / "boundary_errors.csv")
    print(out_dir / "segment_matches.csv")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
