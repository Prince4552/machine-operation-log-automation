from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        raise ValueError(f"Timestamp has no timezone: {value}")
    return dt.astimezone(timezone.utc)


def session_bounds(session_dir: Path) -> tuple[str, str]:
    timestamps: list[str] = []

    chunks = sorted(
        p for p in session_dir.iterdir()
        if p.is_dir() and p.name.startswith("chunk_")
    )

    for chunk in chunks:
        events_path = chunk / "events.jsonl"
        if not events_path.exists():
            continue

        with events_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                event: dict[str, Any] = json.loads(line)
                timestamp = event.get("timestamp_iso")

                if isinstance(timestamp, str):
                    timestamps.append(timestamp)

    if not timestamps:
        raise ValueError(f"No timestamps found in {session_dir}")

    start = min(timestamps, key=parse_timestamp)
    end = max(timestamps, key=parse_timestamp)
    return start, end


def find_sessions(dataset_dir: Path) -> list[Path]:
    return sorted(
        p for p in dataset_dir.iterdir()
        if p.is_dir() and p.name.startswith("ses_")
    )


def build_placeholder_segments(
    dataset_dir: Path,
    label: str,
) -> list[dict[str, str]]:
    segments: list[dict[str, str]] = []

    for session_dir in find_sessions(dataset_dir):
        start, end = session_bounds(session_dir)

        if parse_timestamp(end) <= parse_timestamp(start):
            continue

        segments.append(
            {
                "session_id": session_dir.name,
                "start": start,
                "end": end,
                "label": label,
            }
        )

    return segments


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create the deliberately simple whole-session baseline."
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("data"),
    )
    parser.add_argument(
        "--dataset",
        choices=["dataset_a", "dataset_b"],
        default="dataset_a",
    )
    parser.add_argument(
        "--session",
        default=None,
        help="Optional single session directory name. If omitted, use all sessions.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/placeholder_segments.jsonl"),
    )
    parser.add_argument(
        "--label",
        default="placeholder",
    )
    args = parser.parse_args()

    dataset_dir = (args.data_root / args.dataset).resolve()

    if args.session:
        session_dir = dataset_dir / args.session
        if not session_dir.is_dir():
            raise SystemExit(f"Session not found: {session_dir}")

        start, end = session_bounds(session_dir)
        if parse_timestamp(end) <= parse_timestamp(start):
            segments = []
        else:
            segments = [{
                "session_id": session_dir.name,
                "start": start,
                "end": end,
                "label": args.label,
            }]
    else:
        segments = build_placeholder_segments(
            dataset_dir=dataset_dir,
            label=args.label,
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)

    with args.output.open("w", encoding="utf-8", newline="\n") as f:
        for segment in segments:
            f.write(json.dumps(segment, ensure_ascii=False) + "\n")

    print(f"Wrote {len(segments)} placeholder segments to {args.output.resolve()}")


if __name__ == "__main__":
    main()
