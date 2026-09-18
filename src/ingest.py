from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


REQUIRED_EVENT_FIELDS = {
    "event_id",
    "session_id",
    "timestamp_iso",
    "layer",
    "event_type",
}


def iter_jsonl(path: Path) -> Iterator[tuple[int, dict[str, Any] | None, str | None]]:
    """Yield (line_number, parsed_object, error_message)."""
    with path.open("r", encoding="utf-8") as f:
        for line_number, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue

            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                yield line_number, None, f"invalid JSON: {exc}"
                continue

            if not isinstance(obj, dict):
                yield line_number, None, "JSON value is not an object"
                continue

            yield line_number, obj, None


def parse_timestamp(event: dict[str, Any]) -> datetime | None:
    """Return an aware UTC datetime from timestamp_iso or timestamp_ms."""
    timestamp_iso = event.get("timestamp_iso")
    if isinstance(timestamp_iso, str) and timestamp_iso:
        try:
            value = timestamp_iso.replace("Z", "+00:00")
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass

    timestamp_ms = event.get("timestamp_ms")
    if isinstance(timestamp_ms, (int, float)):
        try:
            return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            pass

    return None


def find_sessions(dataset_dir: Path) -> list[Path]:
    """Find session directories directly under dataset_a or dataset_b."""
    return sorted(
        p for p in dataset_dir.iterdir()
        if p.is_dir() and p.name.startswith("ses_")
    )


def inspect_session(session_dir: Path) -> dict[str, Any]:
    chunks = sorted(
        p for p in session_dir.iterdir()
        if p.is_dir() and p.name.startswith("chunk_")
    )

    event_count = 0
    event_types: Counter[str] = Counter()
    layers: Counter[str] = Counter()

    timestamps: list[datetime] = []
    machine_ids: set[str] = set()
    chunk_summaries: list[dict[str, Any]] = []

    invalid_json_lines = 0
    missing_required_fields = 0

    for chunk_dir in chunks:
        events_path = chunk_dir / "events.jsonl"
        screenshots_dir = chunk_dir / "screenshots"

        chunk_event_count = 0
        chunk_invalid_json = 0
        chunk_missing_required = 0

        if not events_path.exists():
            chunk_summaries.append(
                {
                    "chunk_id": chunk_dir.name,
                    "events": 0,
                    "screenshots_present": screenshots_dir.is_dir(),
                    "events_file_missing": True,
                    "invalid_json_lines": 0,
                    "missing_required_fields": 0,
                }
            )
            continue

        for _, event, error in iter_jsonl(events_path):
            if error is not None:
                invalid_json_lines += 1
                chunk_invalid_json += 1
                continue

            assert event is not None

            missing = REQUIRED_EVENT_FIELDS - event.keys()
            if missing:
                missing_required_fields += 1
                chunk_missing_required += 1

            event_count += 1
            chunk_event_count += 1

            event_type = event.get("event_type")
            if isinstance(event_type, str):
                event_types[event_type] += 1
            else:
                event_types["<missing>"] += 1

            layer = event.get("layer")
            if isinstance(layer, str):
                layers[layer] += 1
            else:
                layers["<missing>"] += 1

            dt = parse_timestamp(event)
            if dt is not None:
                timestamps.append(dt)

            source = event.get("source")
            if isinstance(source, dict):
                machine_id = source.get("machine_id")
                if isinstance(machine_id, str) and machine_id:
                    machine_ids.add(machine_id)

        chunk_summaries.append(
            {
                "chunk_id": chunk_dir.name,
                "events": chunk_event_count,
                "screenshots_present": screenshots_dir.is_dir(),
                "events_file_missing": False,
                "invalid_json_lines": chunk_invalid_json,
                "missing_required_fields": chunk_missing_required,
            }
        )

    start_dt = min(timestamps) if timestamps else None
    end_dt = max(timestamps) if timestamps else None

    return {
        "session_id": session_dir.name,
        "chunks": len(chunks),
        "events": event_count,
        "start": start_dt.isoformat().replace("+00:00", "Z") if start_dt else None,
        "end": end_dt.isoformat().replace("+00:00", "Z") if end_dt else None,
        "machine_ids": sorted(machine_ids),
        "screenshots_present_in_chunks": sum(
            1 for item in chunk_summaries if item["screenshots_present"]
        ),
        "chunks_without_screenshots": sum(
            1 for item in chunk_summaries if not item["screenshots_present"]
        ),
        "missing_events_files": sum(
            1 for item in chunk_summaries if item["events_file_missing"]
        ),
        "invalid_json_lines": invalid_json_lines,
        "events_with_missing_required_fields": missing_required_fields,
        "event_types": dict(event_types),
        "layers": dict(layers),
        "chunk_summaries": chunk_summaries,
    }


def summarize_dataset(
    dataset_name: str,
    dataset_dir: Path,
) -> dict[str, Any]:
    sessions = find_sessions(dataset_dir)
    session_data = [inspect_session(session_dir) for session_dir in sessions]

    chunk_counts = [item["chunks"] for item in session_data]
    event_counts = [item["events"] for item in session_data]

    all_event_types: Counter[str] = Counter()
    all_layers: Counter[str] = Counter()

    for item in session_data:
        all_event_types.update(item["event_types"])
        all_layers.update(item["layers"])

    return {
        "dataset": dataset_name,
        "path": str(dataset_dir),
        "sessions": len(session_data),
        "total_chunks": sum(chunk_counts),
        "total_events": sum(event_counts),
        "avg_chunks_per_session": (
            sum(chunk_counts) / len(chunk_counts) if chunk_counts else 0.0
        ),
        "min_chunks_per_session": min(chunk_counts) if chunk_counts else 0,
        "max_chunks_per_session": max(chunk_counts) if chunk_counts else 0,
        "avg_events_per_session": (
            sum(event_counts) / len(event_counts) if event_counts else 0.0
        ),
        "min_events_per_session": min(event_counts) if event_counts else 0,
        "max_events_per_session": max(event_counts) if event_counts else 0,
        "event_types": dict(all_event_types),
        "layers": dict(all_layers),
        "sessions_detail": session_data,
    }


def print_dataset_summary(summary: dict[str, Any]) -> None:
    print("=" * 90)
    print(summary["dataset"])
    print("=" * 90)

    print(f"Path:                 {summary['path']}")
    print(f"Sessions:             {summary['sessions']}")
    print(f"Total chunks:         {summary['total_chunks']}")
    print(f"Avg chunks/session:   {summary['avg_chunks_per_session']:.2f}")
    print(f"Min chunks/session:   {summary['min_chunks_per_session']}")
    print(f"Max chunks/session:   {summary['max_chunks_per_session']}")
    print(f"Total events:         {summary['total_events']}")
    print(f"Avg events/session:   {summary['avg_events_per_session']:.2f}")
    print(f"Min events/session:   {summary['min_events_per_session']}")
    print(f"Max events/session:   {summary['max_events_per_session']}")

    print("\nEvent types:")
    for event_type, count in sorted(
        summary["event_types"].items(),
        key=lambda item: (-item[1], item[0]),
    ):
        print(f"  {event_type:<30} {count:>10,}")

    print("\nLayers:")
    for layer, count in sorted(
        summary["layers"].items(),
        key=lambda item: (-item[1], item[0]),
    ):
        print(f"  {layer:<30} {count:>10,}")

    print("\nPer-session inventory:")
    header = (
        f"{'Session':<48} {'Chunks':>6} {'Events':>9} "
        f"{'Screenshots':>12} {'Machine ID':<22}"
    )
    print(header)
    print("-" * len(header))

    for item in summary["sessions_detail"]:
        machine = ", ".join(item["machine_ids"]) if item["machine_ids"] else "<unknown>"
        print(
            f"{item['session_id']:<48} "
            f"{item['chunks']:>6} "
            f"{item['events']:>9,} "
            f"{item['screenshots_present_in_chunks']:>12} "
            f"{machine:<22}"
        )

    problems = [
        item
        for item in summary["sessions_detail"]
        if item["missing_events_files"]
        or item["invalid_json_lines"]
        or item["events_with_missing_required_fields"]
    ]

    if problems:
        print("\nValidation notes:")
        for item in problems:
            print(
                f"  {item['session_id']}: "
                f"missing events files={item['missing_events_files']}, "
                f"invalid JSON lines={item['invalid_json_lines']}, "
                f"events missing required fields="
                f"{item['events_with_missing_required_fields']}"
            )
    else:
        print("\nBasic validation: no missing event files, invalid JSON, "
              "or missing required event fields detected.")


def save_json_summary(
    summaries: list[dict[str, Any]],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(summaries, f, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inventory Dataset A and Dataset B operation logs."
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("data"),
        help="Project data directory containing dataset_a and dataset_b "
             "(default: data)",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path for a JSON copy of the inventory.",
    )
    args = parser.parse_args()

    data_root = args.data_root.resolve()

    if not data_root.exists():
        raise SystemExit(f"Data directory not found: {data_root}")

    summaries: list[dict[str, Any]] = []

    expected = {
        "Dataset A": ("dataset_a", 63),
        "Dataset B": ("dataset_b", 15),
    }

    for dataset_name, (folder_name, expected_sessions) in expected.items():
        dataset_dir = data_root / folder_name

        if not dataset_dir.exists():
            raise SystemExit(f"Missing dataset directory: {dataset_dir}")

        summary = summarize_dataset(dataset_name, dataset_dir)
        summaries.append(summary)
        print_dataset_summary(summary)

        if summary["sessions"] != expected_sessions:
            print(
                f"\nWARNING: expected about {expected_sessions} sessions "
                f"from the task specification, but found {summary['sessions']}."
            )

        print()

    if args.json_out is not None:
        save_json_summary(summaries, args.json_out)
        print(f"Inventory JSON written to: {args.json_out.resolve()}")


if __name__ == "__main__":
    main()
