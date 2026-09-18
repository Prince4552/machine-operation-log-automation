from __future__ import annotations

import argparse
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    # Read JSONL explicitly as UTF-8 so Japanese text is preserved.
    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"WARNING: invalid JSON at line {line_number}: {exc}")
                continue

            if isinstance(obj, dict):
                records.append(obj)

    return records


def load_json(path: Path) -> dict[str, Any]:
    # Read JSON explicitly as UTF-8 so Japanese text is preserved.
    with path.open("r", encoding="utf-8") as f:
        obj = json.load(f)

    if not isinstance(obj, dict):
        raise ValueError(f"{path} does not contain a JSON object.")

    return obj


def short(value: Any, max_len: int = 80) -> str:
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


def print_manifest(manifest: dict[str, Any]) -> None:
    session = manifest.get("session", {})
    processes = manifest.get("processes", [])

    print("\n" + "=" * 100)
    print("GT MANIFEST")
    print("=" * 100)

    print(f"Run ID:        {short(manifest.get('run_id'))}")
    print(f"Session start: {short(session.get('start_ts'))}")
    print(f"Session end:   {short(session.get('end_ts'))}")
    print(f"Processes:     {len(processes)}")

    for process_index, process in enumerate(processes, start=1):
        code = process.get("code")
        name = process.get("family_name")
        domain = process.get("domain")
        executions = process.get("executions", [])

        print("\n" + "-" * 100)
        print(f"PROCESS {process_index}")
        print(f"  Code:       {short(code)}")
        print(f"  Name:       {short(name)}")
        print(f"  Domain:     {short(domain)}")
        print(f"  Executions: {len(executions)}")

        for execution_index, execution in enumerate(executions, start=1):
            print(f"\n  Execution {execution_index}")
            print(f"    Code:                    {short(execution.get('code'))}")
            print(f"    Variant:                 {short(execution.get('variant'))}")
            print(f"    Case ID:                 {short(execution.get('case_id'))}")
            print(f"    Start:                   {short(execution.get('start_ts'))}")
            print(f"    End:                     {short(execution.get('end_ts'))}")
            print(f"    Apps:                    {short(execution.get('apps'))}")
            print(f"    Phase:                   {short(execution.get('phase'))}")
            print(f"    Sequence:                {short(execution.get('seq'))}")
            print(
                "    Continues from previous: "
                f"{short(execution.get('continues_from_prev'))}"
            )
            print(
                "    Continues to next:       "
                f"{short(execution.get('continues_to_next'))}"
            )

    boundaries = manifest.get("expected_boundaries")
    if boundaries is not None:
        print("\n" + "-" * 100)
        print(
            "Expected boundaries: "
            f"{len(boundaries) if isinstance(boundaries, list) else 'present'}"
        )
        if isinstance(boundaries, list):
            for boundary in boundaries[:20]:
                print(f"  {short(boundary)}")
            if len(boundaries) > 20:
                print(f"  ... ({len(boundaries) - 20} more)")


def print_gt_timeline(records: list[dict[str, Any]]) -> None:
    print("\n" + "=" * 100)
    print("GT EVENT TIMELINE")
    print("=" * 100)

    header = (
        f"{'Timestamp':<30} "
        f"{'Event':<24} "
        f"{'Current process':<18} "
        f"{'Variant':<16} "
        "Details"
    )
    print(header)
    print("-" * len(header))

    for record in records:
        timestamp = short(record.get("ts_utc"), 30)
        event = short(record.get("event"), 24)
        current_process = short(record.get("current_process"), 18)
        variant = short(record.get("process_variant"), 16)

        details: list[str] = []
        event_name = record.get("event")

        if event_name == "process_started":
            details.append(f"code={short(record.get('process_code'))}")
            details.append(f"name={short(record.get('process_name'))}")
            details.append(f"case={short(record.get('case_id'))}")

        elif event_name == "process_switched_out":
            details.append(f"from={short(record.get('from'))}")
            details.append(f"to={short(record.get('to'))}")

        elif event_name == "process_suspended":
            details.append(f"from={short(record.get('from'))}")
            details.append(f"to={short(record.get('to'))}")
            details.append(f"split_id={short(record.get('split_id'))}")

        elif event_name == "process_resumed":
            details.append(f"process={short(record.get('process_code'))}")
            details.append(f"split_id={short(record.get('split_id'))}")
            details.append(f"phase={short(record.get('phase'))}")

        elif event_name == "task_started":
            details.append(f"task_id={short(record.get('task_id'))}")
            details.append(f"action={short(record.get('action'))}")
            details.append(f"entity={short(record.get('entity'))}")

        elif event_name in {"clipboard_copy", "clipboard_paste"}:
            details.append(f"target_app={short(record.get('target_app'))}")
            details.append(f"content={short(record.get('content_preview'))}")

        elif event_name == "run_config":
            details.append(f"operator={short(record.get('operator'))}")
            details.append(f"dept={short(record.get('operator_dept'))}")
            details.append(f"machine={short(record.get('machine_id'))}")

        elif event_name == "session_ended":
            details.append(f"tasks={short(record.get('total_tasks'))}")
            details.append(f"duration={short(record.get('duration_seconds'))}s")

        print(
            f"{timestamp:<30} "
            f"{event:<24} "
            f"{current_process:<18} "
            f"{variant:<16} "
            f"{' | '.join(details)}"
        )


def build_report(
    session_dir: Path,
    manifest: dict[str, Any],
    records: list[dict[str, Any]],
    total_gt_records: int,
) -> str:
    buffer = io.StringIO()

    with redirect_stdout(buffer):
        print(f"Session: {session_dir.name}")
        print(f"Manifest: {session_dir / 'gt_manifest.json'}")
        print(f"GT log:   {session_dir / 'gt.jsonl'}")

        print_manifest(manifest)
        print_gt_timeline(records)

        print("\n" + "=" * 100)
        suffix = ""
        if total_gt_records > len(records):
            suffix = " (limited by --max-events)"
        print(f"GT records displayed: {len(records)}{suffix}")
        print("=" * 100)

    return buffer.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect one Dataset A session's gt_manifest.json and gt.jsonl."
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("data"),
        help="Project data directory containing dataset_a (default: data)",
    )
    parser.add_argument(
        "--session",
        required=True,
        help="Session directory name, e.g. ses_20260630-121953-LAPTOP-R36BQBTE",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=200,
        help="Maximum GT timeline events to print (default: 200).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional UTF-8 text file to save the report.",
    )
    args = parser.parse_args()

    session_dir = (args.data_root / "dataset_a" / args.session).resolve()

    if not session_dir.is_dir():
        raise SystemExit(f"Session not found: {session_dir}")

    manifest_path = session_dir / "gt_manifest.json"
    gt_path = session_dir / "gt.jsonl"

    if not manifest_path.exists():
        raise SystemExit(f"Missing: {manifest_path}")

    if not gt_path.exists():
        raise SystemExit(f"Missing: {gt_path}")

    manifest = load_json(manifest_path)
    all_records = load_jsonl(gt_path)
    records = all_records[: args.max_events]

    report = build_report(
        session_dir=session_dir,
        manifest=manifest,
        records=records,
        total_gt_records=len(all_records),
    )

    # Print to the terminal.
    print(report, end="")

    # Write directly as UTF-8, bypassing PowerShell's output encoding.
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"\nSaved UTF-8 report to: {args.output.resolve()}")


if __name__ == "__main__":
    main()
