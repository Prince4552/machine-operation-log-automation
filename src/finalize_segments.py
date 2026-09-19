#!/usr/bin/env python3
"""Validate and write the final Step-1 segments.jsonl artifact.

Input: process_discovery_final.py's segments_labeled.jsonl
Output: exactly four fields per line:
  session_id, start, end, label

The script does not merge segments. Separate contiguous segments may share the
same workflow label, which is allowed by the task and preserves interruption
boundaries.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

REQUIRED = {"session_id", "start", "end", "label"}
FORBIDDEN_UNRESOLVED = {"", "UNKNOWN", "UNASSIGNED"}


def parse_ts(v: Any) -> float:
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"invalid timestamp: {v!r}")
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError(f"timestamp must contain timezone: {v!r}")
    return dt.timestamp()


def load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            row = json.loads(raw)
            if not isinstance(row, dict):
                raise ValueError(f"line {line_no}: not a JSON object")
            missing = REQUIRED - set(row)
            if missing:
                raise ValueError(f"line {line_no}: missing required fields {sorted(missing)}")
            sid = row["session_id"]
            label = row["label"]
            if not isinstance(sid, str) or not sid:
                raise ValueError(f"line {line_no}: invalid session_id")
            if not isinstance(label, str) or label.strip() in FORBIDDEN_UNRESOLVED:
                raise ValueError(f"line {line_no}: unresolved/empty label {label!r}")
            start = parse_ts(row["start"])
            end = parse_ts(row["end"])
            if end <= start:
                raise ValueError(f"line {line_no}: segment must have start < end")
            rows.append({"session_id": sid, "start": row["start"], "end": row["end"],
                         "label": label.strip(), "_start": start, "_end": end})
    return rows


def validate(rows: list[dict[str, Any]], expected_sessions: int | None) -> dict[str, Any]:
    by_session: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_session.setdefault(row["session_id"], []).append(row)

    if expected_sessions is not None and len(by_session) != expected_sessions:
        raise ValueError(
            f"expected {expected_sessions} sessions, found {len(by_session)}: "
            f"{sorted(by_session)[:5]}"
        )

    labels = Counter(row["label"] for row in rows)
    for sid, session_rows in by_session.items():
        session_rows.sort(key=lambda r: (r["_start"], r["_end"], r["label"]))
        for left, right in zip(session_rows, session_rows[1:]):
            if right["_start"] < left["_end"]:
                raise ValueError(f"overlap in session {sid}: {left} vs {right}")

    return {
        "segment_count": len(rows),
        "session_count": len(by_session),
        "label_count": len(labels),
        "sessions": sorted(by_session),
        "top_labels": labels.most_common(20),
        "all_labels_resolved": all(label not in FORBIDDEN_UNRESOLVED for label in labels),
    }


def write_output(rows: list[dict[str, Any]], path: Path) -> None:
    ordered = sorted(rows, key=lambda r: (r["session_id"], r["_start"], r["_end"], r["label"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in ordered:
            handle.write(json.dumps({
                "session_id": row["session_id"],
                "start": row["start"],
                "end": row["end"],
                "label": row["label"],
            }, ensure_ascii=False) + "\n")


def preflight() -> None:
    rows = [
        {"session_id": "s1", "start": "2026-01-01T00:00:00Z", "end": "2026-01-01T00:00:10Z", "label": "WORKFLOW_001"},
        {"session_id": "s1", "start": "2026-01-01T00:00:12Z", "end": "2026-01-01T00:00:20Z", "label": "WORKFLOW_001"},
        {"session_id": "s2", "start": "2026-01-01T00:00:00Z", "end": "2026-01-01T00:00:15Z", "label": "WORKFLOW_002"},
    ]
    tmp = []
    for r in rows:
        x = dict(r)
        x["_start"] = parse_ts(r["start"])
        x["_end"] = parse_ts(r["end"])
        tmp.append(x)
    report = validate(tmp, expected_sessions=2)
    assert report["segment_count"] == 3
    assert report["label_count"] == 2
    assert report["all_labels_resolved"] is True
    print("Preflight final-segments self-test: PASS (3 assertions)", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize and validate segments.jsonl")
    parser.add_argument("--input", required=True, help="segments_labeled.jsonl")
    parser.add_argument("--output", required=True, help="final segments.jsonl")
    parser.add_argument("--expected-sessions", type=int, default=None)
    parser.add_argument("--report", default=None, help="optional validation report JSON")
    args = parser.parse_args()

    preflight()
    rows = load_rows(Path(args.input))
    report = validate(rows, args.expected_sessions)
    write_output(rows, Path(args.output))
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("FINAL SEGMENTS VALIDATION", flush=True)
    print("=" * 78, flush=True)
    print(f"Sessions:       {report['session_count']}", flush=True)
    print(f"Segments:       {report['segment_count']}", flush=True)
    print(f"Workflow labels:{report['label_count']}", flush=True)
    print("Overlaps:       0", flush=True)
    print("Unresolved:     0", flush=True)
    print(f"Wrote:          {args.output}", flush=True)
    if args.report:
        print(f"Report:         {args.report}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
