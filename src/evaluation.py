"""
Evaluate predicted segments against Dataset A ground truth.

This version evaluates a complete multi-session prediction file.

Expected prediction format (JSONL):
{"session_id": "...", "start": "...", "end": "...", "label": "..."}

Expected GT format:
the JSON produced by ground_truth.py, containing:
{
    "sessions": [
        {
            "session_id": "...",
            "segments": [...]
        },
        ...
    ]
}

The main metric is internal boundary detection:
- GT boundaries = start time of every GT segment except the first
- predicted boundaries = start time of every predicted segment except the first

Matching is one-to-one within the requested tolerance.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any


TOLERANCES = (0.5, 1.0, 2.0, 5.0)


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO-8601 timestamp and require timezone information."""
    if not isinstance(value, str):
        raise ValueError(f"timestamp must be a string, got {type(value).__name__}")

    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    dt = datetime.fromisoformat(text)

    if dt.tzinfo is None:
        raise ValueError(f"timestamp must include a timezone: {value!r}")

    return dt


def load_predictions(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Load JSONL predictions and group them by session_id."""
    by_session: dict[str, list[dict[str, Any]]] = {}

    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON in prediction file at line {line_no}: {exc}"
                ) from exc

            if not isinstance(record, dict):
                raise ValueError(f"Prediction line {line_no} must be a JSON object.")

            for field in ("session_id", "start", "end", "label"):
                if field not in record:
                    raise ValueError(
                        f"Prediction line {line_no} is missing required field {field!r}."
                    )

            session_id = record["session_id"]
            if not isinstance(session_id, str) or not session_id:
                raise ValueError(
                    f"Prediction line {line_no}: session_id must be a non-empty string."
                )

            start = parse_timestamp(record["start"])
            end = parse_timestamp(record["end"])

            if end <= start:
                raise ValueError(f"Prediction line {line_no}: end must be after start.")

            by_session.setdefault(session_id, []).append(record)

    for session_id, segments in by_session.items():
        segments.sort(key=lambda x: parse_timestamp(x["start"]))

        for previous, current in zip(segments, segments[1:]):
            previous_end = parse_timestamp(previous["end"])
            current_start = parse_timestamp(current["start"])

            if current_start < previous_end:
                raise ValueError(
                    f"Predicted segments overlap in session {session_id!r}: "
                    f"{previous['start']}..{previous['end']} overlaps "
                    f"{current['start']}..{current['end']}."
                )

    return by_session


def load_ground_truth(path: Path) -> dict[str, dict[str, Any]]:
    """Load the complete GT reconstruction and index sessions by session_id."""
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("Ground-truth file must contain a JSON object.")

    sessions = data.get("sessions")
    if not isinstance(sessions, list):
        raise ValueError("Ground-truth file does not contain a 'sessions' list.")

    by_session: dict[str, dict[str, Any]] = {}

    for session_record in sessions:
        if not isinstance(session_record, dict):
            raise ValueError("Every GT session entry must be a JSON object.")

        session_id = session_record.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("Every GT session must have a non-empty session_id.")

        if session_id in by_session:
            raise ValueError(f"Duplicate GT session_id: {session_id}")

        gt_segments = session_record.get("segments")
        if not isinstance(gt_segments, list):
            raise ValueError(
                f"GT session {session_id!r} does not contain a 'segments' list."
            )

        cleaned_segments: list[dict[str, Any]] = []

        for index, segment in enumerate(gt_segments, start=1):
            if not isinstance(segment, dict):
                raise ValueError(
                    f"GT segment {index} in session {session_id!r} is not an object."
                )

            for field in ("start", "end"):
                if field not in segment:
                    raise ValueError(
                        f"GT segment {index} in session {session_id!r} "
                        f"is missing {field!r}."
                    )

            start = parse_timestamp(segment["start"])
            end = parse_timestamp(segment["end"])

            if end <= start:
                raise ValueError(
                    f"GT segment {index} in session {session_id!r}: end must be after start."
                )

            cleaned_segments.append(segment)

        cleaned_segments.sort(key=lambda x: parse_timestamp(x["start"]))

        for previous, current in zip(cleaned_segments, cleaned_segments[1:]):
            previous_end = parse_timestamp(previous["end"])
            current_start = parse_timestamp(current["start"])

            if current_start < previous_end:
                raise ValueError(
                    f"GT segments overlap in session {session_id!r}: "
                    f"{previous['start']}..{previous['end']} overlaps "
                    f"{current['start']}..{current['end']}."
                )

        session_copy = dict(session_record)
        session_copy["segments"] = cleaned_segments
        by_session[session_id] = session_copy

    return by_session


def internal_boundaries(segments: list[dict[str, Any]]) -> list[float]:
    """
    Return internal segmentation boundaries as Unix timestamps.

    We use starts of segments after the first segment. This represents each
    process transition exactly once instead of counting both the previous
    segment's end and the next segment's start.
    """
    if len(segments) <= 1:
        return []

    return [parse_timestamp(segment["start"]).timestamp() for segment in segments[1:]]


def match_boundaries(
    predicted: list[float],
    ground_truth: list[float],
    tolerance_seconds: float,
) -> tuple[int, int, int]:
    """Greedily one-to-one match predicted boundaries to GT boundaries."""
    predicted = sorted(predicted)
    ground_truth = sorted(ground_truth)

    used_gt: set[int] = set()
    true_positives = 0

    for predicted_time in predicted:
        best_index = None
        best_distance = math.inf

        for index, gt_time in enumerate(ground_truth):
            if index in used_gt:
                continue

            distance = abs(predicted_time - gt_time)

            if distance <= tolerance_seconds and distance < best_distance:
                best_index = index
                best_distance = distance

            if gt_time > predicted_time + tolerance_seconds:
                break

        if best_index is not None:
            used_gt.add(best_index)
            true_positives += 1

    false_positives = len(predicted) - true_positives
    false_negatives = len(ground_truth) - true_positives

    return true_positives, false_positives, false_negatives


def safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def f1_score(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def metrics_from_counts(
    true_positives: int,
    false_positives: int,
    false_negatives: int,
) -> dict[str, float | int]:
    precision = safe_divide(true_positives, true_positives + false_positives)
    recall = safe_divide(true_positives, true_positives + false_negatives)
    f1 = f1_score(precision, recall)

    return {
        "tp": true_positives,
        "fp": false_positives,
        "fn": false_negatives,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def evaluate_session(
    predicted_segments: list[dict[str, Any]],
    gt_segments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate one session at all configured tolerances."""
    predicted_boundaries = internal_boundaries(predicted_segments)
    gt_boundaries = internal_boundaries(gt_segments)

    result: dict[str, Any] = {
        "predicted_segments": len(predicted_segments),
        "gt_segments": len(gt_segments),
        "predicted_boundaries": len(predicted_boundaries),
        "gt_boundaries": len(gt_boundaries),
        "metrics": {},
    }

    for tolerance in TOLERANCES:
        tp, fp, fn = match_boundaries(
            predicted_boundaries,
            gt_boundaries,
            tolerance,
        )
        result["metrics"][str(tolerance)] = metrics_from_counts(tp, fp, fn)

    return result


def evaluate_all(
    predictions: dict[str, list[dict[str, Any]]],
    ground_truth: dict[str, dict[str, Any]],
    requested_session: str | None = None,
) -> dict[str, Any]:
    """Evaluate all common sessions and micro-average TP/FP/FN."""
    if requested_session is not None:
        if requested_session not in ground_truth:
            raise ValueError(
                f"Requested session {requested_session!r} is not present in GT."
            )
        if requested_session not in predictions:
            raise ValueError(
                f"Requested session {requested_session!r} is not present in predictions."
            )
        session_ids = [requested_session]
    else:
        session_ids = sorted(set(predictions) & set(ground_truth))

    if not session_ids:
        raise ValueError(
            "No common session_ids were found between predictions and ground truth."
        )

    prediction_only = sorted(set(predictions) - set(ground_truth))
    gt_only = sorted(set(ground_truth) - set(predictions))

    per_session: dict[str, Any] = {}
    aggregate_counts = {
        tolerance: {"tp": 0, "fp": 0, "fn": 0} for tolerance in TOLERANCES
    }

    for session_id in session_ids:
        session_result = evaluate_session(
            predictions[session_id],
            ground_truth[session_id]["segments"],
        )
        per_session[session_id] = session_result

        for tolerance in TOLERANCES:
            counts = session_result["metrics"][str(tolerance)]
            aggregate_counts[tolerance]["tp"] += counts["tp"]
            aggregate_counts[tolerance]["fp"] += counts["fp"]
            aggregate_counts[tolerance]["fn"] += counts["fn"]

    aggregate_metrics: dict[str, Any] = {}
    for tolerance in TOLERANCES:
        counts = aggregate_counts[tolerance]
        aggregate_metrics[str(tolerance)] = metrics_from_counts(
            counts["tp"], counts["fp"], counts["fn"]
        )

    return {
        "sessions_evaluated": len(session_ids),
        "prediction_sessions": len(predictions),
        "ground_truth_sessions": len(ground_truth),
        "prediction_only_sessions": prediction_only,
        "ground_truth_only_sessions": gt_only,
        "aggregate_micro": aggregate_metrics,
        "per_session": per_session,
    }


def print_report(results: dict[str, Any]) -> None:
    """Print a compact human-readable evaluation report."""
    print()
    print("DATASET A BASELINE EVALUATION")
    print("=" * 72)
    print(f"Sessions evaluated:          {results['sessions_evaluated']}")
    print(f"Prediction sessions:         {results['prediction_sessions']}")
    print(f"Ground-truth sessions:       {results['ground_truth_sessions']}")

    if results["prediction_only_sessions"]:
        print(
            f"Prediction-only sessions:    {len(results['prediction_only_sessions'])}"
        )

    if results["ground_truth_only_sessions"]:
        print(
            f"GT-only sessions:            {len(results['ground_truth_only_sessions'])}"
        )

    print()
    print("MICRO-AVERAGED INTERNAL BOUNDARY METRICS")
    print("-" * 72)
    print(
        f"{'Tolerance':>12} {'TP':>8} {'FP':>8} {'FN':>8} "
        f"{'Precision':>12} {'Recall':>12} {'F1':>12}"
    )

    for tolerance in TOLERANCES:
        metrics = results["aggregate_micro"][str(tolerance)]
        print(
            f"{tolerance:>9.1f}s "
            f"{metrics['tp']:>8} "
            f"{metrics['fp']:>8} "
            f"{metrics['fn']:>8} "
            f"{metrics['precision']:>12.4f} "
            f"{metrics['recall']:>12.4f} "
            f"{metrics['f1']:>12.4f}"
        )

    print()
    print(
        "Boundary definition: start of each predicted/GT segment after the "
        "first segment in that session."
    )
    print(
        "This prevents one process transition from being counted twice as "
        "both an end and a start."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate predicted segments against Dataset A GT segments."
    )
    parser.add_argument(
        "--predicted",
        required=True,
        help="JSONL file containing predicted segments for one or all sessions.",
    )
    parser.add_argument(
        "--gt",
        required=True,
        help="JSON file produced by ground_truth.py.",
    )
    parser.add_argument(
        "--session",
        help="Optional single session_id to evaluate instead of all sessions.",
    )
    parser.add_argument(
        "--results",
        help="Optional path to save detailed evaluation results as JSON.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    predicted_path = Path(args.predicted)
    gt_path = Path(args.gt)

    if not predicted_path.exists():
        raise FileNotFoundError(f"Prediction file not found: {predicted_path}")
    if not gt_path.exists():
        raise FileNotFoundError(f"Ground-truth file not found: {gt_path}")

    predictions = load_predictions(predicted_path)
    ground_truth = load_ground_truth(gt_path)

    results = evaluate_all(
        predictions,
        ground_truth,
        requested_session=args.session,
    )

    print_report(results)

    if args.results:
        output_path = Path(args.results)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print()
        print(f"Saved detailed results to {output_path}")


if __name__ == "__main__":
    main()
