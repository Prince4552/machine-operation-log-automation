from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


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
        "--output",
        type=Path,
        required=True,
        help="PNG output path.",
    )
    args = parser.parse_args()

    with args.gt_json.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    executions = [
        item
        for item in payload["executions"]
        if item.get("start") and item.get("end")
    ]

    labels = sorted({item["process_code"] for item in executions})
    y_positions = {label: index for index, label in enumerate(labels)}

    fig, ax = plt.subplots(figsize=(14, max(4, 1 + 0.7 * len(labels))))

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
    ax.set_title(f"Dataset A GT execution timeline — {payload['session_id']}")
    fig.autofmt_xdate()
    fig.tight_layout()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=160)
    plt.close(fig)

    print(f"Saved timeline plot to {args.output.resolve()}")


if __name__ == "__main__":
    main()
