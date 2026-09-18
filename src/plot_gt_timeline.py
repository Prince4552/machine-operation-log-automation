from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO-8601 timestamp, including timestamps ending in Z."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_session_executions(payload: dict[str, Any], session_id: str | None) -> tuple[str, list[dict[str, Any]]]:
    """
    Support both:
    1. the old single-session GT format:
       {"session_id": "...", "executions": [...]}
    2. the current multi-session ground_truth.json format:
       {"sessions": [{"session_id": "...", "executions": [...]}, ...]}
    """
    # Current multi-session format.
    sessions = payload.get("sessions")
    if isinstance(sessions, list):
        session_map: dict[str, dict[str, Any]] = {}

        for session in sessions:
            if not isinstance(session, dict):
                continue

            sid = session.get("session_id")
            if isinstance(sid, str) and sid:
                session_map[sid] = session

        if not session_map:
            raise ValueError("No valid sessions found in the ground-truth JSON.")

        if session_id is None:
            # Preserve the existing one-session visualization workflow:
            # use the first session when no --session is supplied.
            selected_id = next(iter(session_map))
        else:
            selected_id = session_id

        if selected_id not in session_map:
            raise ValueError(
                f"Session {selected_id!r} not found in ground-truth JSON."
            )

        selected = session_map[selected_id]
        executions = selected.get("executions", [])

        if not isinstance(executions, list):
            raise ValueError(
                f"Session {selected_id!r} does not contain a valid 'executions' list."
            )

        return selected_id, executions

    # Backward-compatible single-session format.
    executions = payload.get("executions")
    if isinstance(executions, list):
        selected_id = payload.get("session_id")

        if not isinstance(selected_id, str) or not selected_id:
            raise ValueError(
                "Single-session GT JSON must contain a non-empty 'session_id'."
            )

        if session_id is not None and session_id != selected_id:
            raise ValueError(
                f"Requested session {session_id!r} does not match "
                f"the GT session {selected_id!r}."
            )

        return selected_id, executions

    raise ValueError(
        "Unsupported GT JSON format. Expected either 'sessions' or 'executions'."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot one Dataset A session's GT execution timeline."
    )
    parser.add_argument(
        "--gt-json",
        type=Path,
        required=True,
        help="JSON produced by ground_truth.py.",
    )
    parser.add_argument(
        "--session",
        help=(
            "Optional session_id to visualize. If omitted, the first session "
            "in the multi-session GT file is used."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="PNG output path.",
    )
    args = parser.parse_args()

    if not args.gt_json.exists():
        raise SystemExit(f"GT JSON not found: {args.gt_json}")

    with args.gt_json.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    if not isinstance(payload, dict):
        raise SystemExit("GT JSON root must be a JSON object.")

    try:
        selected_session_id, raw_executions = load_session_executions(
            payload,
            args.session,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    executions = [
        item
        for item in raw_executions
        if isinstance(item, dict)
        and item.get("start")
        and item.get("end")
        and item.get("process_code")
    ]

    executions.sort(key=lambda item: parse_timestamp(item["start"]))

    if not executions:
        raise SystemExit(
            f"No plottable executions found for session {selected_session_id!r}."
        )

    labels = sorted({item["process_code"] for item in executions})
    y_positions = {label: index for index, label in enumerate(labels)}

    fig, ax = plt.subplots(
        figsize=(14, max(4, 1 + 0.7 * len(labels)))
    )

    for execution in executions:
        start = parse_timestamp(execution["start"])
        end = parse_timestamp(execution["end"])
        duration = (end - start).total_seconds()

        y = y_positions[execution["process_code"]]

        ax.barh(
            y,
            duration,
            left=start,
            height=0.55,
        )

    ax.set_yticks(list(y_positions.values()))
    ax.set_yticklabels(labels)
    ax.set_xlabel("UTC time")
    ax.set_ylabel("Process code")
    ax.set_title(
        f"Dataset A GT execution timeline — {selected_session_id}"
    )

    fig.autofmt_xdate()
    fig.tight_layout()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=160)
    plt.close(fig)

    print(f"Session: {selected_session_id}")
    print(f"Executions plotted: {len(executions)}")
    print(f"Saved timeline plot to {args.output.resolve()}")


if __name__ == "__main__":
    main()
