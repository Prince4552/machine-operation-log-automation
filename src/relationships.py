#!/usr/bin/env python3
"""
Build transparent activity-to-activity relationship candidates.

Phase covered:
    relationship features
     candidate generation without all-pairs comparison
     first rule-based relationship score

Input:
    JSONL activity records produced by the frozen activities_v4 pipeline.

Output:
    JSONL relationship records plus a compact summary JSON.

The script is intentionally deterministic and uses only standard-library Python.
It does not assign activities to processes yet. That comes after we inspect this
relationship layer and add the constrained grouping stage.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REQUIRED_ACTIVITY_FIELDS = {
    "activity_id",
    "session_id",
    "start",
    "end",
    "type",
    "app",
    "window",
    "browser_tab",
    "browser_url",
    "text",
    "screen_text",
    "entities",
    "source_event_ids",
    "triggered_by",
}

# These entity types are useful enough to act as "same object" evidence.
# Generic NUMBER_CANDIDATE values are deliberately excluded because they can
# create many false links (dates, counts, ports, etc.).
LINKABLE_ENTITY_TYPES = {
    "INVOICE_ID",
    "EMPLOYEE_ID",
    "CASE_ID",
    "DOCUMENT_ID",
    "CUSTOMER_ID",
    "ID_CANDIDATE",
    "EMAIL",
    "FILENAME",
}

# URLs are only linkable when they look like an object/page URL rather than a
# generic root URL. Local/dev URLs are already filtered by activities_v4.
URL_PATH_MARKERS = ("/", "?", "#")

# Candidate-generation limits. They are deliberately conservative so the
# script does not become an accidental all-pairs algorithm.
NEAR_TIME_SECONDS = 45.0
ENTITY_NEIGHBORS = 5
NEAR_NEIGHBORS = 20
MAX_ENTITY_GROUP = 200

# Relationship score from the agreed first hypothesis.
WEIGHTS = {
    "same_entity": 5,
    "triggered_by": 5,
    "same_window": 2,
    "same_app": 2,
    "same_browser_tab": 1,
    "semantic_match": 1,
    "close_in_time": 1,
    "large_time_gap": -1,
}

CLOSE_TIME_SECONDS = 30.0
LARGE_TIME_GAP_SECONDS = 120.0


# ---------------------------------------------------------------------------
# Basic normalization / parsing
# ---------------------------------------------------------------------------

def normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = unicodedata.normalize("NFKC", value).strip()
    return value.casefold()


def parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid timestamp: {value!r}")

    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError(f"Timestamp must contain timezone information: {value!r}")
    return dt


def safe_string(value: Any) -> str:
    return value if isinstance(value, str) else ""


# ---------------------------------------------------------------------------
# Activity validation
# ---------------------------------------------------------------------------

def load_activities(path: Path) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    if not path.exists():
        raise FileNotFoundError(f"Activity file not found: {path}")

    activities: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON in {path} at line {line_no}: {exc}"
                ) from exc

            if not isinstance(record, dict):
                raise ValueError(
                    f"Activity line {line_no} is not a JSON object."
                )

            missing = REQUIRED_ACTIVITY_FIELDS - set(record)
            if missing:
                raise ValueError(
                    f"Activity line {line_no} is missing fields: "
                    f"{sorted(missing)}"
                )

            activity_id = record["activity_id"]
            session_id = record["session_id"]

            if not isinstance(activity_id, str) or not activity_id:
                raise ValueError(
                    f"Activity line {line_no}: activity_id must be a non-empty string."
                )
            if not isinstance(session_id, str) or not session_id:
                raise ValueError(
                    f"Activity line {line_no}: session_id must be a non-empty string."
                )
            if activity_id in seen_ids:
                raise ValueError(f"Duplicate activity_id: {activity_id}")

            start = parse_timestamp(record["start"])
            end = parse_timestamp(record["end"])
            if end < start:
                raise ValueError(
                    f"Activity {activity_id}: end is before start."
                )

            if not isinstance(record["entities"], list):
                raise ValueError(
                    f"Activity {activity_id}: entities must be a list."
                )
            if not isinstance(record["source_event_ids"], list):
                raise ValueError(
                    f"Activity {activity_id}: source_event_ids must be a list."
                )
            if not isinstance(record["triggered_by"], list):
                raise ValueError(
                    f"Activity {activity_id}: triggered_by must be a list."
                )

            record["_start_dt"] = start
            record["_end_dt"] = end
            record["_start_ts"] = start.timestamp()
            record["_end_ts"] = end.timestamp()

            seen_ids.add(activity_id)
            activities.append(record)

    if not activities:
        raise ValueError("Activity file contains no activities.")

    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for activity in activities:
        by_session[activity["session_id"]].append(activity)

    for session_id, items in by_session.items():
        items.sort(key=lambda a: (a["_start_dt"], a["_end_dt"], a["activity_id"]))

        # Activities may have overlapping intervals, so we only check ordering
        # of their start times here. Overlap itself is not an error.
        for previous, current in zip(items, items[1:]):
            if current["_start_dt"] < previous["_start_dt"]:
                raise AssertionError(
                    f"Internal sorting failure in session {session_id}."
                )

    return activities, dict(by_session)


# ---------------------------------------------------------------------------
# Entity handling
# ---------------------------------------------------------------------------

def entity_key(entity: Any) -> tuple[str, str] | None:
    if not isinstance(entity, dict):
        return None

    entity_type = entity.get("type")
    value = entity.get("value")

    if not isinstance(entity_type, str) or not isinstance(value, str):
        return None

    entity_type = entity_type.strip().upper()
    value_norm = normalize_text(value)

    if not entity_type or not value_norm:
        return None

    if entity_type in LINKABLE_ENTITY_TYPES:
        return (entity_type, value_norm)

    if entity_type == "URL":
        # Only retain URL values that look like a meaningful page/object URL.
        # A generic root URL is too weak as an entity identity.
        if "/" not in value_norm.split("://", 1)[-1]:
            return None
        return (entity_type, value_norm)

    return None


def activity_entities(activity: dict[str, Any]) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for entity in activity.get("entities", []):
        key = entity_key(entity)
        if key is not None:
            result.add(key)
    return result


# ---------------------------------------------------------------------------
# Context / relationship features
# ---------------------------------------------------------------------------

def direct_trigger_link(a: dict[str, Any], b: dict[str, Any]) -> bool:
    a_event_ids = {
        str(value) for value in a.get("source_event_ids", []) if isinstance(value, str)
    }
    b_event_ids = {
        str(value) for value in b.get("source_event_ids", []) if isinstance(value, str)
    }

    a_triggers = {
        str(value) for value in a.get("triggered_by", []) if isinstance(value, str)
    }
    b_triggers = {
        str(value) for value in b.get("triggered_by", []) if isinstance(value, str)
    }

    # Support both orientations and either event-id or activity-id references.
    return bool(
        a_triggers.intersection(b_event_ids)
        or b_triggers.intersection(a_event_ids)
        or a_triggers.intersection({str(b["activity_id"])})
        or b_triggers.intersection({str(a["activity_id"])})
    )


def semantic_match(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """
    Very conservative semantic proxy for T0.

    We only mark semantic_match when one meaningful activity text is a
    substring of the other after Unicode/case normalization. This is
    intentionally weak (+1 only); no embedding model is introduced yet.
    """
    a_text = normalize_text(a.get("text"))
    b_text = normalize_text(b.get("text"))

    if len(a_text) < 4 or len(b_text) < 4:
        return False

    return a_text in b_text or b_text in a_text


def relation_features(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    a_entities = activity_entities(a)
    b_entities = activity_entities(b)
    shared_entities = sorted(a_entities.intersection(b_entities))

    same_entity = bool(shared_entities)
    triggered_by = direct_trigger_link(a, b)

    same_app = bool(
        normalize_text(a.get("app"))
        and normalize_text(a.get("app")) == normalize_text(b.get("app"))
    )

    same_window = bool(
        normalize_text(a.get("window"))
        and normalize_text(a.get("window")) == normalize_text(b.get("window"))
    )

    same_browser_tab = bool(
        normalize_text(a.get("browser_tab"))
        and normalize_text(a.get("browser_tab"))
        == normalize_text(b.get("browser_tab"))
    )

    a_start = a["_start_ts"]
    b_start = b["_start_ts"]
    delta_seconds = abs(b_start - a_start)

    close_in_time = delta_seconds <= CLOSE_TIME_SECONDS
    large_time_gap = delta_seconds > LARGE_TIME_GAP_SECONDS

    features = {
        "same_entity": same_entity,
        "shared_entities": [
            {"type": entity_type, "value": value}
            for entity_type, value in shared_entities
        ],
        "triggered_by": triggered_by,
        "same_app": same_app,
        "same_window": same_window,
        "same_browser_tab": same_browser_tab,
        "close_in_time": close_in_time,
        "large_time_gap": large_time_gap,
        "delta_seconds": delta_seconds,
        "semantic_match": semantic_match(a, b),
    }

    score = 0
    score += WEIGHTS["same_entity"] if same_entity else 0
    score += WEIGHTS["triggered_by"] if triggered_by else 0
    score += WEIGHTS["same_window"] if same_window else 0
    score += WEIGHTS["same_app"] if same_app else 0
    score += WEIGHTS["same_browser_tab"] if same_browser_tab else 0
    score += WEIGHTS["semantic_match"] if features["semantic_match"] else 0
    score += WEIGHTS["close_in_time"] if close_in_time else 0
    score += WEIGHTS["large_time_gap"] if large_time_gap else 0

    if triggered_by or same_entity:
        strength = "STRONG"
    elif score >= 3:
        strength = "MODERATE"
    else:
        strength = "WEAK"

    evidence: list[str] = []
    if same_entity:
        evidence.append("same_entity")
    if triggered_by:
        evidence.append("triggered_by")
    if same_window:
        evidence.append("same_window")
    if same_app:
        evidence.append("same_app")
    if same_browser_tab:
        evidence.append("same_browser_tab")
    if features["semantic_match"]:
        evidence.append("semantic_match")
    if close_in_time:
        evidence.append("close_in_time")
    if large_time_gap:
        evidence.append("large_time_gap")

    features["score"] = score
    features["strength"] = strength
    features["evidence"] = evidence

    return features


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------

def add_pair(
    candidates: dict[tuple[int, int], set[str]],
    i: int,
    j: int,
    reason: str,
) -> None:
    if i == j:
        return
    left, right = sorted((i, j))
    candidates.setdefault((left, right), set()).add(reason)


def generate_candidates(
    session_activities: list[dict[str, Any]],
) -> dict[tuple[int, int], set[str]]:
    """
    Generate only plausible candidate pairs.

    Sources:
      1. nearby temporal neighbors
      2. shared strong entity
      3. explicit triggered_by linkage
    """
    n = len(session_activities)
    candidates: dict[tuple[int, int], set[str]] = {}

    # 1) Nearby activities: at most NEAR_NEIGHBORS forward neighbors and only
    # when the timestamps are within NEAR_TIME_SECONDS.
    for i in range(n):
        a = session_activities[i]
        checked = 0

        for j in range(i + 1, n):
            if checked >= NEAR_NEIGHBORS:
                break

            b = session_activities[j]
            delta = b["_start_ts"] - a["_start_ts"]

            if delta > NEAR_TIME_SECONDS:
                break

            add_pair(candidates, i, j, "nearby")
            checked += 1

    # 2) Shared entities: build an inverted index, then connect only a small
    # neighborhood around each activity in entity order. Huge entity groups are
    # not expanded into all-pairs.
    entity_to_indices: dict[tuple[str, str], list[int]] = defaultdict(list)

    for index, activity in enumerate(session_activities):
        for key in activity_entities(activity):
            entity_to_indices[key].append(index)

    for key, indices in entity_to_indices.items():
        if len(indices) > MAX_ENTITY_GROUP:
            # A huge entity group is probably a generic application/document
            # context rather than a useful case-specific identity. Skip it
            # rather than creating a combinatorial explosion.
            continue

        for pos, i in enumerate(indices):
            lower = max(0, pos - ENTITY_NEIGHBORS)
            upper = min(len(indices), pos + ENTITY_NEIGHBORS + 1)

            for q in range(lower, upper):
                if q == pos:
                    continue
                add_pair(candidates, i, indices[q], "shared_entity")

    # 3) Explicit trigger/cause links.
    source_to_indices: dict[str, list[int]] = defaultdict(list)
    activity_id_to_index: dict[str, int] = {}

    for index, activity in enumerate(session_activities):
        activity_id_to_index[activity["activity_id"]] = index

        for event_id in activity.get("source_event_ids", []):
            if isinstance(event_id, str):
                source_to_indices[event_id].append(index)

    for index, activity in enumerate(session_activities):
        for trigger in activity.get("triggered_by", []):
            if not isinstance(trigger, str):
                continue

            if trigger in activity_id_to_index:
                add_pair(
                    candidates,
                    index,
                    activity_id_to_index[trigger],
                    "triggered_by",
                )

            for other_index in source_to_indices.get(trigger, []):
                add_pair(candidates, index, other_index, "triggered_by")

    return candidates


# ---------------------------------------------------------------------------
# Build relationship output
# ---------------------------------------------------------------------------

def build_relationships(
    by_session: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], Counter[str], Counter[str]]:
    relationships: list[dict[str, Any]] = []
    candidate_reason_counts: Counter[str] = Counter()
    strength_counts: Counter[str] = Counter()

    for session_id, activities in sorted(by_session.items()):
        candidates = generate_candidates(activities)

        for (left_index, right_index), reasons in sorted(candidates.items()):
            a = activities[left_index]
            b = activities[right_index]

            features = relation_features(a, b)

            record = {
                "session_id": session_id,
                "activity_a": a["activity_id"],
                "activity_b": b["activity_id"],
                "candidate_reasons": sorted(reasons),
                "features": features,
            }

            relationships.append(record)

            for reason in reasons:
                candidate_reason_counts[reason] += 1
            strength_counts[features["strength"]] += 1

    return relationships, candidate_reason_counts, strength_counts


# ---------------------------------------------------------------------------
# Self-checks
# ---------------------------------------------------------------------------

def self_check(
    activities: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
) -> None:
    activity_ids = {a["activity_id"] for a in activities}

    seen_pairs: set[tuple[str, str]] = set()

    for relation in relationships:
        a = relation["activity_a"]
        b = relation["activity_b"]

        if a not in activity_ids or b not in activity_ids:
            raise AssertionError("Relationship references an unknown activity.")

        if a == b:
            raise AssertionError("Self-relationship detected.")

        pair = tuple(sorted((a, b)))
        if pair in seen_pairs:
            raise AssertionError(f"Duplicate relationship pair detected: {pair}")
        seen_pairs.add(pair)

        features = relation["features"]
        if not isinstance(features.get("score"), int):
            raise AssertionError("Relationship score is not an integer.")
        if not math.isfinite(float(features.get("delta_seconds", 0.0))):
            raise AssertionError("Non-finite time gap detected.")

        evidence = features.get("evidence")
        if not isinstance(evidence, list):
            raise AssertionError("Evidence is not a list.")

    # Every strong entity/trigger pair should be present because those are
    # explicit candidate sources. This protects us from accidentally removing
    # the highest-value edges during future edits.
    for relation in relationships:
        features = relation["features"]
        if features["same_entity"] or features["triggered_by"]:
            if not (
                "shared_entity" in relation["candidate_reasons"]
                or "triggered_by" in relation["candidate_reasons"]
            ):
                raise AssertionError(
                    "Strong relationship missing its corresponding candidate reason."
                )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_summary(
    path: Path,
    activities: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    by_session: dict[str, list[dict[str, Any]]],
    candidate_reason_counts: Counter[str],
    strength_counts: Counter[str],
) -> None:
    total_candidates = len(relationships)
    strong = sum(
        1 for relation in relationships
        if relation["features"]["strength"] == "STRONG"
    )
    moderate = sum(
        1 for relation in relationships
        if relation["features"]["strength"] == "MODERATE"
    )
    weak = sum(
        1 for relation in relationships
        if relation["features"]["strength"] == "WEAK"
    )

    summary = {
        "sessions": len(by_session),
        "activities": len(activities),
        "candidate_relationships": total_candidates,
        "candidate_reasons": dict(sorted(candidate_reason_counts.items())),
        "strength_counts": {
            "STRONG": strong,
            "MODERATE": moderate,
            "WEAK": weak,
        },
        "score_hypothesis": WEIGHTS,
        "parameters": {
            "near_time_seconds": NEAR_TIME_SECONDS,
            "near_neighbors": NEAR_NEIGHBORS,
            "entity_neighbors": ENTITY_NEIGHBORS,
            "max_entity_group": MAX_ENTITY_GROUP,
            "close_time_seconds": CLOSE_TIME_SECONDS,
            "large_time_gap_seconds": LARGE_TIME_GAP_SECONDS,
        },
        "self_check": "PASS",
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build transparent activity relationship candidates."
    )
    parser.add_argument(
        "--activities",
        required=True,
        type=Path,
        help="Activity JSONL produced by activities_v4.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Relationship JSONL output path.",
    )
    parser.add_argument(
        "--summary",
        required=True,
        type=Path,
        help="Relationship summary JSON output path.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        activities, by_session = load_activities(args.activities)

        relationships, candidate_reason_counts, strength_counts = build_relationships(
            by_session
        )

        self_check(activities, relationships)

        write_jsonl(args.output, relationships)
        write_summary(
            args.summary,
            activities,
            relationships,
            by_session,
            candidate_reason_counts,
            strength_counts,
        )

    except (OSError, ValueError, AssertionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("RELATIONSHIP LAYER")
    print("=" * 64)
    print(f"Sessions:                 {len(by_session)}")
    print(f"Activities:               {len(activities)}")
    print(f"Candidate relationships:  {len(relationships)}")

    print()
    print("Candidate reasons:")
    for key, value in sorted(candidate_reason_counts.items()):
        print(f"  {key:<18} {value:>8}")

    print()
    print("Relationship strength:")
    for key in ("STRONG", "MODERATE", "WEAK"):
        print(f"  {key:<18} {strength_counts.get(key, 0):>8}")

    print()
    print("Self-check: PASS")
    print(f"Wrote relationships: {args.output.resolve()}")
    print(f"Wrote summary:       {args.summary.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
