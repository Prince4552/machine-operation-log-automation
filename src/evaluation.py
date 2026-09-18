from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path
from typing import Any


DEFAULT_TOLERANCES_SECONDS = (0.5, 1.0, 2.0, 5.0)


def _to_seconds(timestamp: str) -> float:
    from datetime import datetime

    value = timestamp.replace("Z", "+00:00")
    return datetime.fromisoformat(value).timestamp()


def boundary_times(segments: list[dict[str, Any]]) -> list[float]:
    boundaries: list[float] = []

    for segment in segments:
        boundaries.append(_to_seconds(segment["start"]))
        boundaries.append(_to_seconds(segment["end"]))

    return sorted(boundaries)


def boundary_metrics_at_tolerance(
    predicted_segments: list[dict[str, Any]],
    ground_truth_segments: list[dict[str, Any]],
    tolerance_seconds: float,
) -> dict[str, float | int]:
    predicted = boundary_times(predicted_segments)
    truth = boundary_times(ground_truth_segments)

    i = 0
    j = 0
    matched = 0

    # One-to-one greedy matching on sorted 1-D timestamps.
    while i < len(predicted) and j < len(truth):
        diff = predicted[i] - truth[j]

        if abs(diff) <= tolerance_seconds:
            matched += 1
            i += 1
            j += 1
        elif predicted[i] < truth[j]:
            i += 1
        else:
            j += 1

    precision = matched / len(predicted) if predicted else 0.0
    recall = matched / len(truth) if truth else 0.0

    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    return {
        "tolerance_seconds": tolerance_seconds,
        "matched": matched,
        "predicted_boundaries": len(predicted),
        "ground_truth_boundaries": len(truth),
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def boundary_metrics(
    predicted_segments: list[dict[str, Any]],
    ground_truth_segments: list[dict[str, Any]],
    tolerances: tuple[float, ...] = DEFAULT_TOLERANCES_SECONDS,
) -> dict[str, Any]:
    return {
        str(tolerance): boundary_metrics_at_tolerance(
            predicted_segments,
            ground_truth_segments,
            tolerance,
        )
        for tolerance in tolerances
    }


def pairwise_same_process_f1(
    predicted_assignments: dict[str, str],
    ground_truth_assignments: dict[str, str],
) -> dict[str, float | int]:
    """Partition-based pairwise F1 without enumerating all O(n^2) pairs."""
    common_ids = sorted(
        set(predicted_assignments) & set(ground_truth_assignments)
    )

    predicted_groups: dict[str, int] = {}
    truth_groups: dict[str, int] = {}
    intersections: dict[tuple[str, str], int] = {}

    for activity_id in common_ids:
        predicted_label = predicted_assignments[activity_id]
        truth_label = ground_truth_assignments[activity_id]

        predicted_groups[predicted_label] = (
            predicted_groups.get(predicted_label, 0) + 1
        )
        truth_groups[truth_label] = truth_groups.get(truth_label, 0) + 1

        key = (predicted_label, truth_label)
        intersections[key] = intersections.get(key, 0) + 1

    def choose2(n: int) -> int:
        return n * (n - 1) // 2

    predicted_positive = sum(choose2(n) for n in predicted_groups.values())
    truth_positive = sum(choose2(n) for n in truth_groups.values())

    true_positive = sum(
        choose2(count) for count in intersections.values()
    )

    false_positive = predicted_positive - true_positive
    false_negative = truth_positive - true_positive

    precision = (
        true_positive / predicted_positive
        if predicted_positive
        else 0.0
    )
    recall = (
        true_positive / truth_positive
        if truth_positive
        else 0.0
    )

    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    return {
        "activities_compared": len(common_ids),
        "true_positive_pairs": true_positive,
        "false_positive_pairs": false_positive,
        "false_negative_pairs": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def evaluate(
    predicted_segments: list[dict[str, Any]],
    ground_truth_segments: list[dict[str, Any]],
) -> dict[str, Any]:
    """T0 evaluator.

    Boundary metrics are directly runnable from the beginning.
    Pairwise same-process F1 is exposed as a reusable function and will be
    populated once the activity layer exists.
    """
    return {
        "boundary": boundary_metrics(
            predicted_segments,
            ground_truth_segments,
        ),
    }


def load_segments(path: Path) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                segments.append(json.loads(line))

    return segments


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate predicted segments against Dataset A GT segments."
    )
    parser.add_argument(
        "--predicted",
        type=Path,
        required=True,
        help="JSONL file containing predicted segments for one session.",
    )
    parser.add_argument(
        "--gt",
        type=Path,
        required=True,
        help="JSON file produced by ground_truth.py for the same session.",
    )
    args = parser.parse_args()

    predicted = load_segments(args.predicted)

    with args.gt.open("r", encoding="utf-8") as f:
        gt_payload = json.load(f)

    truth = gt_payload["segments"]

    result = evaluate(predicted, truth)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
