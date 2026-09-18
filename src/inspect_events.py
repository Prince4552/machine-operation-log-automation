from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_events(path: Path, limit: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            if len(events) >= limit:
                break

            line = line.strip()
            if not line:
                continue

            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                print(f"Skipping invalid JSON at line {line_number}")
                continue

            if isinstance(obj, dict):
                events.append(obj)

    return events


def as_text(value: Any, max_len: int = 32) -> str:
    if value is None:
        return ""

    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)

    text = " ".join(text.split())
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def get_context_value(context: Any, key: str) -> Any:
    return context.get(key) if isinstance(context, dict) else None


def get_active_app_name(active_app: Any) -> str:
    if isinstance(active_app, dict):
        return (
            active_app.get("app_name")
            or active_app.get("process_name")
            or ""
        )
    return str(active_app or "")


def get_window_title(active_app: Any) -> str:
    if isinstance(active_app, dict):
        return str(active_app.get("window_title") or "")
    return ""


def print_events(events: list[dict[str, Any]]) -> None:
    print()
    print(
        f"{'#':>3}  {'Timestamp':<24} {'Type':<24} "
        f"{'Layer':<7} {'App':<18} {'Window':<28} {'Text'}"
    )
    print("-" * 125)

    for index, event in enumerate(events, start=1):
        context = event.get("context", {})
        active_app = get_context_value(context, "active_app")
        active_tab = get_context_value(context, "active_browser_tab")

        timestamp = event.get("timestamp_iso", "")
        event_type = event.get("event_type", "")
        layer = event.get("layer", "")

        app = get_active_app_name(active_app)
        window = get_window_title(active_app)

        if not window:
            window = as_text(
                get_context_value(context, "active_browser_tab"),
                max_len=28,
            )

        extracted_text = as_text(
            get_context_value(context, "extracted_text"),
            max_len=36,
        )

        print(
            f"{index:>3}  "
            f"{as_text(timestamp, 24):<24} "
            f"{as_text(event_type, 24):<24} "
            f"{as_text(layer, 7):<7} "
            f"{as_text(app, 18):<18} "
            f"{as_text(window, 28):<28} "
            f"{extracted_text}"
        )

        # Show a little extra context for browser events when useful.
        if isinstance(active_tab, dict):
            url = active_tab.get("url")
            title = active_tab.get("title")
            if url or title:
                print(
                    f"     browser: "
                    f"title={as_text(title, 40)} "
                    f"url={as_text(url, 70)}"
                )


def find_first_session(dataset_dir: Path) -> Path:
    sessions = sorted(
        p for p in dataset_dir.iterdir()
        if p.is_dir() and p.name.startswith("ses_")
    )
    if not sessions:
        raise SystemExit(f"No sessions found in {dataset_dir}")
    return sessions[0]


def find_first_chunk(session_dir: Path) -> Path:
    chunks = sorted(
        p for p in session_dir.iterdir()
        if p.is_dir() and p.name.startswith("chunk_")
    )
    if not chunks:
        raise SystemExit(f"No chunks found in {session_dir}")
    return chunks[0]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print a readable sample of raw events from one chunk."
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
        help="Session directory name. If omitted, the first session is used.",
    )
    parser.add_argument(
        "--chunk",
        help="Chunk directory name. If omitted, the first chunk is used.",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=100,
        help="Number of events to display (default: 100).",
    )
    args = parser.parse_args()

    dataset_dir = (args.data_root / args.dataset).resolve()

    if args.session:
        session_dir = dataset_dir / args.session
    else:
        session_dir = find_first_session(dataset_dir)

    if not session_dir.is_dir():
        raise SystemExit(f"Session not found: {session_dir}")

    if args.chunk:
        chunk_dir = session_dir / args.chunk
    else:
        chunk_dir = find_first_chunk(session_dir)

    events_path = chunk_dir / "events.jsonl"
    if not events_path.exists():
        raise SystemExit(f"events.jsonl not found: {events_path}")

    print(f"Dataset: {args.dataset}")
    print(f"Session: {session_dir.name}")
    print(f"Chunk:   {chunk_dir.name}")
    print(f"File:    {events_path}")
    print(f"Showing first {args.n} valid events")

    events = load_events(events_path, args.n)
    print_events(events)
    print(f"\nDisplayed events: {len(events)}")


if __name__ == "__main__":
    main()
