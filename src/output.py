from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REQUIRED_FIELDS = {"session_id", "start", "end", "label"}


def parse_utc(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp is not a string")

    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)

    if dt.tzinfo is None:
        raise ValueError("timestamp has no timezone")

    return dt.astimezone(timezone.utc)


def write_segments(
    segments: Iterable[dict[str, Any]],
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="\n") as f:
        for segment in segments:
            if set(segment.keys()) != REQUIRED_FIELDS:
                raise ValueError(
                    f"Segment must have exactly {sorted(REQUIRED_FIELDS)}: "
                    f"{segment}"
                )
            f.write(json.dumps(segment, ensure_ascii=False) + "\n")


def load_segments(path: Path) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(
                    f"{path} line {line_number} is not a JSON object."
                )

            segments.append(value)

    return segments


def validate_segments(
    path: Path,
    dataset_dir: Path,
    *,
    strict: bool = True,
) -> dict[str, Any]:
    segments = load_segments(path)

    actual_sessions = {
        p.name
        for p in dataset_dir.iterdir()
        if p.is_dir() and p.name.startswith("ses_")
    }

    errors: list[str] = []
    sessions_seen: set[str] = set()

    by_session: dict[str, list[dict[str, Any]]] = {}

    for index, segment in enumerate(segments, start=1):
        if set(segment.keys()) != REQUIRED_FIELDS:
            errors.append(
                f"Line {index}: expected exactly "
                f"{sorted(REQUIRED_FIELDS)}, got {sorted(segment.keys())}"
            )
            continue

        session_id = segment["session_id"]
        label = segment["label"]

        if session_id not in actual_sessions:
            errors.append(
                f"Line {index}: unknown session_id {session_id!r}"
            )

        if not isinstance(label, str) or not label.strip():
            errors.append(f"Line {index}: label must be a non-empty string.")

        try:
            start = parse_utc(segment["start"])
            end = parse_utc(segment["end"])
        except ValueError as exc:
            errors.append(f"Line {index}: invalid timestamp: {exc}")
            continue

        if end <= start:
            errors.append(
                f"Line {index}: end must be after start "
                f"({segment['start']} -> {segment['end']})"
            )

        sessions_seen.add(session_id)
        by_session.setdefault(session_id, []).append(
            {
                **segment,
                "_start_dt": start,
                "_end_dt": end,
            }
        )

        if strict and label.upper() in {"UNKNOWN", "UNASSIGNED"}:
            errors.append(
                f"Line {index}: unresolved label {label!r} is not allowed "
                "in strict mode."
            )

    for session_id, items in by_session.items():
        items.sort(key=lambda item: (item["_start_dt"], item["_end_dt"]))

        for previous, current in zip(items, items[1:]):
            if current["_start_dt"] < previous["_end_dt"]:
                errors.append(
                    f"Session {session_id}: overlapping segments: "
                    f"{previous['start']} -> {previous['end']} and "
                    f"{current['start']} -> {current['end']}"
                )

    label_counts: dict[str, int] = {}
    for segment in segments:
        label = segment.get("label")
        if isinstance(label, str):
            label_counts[label] = label_counts.get(label, 0) + 1

    too_many_labels = (
        bool(segments)
        and len(label_counts) >= max(10, int(0.5 * len(segments)))
    )

    if too_many_labels:
        errors.append(
            "Label count is approaching segment count; "
            "label consistency may have failed."
        )

    if strict and sessions_seen != actual_sessions:
        missing = sorted(actual_sessions - sessions_seen)
        if missing:
            errors.append(
                f"Missing output segments for Dataset B sessions: {missing}"
            )

    return {
        "valid": not errors,
        "segments": len(segments),
        "sessions_seen": len(sessions_seen),
        "labels": label_counts,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a segments.jsonl file."
    )
    parser.add_argument("segments_path", type=Path)
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=Path("data/dataset_b"),
    )
    parser.add_argument(
        "--development",
        action="store_true",
        help="Disable strict final-output checks for placeholder development.",
    )
    args = parser.parse_args()

    result = validate_segments(
        args.segments_path,
        args.dataset_dir,
        strict=not args.development,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not result["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
