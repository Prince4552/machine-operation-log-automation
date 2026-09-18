from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class Execution:
    execution_id: str
    session_id: str
    process_code: str
    process_name: str
    domain: str | None
    variant: str | None
    case_id: str | None
    start: str | None
    end: str | None
    end_source: str | None
    end_event: str | None
    apps: list[str]
    phase: int | None
    seq: int | None
    continues_from_prev: bool
    continues_to_next: bool


@dataclass
class Segment:
    segment_id: str
    session_id: str
    execution_id: str | None
    process_code: str
    process_name: str
    start: str
    end: str
    start_event: str
    end_event: str | None


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        value = json.load(f)

    if not isinstance(value, dict):
        raise ValueError(f"{path} does not contain a JSON object.")

    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON in {path} at line {line_number}: {exc}"
                ) from exc

            if not isinstance(value, dict):
                raise ValueError(
                    f"Expected JSON object in {path} at line {line_number}"
                )

            records.append(value)

    return records


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def make_execution_id(
    process_code: str,
    seq: int | None,
    case_id: str | None,
    fallback_index: int,
) -> str:
    if case_id:
        return f"{process_code}:{case_id}"
    if seq is not None:
        return f"{process_code}:seq-{seq}"
    return f"{process_code}:execution-{fallback_index}"


def reconstruct_executions(
    session_dir: Path,
) -> tuple[list[Execution], list[str]]:
    """Read execution records from gt_manifest.json.

    gt_manifest.json is the canonical source for execution identity and
    metadata. Missing end timestamps are preserved initially and can later be
    filled from the matching contiguous GT segment in gt.jsonl.
    """
    manifest_path = session_dir / "gt_manifest.json"
    manifest = load_json(manifest_path)

    executions: list[Execution] = []
    warnings: list[str] = []

    session_id = session_dir.name
    seen_ids: set[str] = set()

    processes = manifest.get("processes", [])
    if not isinstance(processes, list):
        raise ValueError(f"{manifest_path}: 'processes' is not a list.")

    for process in processes:
        if not isinstance(process, dict):
            warnings.append(
                f"{session_id}: malformed process entry ignored."
            )
            continue

        process_code = process.get("code")
        process_name = process.get("family_name", "")
        domain = process.get("domain")

        if not isinstance(process_code, str) or not process_code:
            warnings.append(
                f"{session_id}: process entry has no valid code."
            )
            continue

        if not isinstance(process_name, str):
            process_name = str(process_name)

        raw_executions = process.get("executions", [])
        if not isinstance(raw_executions, list):
            warnings.append(
                f"{session_id}: process {process_code!r} has a non-list "
                "'executions' field."
            )
            continue

        for fallback_index, raw in enumerate(raw_executions, start=1):
            if not isinstance(raw, dict):
                warnings.append(
                    f"{session_id}: malformed execution under "
                    f"process {process_code!r}."
                )
                continue

            variant = raw.get("variant")
            case_id = raw.get("case_id")
            start = raw.get("start_ts")
            end = raw.get("end_ts")

            variant = variant if isinstance(variant, str) else None
            case_id = case_id if isinstance(case_id, str) else None
            start = start if isinstance(start, str) else None
            end = end if isinstance(end, str) else None

            phase = raw.get("phase")
            phase = phase if isinstance(phase, int) else None

            seq = raw.get("seq")
            seq = seq if isinstance(seq, int) else None

            apps = raw.get("apps", [])
            if not isinstance(apps, list):
                apps = []

            execution_id = make_execution_id(
                process_code,
                seq,
                case_id,
                fallback_index,
            )

            if execution_id in seen_ids:
                warnings.append(
                    f"{session_id}: duplicate execution_id "
                    f"{execution_id!r}."
                )
            seen_ids.add(execution_id)

            if start is None:
                warnings.append(
                    f"{session_id}: execution {execution_id} has no start_ts."
                )
            else:
                try:
                    parse_ts(start)
                except ValueError:
                    warnings.append(
                        f"{session_id}: execution {execution_id} has "
                        f"invalid start_ts={start!r}."
                    )

            if end is not None:
                try:
                    parse_ts(end)
                except ValueError:
                    warnings.append(
                        f"{session_id}: execution {execution_id} has "
                        f"invalid end_ts={end!r}."
                    )

            executions.append(
                Execution(
                    execution_id=execution_id,
                    session_id=session_id,
                    process_code=process_code,
                    process_name=process_name,
                    domain=domain if isinstance(domain, str) else None,
                    variant=variant,
                    case_id=case_id,
                    start=start,
                    end=end,
                    end_source="manifest" if end is not None else None,
                    end_event=None,
                    apps=[str(app) for app in apps],
                    phase=phase,
                    seq=seq,
                    continues_from_prev=bool(
                        raw.get("continues_from_prev", False)
                    ),
                    continues_to_next=bool(
                        raw.get("continues_to_next", False)
                    ),
                )
            )

    return executions, warnings


def reconstruct_gt_segments(
    session_dir: Path,
    process_names: dict[str, str],
) -> tuple[list[Segment], list[str]]:
    """Turn gt.jsonl process transitions into contiguous time segments.

    We intentionally do not infer execution identity from split_id. The
    manifest remains the canonical source for case/execution identity.
    """
    gt_path = session_dir / "gt.jsonl"
    records = load_jsonl(gt_path)

    session_id = session_dir.name
    warnings: list[str] = []
    segments: list[Segment] = []

    active_process: str | None = None
    active_case_id: str | None = None
    active_start: str | None = None
    active_start_event: str | None = None
    segment_number = 0

    def close_active(end_ts: str, end_event: str) -> None:
        nonlocal active_process
        nonlocal active_case_id
        nonlocal active_start
        nonlocal active_start_event
        nonlocal segment_number

        if active_process is None or active_start is None:
            warnings.append(
                f"{session_id}: {end_event} at {end_ts} occurred without "
                "an active process."
            )
            active_process = None
            active_case_id = None
            active_start = None
            active_start_event = None
            return

        try:
            if parse_ts(end_ts) <= parse_ts(active_start):
                warnings.append(
                    f"{session_id}: ignored non-positive GT segment "
                    f"{active_process}: {active_start} -> {end_ts}."
                )
            else:
                segment_number += 1
                segments.append(
                    Segment(
                        segment_id=(
                            f"{session_id}:seg-{segment_number:04d}"
                        ),
                        session_id=session_id,
                        execution_id=None,
                        process_code=active_process,
                        process_name=process_names.get(active_process, ""),
                        start=active_start,
                        end=end_ts,
                        start_event=active_start_event or "unknown",
                        end_event=end_event,
                    )
                )
        except ValueError:
            warnings.append(
                f"{session_id}: invalid GT segment timestamps "
                f"{active_start!r} -> {end_ts!r}."
            )

        active_process = None
        active_case_id = None
        active_start = None
        active_start_event = None

    for record_index, record in enumerate(records, start=1):
        event = record.get("event")
        ts = record.get("ts_utc")

        if not isinstance(event, str) or not isinstance(ts, str):
            warnings.append(
                f"{session_id}: GT record {record_index} has invalid "
                "event/ts_utc."
            )
            continue

        if event == "run_config":
            continue

        if event == "process_started":
            process_code = record.get("process_code")
            case_id = record.get("case_id")

            if not isinstance(process_code, str) or not process_code:
                warnings.append(
                    f"{session_id}: process_started at {ts} has no "
                    "valid process_code."
                )
                continue

            case_id = case_id if isinstance(case_id, str) else None

            # The schema says the recorder can emit the same process_started
            # twice in a row. Ignore it only when both the process AND case
            # match the currently active state.
            #
            # Same process + different case is a legitimate new execution.
            if (
                active_process == process_code
                and active_case_id == case_id
                and active_start is not None
            ):
                warnings.append(
                    f"{session_id}: ignored duplicate process_started "
                    f"for process={process_code}, case={case_id} at {ts}."
                )
                continue

            if active_process is not None:
                close_active(ts, "process_started")

            active_process = process_code
            active_case_id = case_id
            active_start = ts
            active_start_event = event

        elif event == "process_resumed":
            process_code = record.get("process_code")

            if not isinstance(process_code, str) or not process_code:
                warnings.append(
                    f"{session_id}: process_resumed at {ts} has no "
                    "valid process_code."
                )
                continue

            if active_process is not None:
                close_active(ts, "process_resumed")

            active_process = process_code
            active_case_id = None
            active_start = ts
            active_start_event = event

        elif event in {
            "process_switched_out",
            "process_suspended",
        }:
            close_active(ts, event)

        elif event == "session_ended":
            close_active(ts, event)

    if active_process is not None:
        warnings.append(
            f"{session_id}: gt.jsonl ended with active process "
            f"{active_process!r}; no synthetic end was created."
        )

    return segments, warnings


def attach_segments_and_infer_missing_ends(
    executions: list[Execution],
    segments: list[Segment],
    session_id: str,
) -> list[str]:
    """Link each contiguous GT segment to a manifest execution.

    Primary matching key:
        process_code + exact start timestamp

    We consume matches one-to-one. For missing execution end_ts, the matched
    segment's end becomes the inferred execution end, and provenance is
    recorded explicitly.
    """
    warnings: list[str] = []

    candidates: dict[tuple[str, str], list[int]] = {}

    for index, execution in enumerate(executions):
        if execution.start is None:
            continue

        key = (execution.process_code, execution.start)
        candidates.setdefault(key, []).append(index)

    used_execution_indices: set[int] = set()

    for segment in segments:
        key = (segment.process_code, segment.start)
        matches = candidates.get(key, [])

        # Prefer an unused execution when several share the same start.
        execution_index = next(
            (
                index
                for index in matches
                if index not in used_execution_indices
            ),
            None,
        )

        if execution_index is None:
            warnings.append(
                f"{session_id}: could not link segment "
                f"{segment.segment_id} to a manifest execution "
                f"using process_code={segment.process_code!r}, "
                f"start={segment.start!r}."
            )
            continue

        execution = executions[execution_index]
        used_execution_indices.add(execution_index)
        segment.execution_id = execution.execution_id

        if execution.end is None:
            execution.end = segment.end
            execution.end_source = "gt_log_inferred"
            execution.end_event = segment.end_event

    # Every execution with start + known end should normally have a matching
    # segment. An execution with no end can still be retained as incomplete.
    for index, execution in enumerate(executions):
        if execution.start is None:
            continue

        if index not in used_execution_indices:
            warnings.append(
                f"{session_id}: execution {execution.execution_id} had "
                "no matching contiguous GT segment."
            )

    return warnings


def validate_segments(segments: list[Segment]) -> list[str]:
    warnings: list[str] = []

    ordered = sorted(
        segments,
        key=lambda segment: parse_ts(segment.start),
    )

    for previous, current in zip(ordered, ordered[1:]):
        try:
            if parse_ts(current.start) < parse_ts(previous.end):
                warnings.append(
                    f"{current.session_id}: overlapping GT segments: "
                    f"{previous.start}->{previous.end} and "
                    f"{current.start}->{current.end}."
                )
        except ValueError:
            continue

    return warnings


def build_session_result(session_dir: Path) -> dict[str, Any]:
    executions, execution_warnings = reconstruct_executions(session_dir)

    process_names = {
        execution.process_code: execution.process_name
        for execution in executions
    }

    segments, segment_warnings = reconstruct_gt_segments(
        session_dir,
        process_names,
    )

    link_warnings = attach_segments_and_infer_missing_ends(
        executions,
        segments,
        session_dir.name,
    )

    overlap_warnings = validate_segments(segments)

    manifest = load_json(session_dir / "gt_manifest.json")
    gt_records = load_jsonl(session_dir / "gt.jsonl")

    expected_boundaries = manifest.get("expected_boundaries", [])
    if not isinstance(expected_boundaries, list):
        expected_boundaries = []

    warnings = (
        execution_warnings
        + segment_warnings
        + link_warnings
        + overlap_warnings
    )

    inferred_end_count = sum(
        execution.end_source == "gt_log_inferred"
        for execution in executions
    )

    return {
        "session_id": session_dir.name,
        "session": manifest.get("session", {}),
        "executions": [asdict(execution) for execution in executions],
        "segments": [asdict(segment) for segment in segments],
        "expected_boundaries_count": len(expected_boundaries),
        "gt_log_record_count": len(gt_records),
        "warnings": warnings,
        "summary": {
            "process_types": len(
                {execution.process_code for execution in executions}
            ),
            "execution_count": len(executions),
            "segment_count": len(segments),
            "executions_missing_start": sum(
                execution.start is None
                for execution in executions
            ),
            "executions_missing_end_after_inference": sum(
                execution.end is None
                for execution in executions
            ),
            "execution_ends_inferred_from_gt_log": inferred_end_count,
            "execution_ends_from_manifest": sum(
                execution.end_source == "manifest"
                for execution in executions
            ),
            "process_codes": sorted(
                {execution.process_code for execution in executions}
            ),
        },
    }


def find_sessions(dataset_dir: Path) -> list[Path]:
    if not dataset_dir.exists():
        raise FileNotFoundError(
            f"Dataset directory not found: {dataset_dir}"
        )

    return sorted(
        path
        for path in dataset_dir.iterdir()
        if path.is_dir() and path.name.startswith("ses_")
    )


def build_dataset_ground_truth(
    dataset_dir: Path,
) -> dict[str, Any]:
    """Run the reconstruction across the complete Dataset A."""
    session_dirs = find_sessions(dataset_dir)

    sessions: list[dict[str, Any]] = []
    failed_sessions: list[dict[str, str]] = []

    distinct_process_codes: set[str] = set()

    totals = {
        "execution_count": 0,
        "segment_count": 0,
        "gt_log_records": 0,
        "execution_ends_inferred_from_gt_log": 0,
        "execution_ends_from_manifest": 0,
        "executions_still_missing_end": 0,
        "sessions_with_warnings": 0,
        "process_type_occurrences": 0,
    }

    for session_dir in session_dirs:
        try:
            result = build_session_result(session_dir)
        except Exception as exc:
            failed_sessions.append(
                {
                    "session_id": session_dir.name,
                    "error": str(exc),
                }
            )
            continue

        sessions.append(result)

        summary = result["summary"]

        totals["execution_count"] += summary["execution_count"]
        totals["segment_count"] += summary["segment_count"]
        totals["gt_log_records"] += result["gt_log_record_count"]
        totals["execution_ends_inferred_from_gt_log"] += (
            summary["execution_ends_inferred_from_gt_log"]
        )
        totals["execution_ends_from_manifest"] += (
            summary["execution_ends_from_manifest"]
        )
        totals["executions_still_missing_end"] += (
            summary["executions_missing_end_after_inference"]
        )
        totals["process_type_occurrences"] += summary["process_types"]

        distinct_process_codes.update(
            summary["process_codes"]
        )

        if result["warnings"]:
            totals["sessions_with_warnings"] += 1

    return {
        "schema_version": "ground_truth_reconstruction_v3",
        "dataset": "dataset_a",
        "dataset_path": str(dataset_dir),
        "sessions_found": len(session_dirs),
        "sessions_processed": len(sessions),
        "sessions_failed": len(failed_sessions),
        "distinct_process_codes": sorted(distinct_process_codes),
        "distinct_process_code_count": len(distinct_process_codes),
        "totals": totals,
        "failed_sessions": failed_sessions,
        "sessions": sessions,
    }


def build_single_session_output(
    dataset_dir: Path,
    session_dir: Path,
) -> dict[str, Any]:
    result = build_session_result(session_dir)
    distinct_codes = sorted(
        result["summary"]["process_codes"]
    )

    return {
        "schema_version": "ground_truth_reconstruction_v3",
        "dataset": "dataset_a",
        "dataset_path": str(dataset_dir),
        "sessions_found": 1,
        "sessions_processed": 1,
        "sessions_failed": 0,
        "distinct_process_codes": distinct_codes,
        "distinct_process_code_count": len(distinct_codes),
        "totals": {
            "execution_count": result["summary"]["execution_count"],
            "segment_count": result["summary"]["segment_count"],
            "gt_log_records": result["gt_log_record_count"],
            "execution_ends_inferred_from_gt_log": result[
                "summary"
            ]["execution_ends_inferred_from_gt_log"],
            "execution_ends_from_manifest": result[
                "summary"
            ]["execution_ends_from_manifest"],
            "executions_still_missing_end": result[
                "summary"
            ]["executions_missing_end_after_inference"],
            "sessions_with_warnings": int(
                bool(result["warnings"])
            ),
            "process_type_occurrences": result[
                "summary"
            ]["process_types"],
        },
        "failed_sessions": [],
        "sessions": [result],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build the Dataset A ground-truth reference. "
            "gt_manifest.json provides execution identity/metadata. "
            "gt.jsonl provides chronological process boundaries."
        )
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("data"),
    )
    parser.add_argument(
        "--session",
        default=None,
        help=(
            "Optional single session for debugging. "
            "Omit this to process all Dataset A sessions."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "outputs/dataset_a/ground_truth_all.json"
        ),
    )
    args = parser.parse_args()

    dataset_dir = (args.data_root / "dataset_a").resolve()

    if args.session:
        session_dir = dataset_dir / args.session

        if not session_dir.is_dir():
            raise SystemExit(
                f"Session not found: {session_dir}"
            )

        output = build_single_session_output(
            dataset_dir,
            session_dir,
        )
    else:
        output = build_dataset_ground_truth(dataset_dir)

    args.output.parent.mkdir(parents=True, exist_ok=True)

    # Preserve Japanese process names in the generated JSON.
    args.output.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    totals = output["totals"]

    print("=" * 100)
    print("GROUND-TRUTH RECONSTRUCTION")
    print("=" * 100)
    print(f"Dataset:                         {dataset_dir}")
    print(f"Sessions found:                  {output['sessions_found']}")
    print(f"Sessions processed:              {output['sessions_processed']}")
    print(f"Sessions failed:                 {output['sessions_failed']}")
    print(
        "Sessions with warnings:          "
        f"{totals['sessions_with_warnings']}"
    )
    print(
        "Distinct process codes:          "
        f"{output['distinct_process_code_count']}"
    )
    print(
        "Process-code occurrences:        "
        f"{totals['process_type_occurrences']}"
    )
    print(f"Total executions:                {totals['execution_count']}")
    print(f"Total GT segments:               {totals['segment_count']}")
    print(f"GT log records:                  {totals['gt_log_records']}")
    print(
        "Execution ends from manifest:    "
        f"{totals['execution_ends_from_manifest']}"
    )
    print(
        "Execution ends inferred:         "
        f"{totals['execution_ends_inferred_from_gt_log']}"
    )
    print(
        "Executions still missing end:   "
        f"{totals['executions_still_missing_end']}"
    )
    print(
        f"\nSaved UTF-8 JSON to:             "
        f"{args.output.resolve()}"
    )

    if output["failed_sessions"]:
        print("\nFailed sessions:")
        for failure in output["failed_sessions"]:
            print(
                f"  {failure['session_id']}: "
                f"{failure['error']}"
            )

    if output["sessions_processed"] != output["sessions_found"]:
        print(
            "\nWARNING: not all discovered sessions were processed."
        )


if __name__ == "__main__":
    main()
