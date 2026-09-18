"""
Evaluate predicted process segments against Dataset A ground truth.

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

T0 boundary metric:
    GT boundaries = unique union of every segment start and end timestamp.
    Predicted boundaries = unique union of every segment start and end timestamp.

Boundaries are matched one-to-one within each tolerance. The matcher uses a
1-D greedy strategy that maximizes the number of valid matches for equal-width
(timestamp) tolerance windows. Sessions missing on either side are still
evaluated so that omitted predictions become false negatives and extra
prediction-only sessions become false positives.

Pairwise same-process F1 is intentionally not implemented here yet because it
requires the activity-to-execution assignment produced by the relationship /
work-unit layer. It should be added once that intermediate representation
exists, rather than inventing an artificial mapping at this stage.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TOLERANCES = (0.5, 1.0, 2.0, 5.0)


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO-8601 timestamp and normalize it to UTC."""
    if not isinstance(value, str):
        raise ValueError(f"timestamp must be a string, got {type(value).__name__}")

    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError(f"timestamp must include a timezone: {value!r}")

    return dt.astimezone(timezone.utc)


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

            label = record["label"]
            if not isinstance(label, str) or not label.strip():
                raise ValueError(
                    f"Prediction line {line_no}: label must be a non-empty string."
                )

            start = parse_timestamp(record["start"])
            end = parse_timestamp(record["end"])
            if end <= start:
                raise ValueError(f"Prediction line {line_no}: end must be after start.")

            by_session.setdefault(session_id, []).append(record)

    validate_non_overlapping_segments(by_session, source_name="predictions")
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
        session_copy = dict(session_record)
        session_copy["segments"] = cleaned_segments
        by_session[session_id] = session_copy

    validate_non_overlapping_segments(
        {sid: record["segments"] for sid, record in by_session.items()},
        source_name="ground truth",
    )
    return by_session


def validate_non_overlapping_segments(
    by_session: dict[str, list[dict[str, Any]]],
    source_name: str,
) -> None:
    """Validate ordering and non-overlap for each session."""
    for session_id, segments in by_session.items():
        segments.sort(key=lambda x: parse_timestamp(x["start"]))

        for previous, current in zip(segments, segments[1:]):
            previous_end = parse_timestamp(previous["end"])
            current_start = parse_timestamp(current["start"])
            if current_start < previous_end:
                raise ValueError(
                    f"{source_name} segments overlap in session {session_id!r}: "
                    f"{previous['start']}..{previous['end']} overlaps "
                    f"{current['start']}..{current['end']}."
                )


def boundary_times(segments: list[dict[str, Any]]) -> list[datetime]:
    """Return the unique union of all segment starts and ends, sorted in time."""
    boundaries: set[datetime] = set()

    for segment in segments:
        boundaries.add(parse_timestamp(segment["start"]))
        boundaries.add(parse_timestamp(segment["end"]))

    return sorted(boundaries)


def match_boundaries(
    predicted: list[datetime],
    ground_truth: list[datetime],
    tolerance_seconds: float,
) -> tuple[int, int, int]:
    """
    Match boundaries one-to-one with maximum-cardinality greedy matching.

    Because every boundary has the same symmetric tolerance window, scanning
    both sorted lists and taking the earliest feasible pair maximizes the
    number of matches. This avoids a nearest-neighbour greedy failure mode
    where an early prediction can consume a GT boundary needed by a later one.
    """
    predicted = sorted(predicted)
    ground_truth = sorted(ground_truth)

    tolerance = tolerance_seconds
    pred_index = 0
    gt_index = 0
    true_positives = 0

    while pred_index < len(predicted) and gt_index < len(ground_truth):
        difference = (predicted[pred_index] - ground_truth[gt_index]).total_seconds()

        if difference < -tolerance:
            # GT is too late for the current prediction; discard this prediction.
            pred_index += 1
        elif difference > tolerance:
            # GT is too early for the current prediction; no future prediction
            # can match it better without violating sorted order.
            gt_index += 1
        else:
            # Earliest feasible pair. Consume both exactly once.
            true_positives += 1
            pred_index += 1
            gt_index += 1

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
    predicted_boundaries = boundary_times(predicted_segments)
    gt_boundaries = boundary_times(gt_segments)

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
    """
    Evaluate every session in the union of prediction and GT session IDs.

    Missing predictions therefore contribute FN, while prediction-only sessions
    contribute FP, instead of disappearing from the aggregate score.
    """
    if requested_session is not None:
        if requested_session not in predictions and requested_session not in ground_truth:
            raise ValueError(
                f"Requested session {requested_session!r} is not present in predictions or GT."
            )
        session_ids = [requested_session]
    else:
        session_ids = sorted(set(predictions) | set(ground_truth))

    if not session_ids:
        raise ValueError("No sessions were found in predictions or ground truth.")

    prediction_only = sorted(set(predictions) - set(ground_truth))
    gt_only = sorted(set(ground_truth) - set(predictions))

    per_session: dict[str, Any] = {}
    aggregate_counts = {
        tolerance: {"tp": 0, "fp": 0, "fn": 0} for tolerance in TOLERANCES
    }

    for session_id in session_ids:
        predicted_segments = predictions.get(session_id, [])
        gt_segments = ground_truth.get(session_id, {}).get("segments", [])

        session_result = evaluate_session(predicted_segments, gt_segments)
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
        "evaluation_definition": {
            "boundary_set": "unique union of all segment starts and ends",
            "matching": "one-to-one maximum-cardinality greedy matching",
            "tolerances_seconds": list(TOLERANCES),
            "missing_sessions_counted": True,
        },
    }


def print_report(results: dict[str, Any]) -> None:
    """Print a compact human-readable evaluation report."""
    print()
    print("DATASET A BASELINE EVALUATION")
    print("=" * 78)
    print(f"Sessions evaluated:          {results['sessions_evaluated']}")
    print(f"Prediction sessions:         {results['prediction_sessions']}")
    print(f"Ground-truth sessions:       {results['ground_truth_sessions']}")
    print(
        f"Prediction-only sessions:    {len(results['prediction_only_sessions'])}"
    )
    print(f"GT-only sessions:             {len(results['ground_truth_only_sessions'])}")

    definition = results["evaluation_definition"]
    print()
    print("EVALUATION DEFINITION")
    print("-" * 78)
    print(f"Boundaries:                   {definition['boundary_set']}")
    print(f"Matching:                     {definition['matching']}")
    print(
        f"Missing sessions counted:     {definition['missing_sessions_counted']}"
    )

    print()
    print("MICRO-AVERAGED BOUNDARY METRICS")
    print("-" * 78)
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
    print("INTEGRITY CHECK")
    if results["prediction_only_sessions"] or results["ground_truth_only_sessions"]:
        print("STATUS: REVIEW — prediction/GT session coverage differs.")
    else:
        print("STATUS: PASS — prediction and GT contain the same session IDs.")


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
