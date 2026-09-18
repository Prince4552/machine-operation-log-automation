"""
src/activities.py

Revision v3: separates passive OCR from targeted value checkpoints, avoids
empty unknown-paste runs, and strengthens the recorder-specific shortcut
echo rule using the observed adjacent 1-10 ms pattern.

Converts low-level desktop-agent operation events (Dataset A / Dataset B,
events.jsonl) into higher-level atomic activities (activities.jsonl).

Architecture (see accompanying write-up for full reasoning):

    Phase A  normalize_events()      raw events -> logical Operations
    Phase B  TextRunEngine           Operations -> text-buffer state
    Phase C  reconcile_checkpoints() buffer vs browser/OCR evidence
    Phase D  build_activities()      Operations -> grouped Activity dicts

Real-data refinement: text_input_complete.related_keystrokes is treated as
strong provenance evidence for the semantic keystrokes in a text-input
episode. Paired raw printable events outside that related set are filtered
as recorder echoes. Timing is used only to pair the echo with its already
identified semantic event; it is not used to decide whether repeated
characters are real.

Design principle: NEVER use "same character within N ms => duplicate,
delete it" logic. The distinguishing signal for recorder echo artifacts is
structural (a command-modifier keystroke transitions to an unmodified
release event for the SAME key), not temporal proximity. Real repeated
keystrokes never carry that modifier transition, so this approach does not
confuse "OO" (two real Os) with an echoed "O" (one real O plus a recorder
artifact). Timing is used only as a last-resort tie-breaker when no
`correlation.triggered_by` link is present, and is logged as such.

This module is deterministic: given the same input events, it always
produces the same output. It performs no I/O other than reading the
requested events.jsonl files and writing the requested output file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


@dataclass
class Config:
    # A run of text-domain operations is split if the gap since the last
    # one exceeds this many milliseconds. This is a guess pending real-data
    # validation -- see the write-up.
    inactivity_gap_ms: int = 30_000

    # Legacy fallback threshold for modifier-based echo detection when a
    # text_input_complete linkage is not available.
    echo_structural_max_gap_ms: int = 50

    # Evidence-backed threshold used ONLY to pair a related keystroke with
    # its immediately following recorder echo inside a text_input_complete
    # episode. We observed 1-5 ms gaps in the real session inspected during
    # development, so 10 ms leaves a little headroom without becoming a
    # generic duplicate-character heuristic.
    linked_echo_max_gap_ms: int = 10

    # Digit-only tokens shorter than this are not considered
    # NUMBER_CANDIDATE entities (too likely to be noise: counts, indices).
    min_number_candidate_digits: int = 4

    # Passive evidence arriving shortly after a text run closes may still be
    # a checkpoint for that just-finished text field. This is intentionally
    # bounded; it is not a generic temporal grouping rule.
    recent_evidence_window_ms: int = 2500


# --------------------------------------------------------------------------
# Small dict/access helpers (defensive against missing fields throughout)
# --------------------------------------------------------------------------


def g(d: Optional[dict], *path, default=None):
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur if cur is not None else default


def payload_get(e: dict, *path, default=None):
    return g(e, "payload", *path, default=default)


def context_get(e: dict, *path, default=None):
    return g(e, "context", *path, default=default)


def corr_get(e: dict, *path, default=None):
    return g(e, "correlation", *path, default=default)


# --------------------------------------------------------------------------
# Tracer -- shared hook used by both activities.py (silent) and
# debug_text_reconstruction.py (verbose). Keeping this shared is what
# guarantees the debug tool shows exactly what the extractor actually did,
# not a re-implementation that could drift from it.
# --------------------------------------------------------------------------


class Tracer:
    """No-op base tracer. debug_text_reconstruction.py supplies a verbose
    subclass; activities.py runs with this one."""

    def raw_event(self, e: dict) -> None:
        pass

    def operation(self, op: "Operation") -> None:
        pass

    def text_state(self, run_key, buffer_text: str, cursor: int, selection) -> None:
        pass

    def checkpoint(self, label: str, value) -> None:
        pass

    def decision(self, event_id: str, decision: str, reason: str) -> None:
        pass


# --------------------------------------------------------------------------
# Key / modifier normalization
# --------------------------------------------------------------------------

_KEY_ALIASES = {
    "backspace": "backspace",
    "delete": "delete",
    "del": "delete",
    "left": "left",
    "arrowleft": "left",
    "right": "right",
    "arrowright": "right",
    "up": "up",
    "arrowup": "up",
    "down": "down",
    "arrowdown": "down",
    "home": "home",
    "end": "end",
    "enter": "enter",
    "return": "enter",
    "tab": "tab",
    "escape": "escape",
    "esc": "escape",
}

# Bare modifier-only keypresses that carry no character and should never
# themselves become operations.
_BARE_MODIFIER_KEYS = {"control", "ctrl", "shift", "alt", "win", "meta", "command"}


def normalize_key_name(raw_key: Optional[str]) -> Optional[str]:
    if not raw_key:
        return None
    low = raw_key.strip().lower()
    if low in _KEY_ALIASES:
        return _KEY_ALIASES[low]
    if low in _BARE_MODIFIER_KEYS:
        return None
    # Single printable character keys: normalize to lowercase for combo
    # matching, but the ORIGINAL character (with case) is what matters for
    # INSERT -- callers use payload.character for that, not this.
    if len(low) == 1:
        return low
    return low  # leave other named keys (e.g. "f5") as-is, lowercase


def get_modifiers(e: dict) -> Dict[str, bool]:
    mods = payload_get(e, "modifiers", default={}) or {}
    return {
        "ctrl": bool(mods.get("ctrl")),
        "alt": bool(mods.get("alt")),
        "shift": bool(mods.get("shift")),
        "win": bool(mods.get("win")),
    }


def command_modifier_active(mods: Dict[str, bool]) -> bool:
    """ctrl/alt/win are treated as 'command' modifiers that can never
    produce literal text. shift is excluded here -- shift+letter is normal
    text input (produces the shifted character), handled separately."""
    return bool(mods.get("ctrl") or mods.get("alt") or mods.get("win"))


def shift_only(mods: Dict[str, bool]) -> bool:
    return bool(mods.get("shift")) and not command_modifier_active(mods)


def active_modifier_names(mods: Dict[str, bool]) -> List[str]:
    return sorted(name for name in ("ctrl", "alt", "shift", "win") if mods.get(name))


# --------------------------------------------------------------------------
# Combo -> logical operation mapping
# --------------------------------------------------------------------------

_COMBO_MAP = {
    ("ctrl", "a"): "SELECT_ALL",
    ("ctrl", "c"): "COPY",
    ("ctrl", "x"): "CUT",
    ("ctrl", "v"): "PASTE",
    ("ctrl", "z"): "UNDO",
    ("ctrl", "y"): "REDO",
    ("ctrl", "shift", "z"): "REDO",
    ("ctrl", "backspace"): "DELETE_WORD_BACK",
    ("ctrl", "left"): "MOVE_WORD_LEFT",
    ("ctrl", "right"): "MOVE_WORD_RIGHT",
}

# Ops that mutate the text buffer (used to decide when to push undo state).
_MUTATING_OPS = {
    "INSERT",
    "BACKSPACE",
    "DELETE",
    "DELETE_WORD_BACK",
    "PASTE",
    "CUT",
}

# Ops that belong to the text-editing domain and therefore open/extend a
# TEXT_ENTRY run (as opposed to standalone CLICK/COPY/PASTE activities
# raised when there is no run context -- see build_activities()).
_TEXT_DOMAIN_OPS = {
    "INSERT",
    "BACKSPACE",
    "DELETE",
    "DELETE_WORD_BACK",
    "MOVE_LEFT",
    "MOVE_RIGHT",
    "MOVE_UP",
    "MOVE_DOWN",
    "MOVE_HOME",
    "MOVE_END",
    "MOVE_WORD_LEFT",
    "MOVE_WORD_RIGHT",
    "SELECT_ALL",
    "COPY",
    "CUT",
    "PASTE",
    "UNDO",
    "REDO",
}

# These operations actually change the text buffer. A new TEXT_ENTRY run
# may start from one of these. Pure caret/selection/clipboard controls do not
# create a text activity from an empty state.
_TEXT_MUTATING_OPS = {
    "INSERT",
    "BACKSPACE",
    "DELETE",
    "DELETE_WORD_BACK",
    "CUT",
    "PASTE",
}

_MOVE_OPS = {
    "left": "MOVE_LEFT",
    "right": "MOVE_RIGHT",
    "up": "MOVE_UP",
    "down": "MOVE_DOWN",
    "home": "MOVE_HOME",
    "end": "MOVE_END",
}


# --------------------------------------------------------------------------
# Operation
# --------------------------------------------------------------------------


@dataclass
class Operation:
    op_type: str
    char: Optional[str] = None
    extend_selection: bool = False
    timestamp_ms: int = 0
    timestamp_iso: str = ""
    source_event_ids: List[str] = field(default_factory=list)
    raw_event_types: List[str] = field(default_factory=list)
    context_snapshot: dict = field(default_factory=dict)
    raw_event: Optional[dict] = None  # the primary originating raw event
    combo_label: Optional[str] = None  # for SHORTCUT ops
    payload: dict = field(default_factory=dict)  # for non-keystroke ops


def _extracted_text_value(value) -> Optional[str]:
    """Return the actual text string from context.extracted_text.

    Real events may store extracted_text as either a string or a small
    metadata object such as {"text": "...", "source": "..."}. The
    downstream reconciliation/entity logic needs the text itself, not the
    wrapper object.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        value = value.get("text")
        return value if isinstance(value, str) else None
    return None


def _target_signature_from_event(e: dict) -> tuple:
    return _target_signature({
        "app_name": context_get(e, "active_app", "app_name"),
        "window_title": context_get(e, "active_app", "window_title"),
        "target_field": payload_get(e, "target_field"),
    })


def _context_snapshot(e: dict) -> dict:
    return {
        "app_name": context_get(e, "active_app", "app_name"),
        "process_name": context_get(e, "active_app", "process_name"),
        "window_title": context_get(e, "active_app", "window_title"),
        "browser_url": context_get(e, "active_browser_tab", "url"),
        "browser_title": context_get(e, "active_browser_tab", "title"),
        "target_field": payload_get(e, "target_field"),
        "extracted_text": _extracted_text_value(context_get(e, "extracted_text")),
    }


# --------------------------------------------------------------------------
# Phase A -- normalize raw events into logical Operations
# --------------------------------------------------------------------------


def _echo_decision(cand: dict, consumed: List[dict], config: Config, tracer: Tracer) -> Tuple[bool, str]:
    """Decide whether `cand` (a trailing unmodified keystroke matching the
    key of a preceding command-modifier keystroke) is a recorder release
    echo that should be consumed (not inserted as text), or an independent
    real keystroke that should be kept.

    Correlation.triggered_by, when present, is authoritative. Only when it
    is absent do we fall back to a structural check (modifier transition +
    sequence adjacency + small gap) -- never a bare "close in time" rule.
    """
    consumed_ids = {c.get("event_id") for c in consumed}
    triggered_by = corr_get(cand, "triggered_by")
    if triggered_by:
        if triggered_by in consumed_ids:
            return True, "correlation.triggered_by links this event to the preceding shortcut sequence"
        # In the inspected real session, the recorder sometimes points the
        # unmodified release event at another correlation record even though
        # it is still the immediate modifier-release echo. Since the caller
        # already required same key + opposite modifier state, an adjacent
        # sequence within the observed 10 ms recorder echo envelope is strong
        # structural evidence.
        prev = consumed[-1]
        gap = cand.get("timestamp_ms", 0) - prev.get("timestamp_ms", 0)
        seq_prev = corr_get(prev, "sequence_number")
        seq_cand = corr_get(cand, "sequence_number")
        adjacent = seq_prev is None or seq_cand is None or seq_cand == seq_prev + 1
        if gap >= 0 and gap <= config.linked_echo_max_gap_ms and adjacent:
            return True, (
                "explicit link points elsewhere, but same-key modifier-release pattern "
                "is sequence-adjacent inside the observed recorder echo envelope"
            )
        return False, "correlation.triggered_by points elsewhere and structural echo envelope not met"

    prev = consumed[-1]
    gap = corr_get(cand, "ms_since_last_event")
    if gap is None:
        try:
            gap = cand.get("timestamp_ms", 0) - prev.get("timestamp_ms", 0)
        except TypeError:
            gap = None

    seq_prev = corr_get(prev, "sequence_number")
    seq_cand = corr_get(cand, "sequence_number")
    adjacent = seq_prev is None or seq_cand is None or seq_cand == seq_prev + 1

    if gap is not None and gap <= config.echo_structural_max_gap_ms and adjacent:
        return True, (
            f"no correlation.triggered_by present; structural fallback accepted "
            f"(modifier-release pattern, {gap}ms gap, sequence-adjacent)"
        )
    return False, "no correlation link and structural fallback threshold not met; kept as independent keystroke"


def _build_general_command_echo_index(events: List[dict], config: Config) -> set:
    """Return raw keystroke IDs that are strongly identifiable as recorder
    release echoes of command-modifier shortcuts.

    Observed real-data pattern:
        ctrl/alt/win + KEY -> optional shortcut metadata event(s) ->
        same KEY with no command modifier, a few milliseconds later.

    This is structural, not a generic duplicate-character rule. The match
    requires the modifier transition, same key, same target/context, and
    immediate raw-stream adjacency apart from recorder shortcut metadata.
    """
    echo_ids: set = set()
    n = len(events)
    i = 0
    while i < n:
        e = events[i]
        if e.get("event_type") != "keystroke":
            i += 1
            continue

        mods = get_modifiers(e)
        if not command_modifier_active(mods):
            i += 1
            continue

        key = normalize_key_name(payload_get(e, "key")) or (payload_get(e, "character") or "").lower()
        if not key:
            i += 1
            continue

        # Walk over recorder shortcut metadata events only.
        j = i + 1
        while j < n and events[j].get("event_type") == "shortcut":
            j += 1

        if j < n and events[j].get("event_type") == "keystroke":
            cand = events[j]
            cand_mods = get_modifiers(cand)
            cand_key = normalize_key_name(payload_get(cand, "key")) or (payload_get(cand, "character") or "").lower()
            same_target = _target_signature_from_event(e) == _target_signature_from_event(cand)
            try:
                gap = int(cand.get("timestamp_ms", 0) or 0) - int(e.get("timestamp_ms", 0) or 0)
            except (TypeError, ValueError):
                gap = 10**9

            seq_e = corr_get(e, "sequence_number")
            seq_c = corr_get(cand, "sequence_number")
            seq_ok = (seq_e is None or seq_c is None or seq_c >= seq_e + 1)

            if (
                cand_key == key
                and not command_modifier_active(cand_mods)
                and same_target
                and 0 <= gap <= config.linked_echo_max_gap_ms
                and seq_ok
            ):
                cid = cand.get("event_id")
                if cid:
                    echo_ids.add(cid)

        i += 1

    return echo_ids


def _resolve_command_combo(
    events: List[dict], i: int, config: Config, tracer: Tracer
) -> Tuple[Tuple[str, ...], List[dict], int]:
    e = events[i]
    mods = get_modifiers(e)
    key = normalize_key_name(payload_get(e, "key")) or (payload_get(e, "character") or "").lower()
    combo = tuple(sorted(active_modifier_names(mods)) + ([key] if key else []))
    consumed = [e]
    j = i + 1
    n = len(events)

    # Consume any recorder shortcut metadata immediately following the
    # modified keystroke before checking for the release echo.
    while j < n and events[j].get("event_type") == "shortcut":
        consumed.append(events[j])
        j += 1

    if j < n and events[j].get("event_type") == "keystroke":
        cand = events[j]
        cand_mods = get_modifiers(cand)
        cand_key = normalize_key_name(payload_get(cand, "key")) or (payload_get(cand, "character") or "").lower()
        same_target = _target_signature_from_event(e) == _target_signature_from_event(cand)
        try:
            gap_from_primary = int(cand.get("timestamp_ms", 0) or 0) - int(e.get("timestamp_ms", 0) or 0)
        except (TypeError, ValueError):
            gap_from_primary = 10**9

        if (
            cand_key == key
            and not command_modifier_active(cand_mods)
            and same_target
            and 0 <= gap_from_primary <= config.linked_echo_max_gap_ms
        ):
            consume, reason = _echo_decision(cand, consumed, config, tracer)
            # The structural precondition above is stronger than the
            # correlation field: same key, modifier transition, same target,
            # optional recorder metadata, and a tiny observed envelope.
            if consume or gap_from_primary <= config.linked_echo_max_gap_ms:
                consumed.append(cand)
                j += 1
                tracer.decision(cand.get("event_id", "?"), "consumed_as_release_echo", reason)
            else:
                tracer.decision(cand.get("event_id", "?"), "kept_as_literal_keystroke", reason)

    return combo, consumed, j


def _resolve_shift_echo(events: List[dict], i: int, config: Config, tracer: Tracer) -> Tuple[List[dict], int]:
    """Mirrors _resolve_command_combo for the shift-only echo pattern
    described in the spec (e.g. 'Shift+N' followed by a redundant 'n')."""
    e = events[i]
    key = normalize_key_name(payload_get(e, "key"))
    consumed = [e]
    j = i + 1
    n = len(events)
    if j < n and events[j].get("event_type") == "keystroke":
        cand = events[j]
        cand_mods = get_modifiers(cand)
        cand_key = normalize_key_name(payload_get(cand, "key"))
        if cand_key == key and not cand_mods.get("shift") and not command_modifier_active(cand_mods):
            consume, reason = _echo_decision(cand, consumed, config, tracer)
            if consume:
                consumed.append(cand)
                j += 1
                tracer.decision(cand.get("event_id", "?"), "consumed_as_shift_release_echo", reason)
            else:
                tracer.decision(cand.get("event_id", "?"), "kept_as_literal_keystroke", reason)
    return consumed, j


def _combo_to_operation(combo: Tuple[str, ...], consumed: List[dict]) -> Operation:
    primary = consumed[0]
    op_type = _COMBO_MAP.get(combo)
    label = "+".join(combo)
    if op_type is None:
        op_type = "SHORTCUT"
    return Operation(
        op_type=op_type,
        combo_label=label,
        timestamp_ms=primary.get("timestamp_ms", 0),
        timestamp_iso=primary.get("timestamp_iso", ""),
        source_event_ids=[c.get("event_id") for c in consumed if c.get("event_id")],
        raw_event_types=[c.get("event_type") for c in consumed],
        context_snapshot=_context_snapshot(primary),
        raw_event=primary,
    )


def _keystroke_to_operation(consumed: List[dict], mods: Dict[str, bool]) -> Optional[Operation]:
    primary = consumed[0]
    key = normalize_key_name(payload_get(primary, "key"))
    char = payload_get(primary, "character")

    base = dict(
        timestamp_ms=primary.get("timestamp_ms", 0),
        timestamp_iso=primary.get("timestamp_iso", ""),
        source_event_ids=[c.get("event_id") for c in consumed if c.get("event_id")],
        raw_event_types=[c.get("event_type") for c in consumed],
        context_snapshot=_context_snapshot(primary),
        raw_event=primary,
    )

    if key in _MOVE_OPS:
        return Operation(op_type=_MOVE_OPS[key], extend_selection=bool(mods.get("shift")), **base)
    if key in ("backspace", "delete", "enter", "tab", "escape"):
        return Operation(op_type=key.upper(), **base)
    if char and len(char) == 1 and char.isprintable():
        return Operation(op_type="INSERT", char=char, **base)
    return None  # bare/unmapped key with no textual or structural effect


def _non_keystroke_to_operation(e: dict) -> Optional[Operation]:
    et = e.get("event_type")
    layer = e.get("layer")
    base = dict(
        timestamp_ms=e.get("timestamp_ms", 0),
        timestamp_iso=e.get("timestamp_iso", ""),
        source_event_ids=[e.get("event_id")] if e.get("event_id") else [],
        raw_event_types=[et],
        context_snapshot=_context_snapshot(e),
        raw_event=e,
        payload=e.get("payload", {}) or {},
    )

    mapping = {
        "app_switch": "APP_SWITCH_EVENT",
        "mouse_click": "CLICK_EVENT",
        "mouse_double_click": "DOUBLE_CLICK_EVENT",
        "mouse_scroll": "SCROLL_EVENT",
        "mouse_drag_drop": "DRAG_DROP_EVENT",
        "clipboard_change": "CLIPBOARD_CHANGE",
        "text_input_complete": "TEXT_INPUT_COMPLETE_HINT",
        "window_title_change": "WINDOW_CONTEXT",
        "window_state_change": "WINDOW_CONTEXT",
        "dialog_opened": "DIALOG_OPEN",
        "dialog_closed": "DIALOG_CLOSE",
        "screenshot_smart": "SCREENSHOT",
        "browser_click": "BROWSER_CLICK_EVENT",
        "browser_form_input": "BROWSER_FORM_INPUT",
        "browser_navigation": "NAVIGATE_EVENT",
        "browser_tab_event": "TAB_EVENT",
        "browser_alert": "OTHER_EVENT",
        "browser_error": "OTHER_EVENT",
        "session_start": "SYSTEM_EVENT",
        "session_end": "SYSTEM_EVENT",
        "extension_connected": "SYSTEM_EVENT",
        "extension_disconnected": "SYSTEM_EVENT",
        "upload_started": "SYSTEM_EVENT",
        "upload_completed": "SYSTEM_EVENT",
        "upload_failed": "SYSTEM_EVENT",
    }
    op_type = mapping.get(et, "OTHER_EVENT")
    return Operation(op_type=op_type, **base)


def _is_printable_text_keystroke(e: dict) -> bool:
    if e.get("event_type") != "keystroke":
        return False
    mods = get_modifiers(e)
    if command_modifier_active(mods):
        return False
    key = normalize_key_name(payload_get(e, "key"))
    char = payload_get(e, "character")
    if key in _BARE_MODIFIER_KEYS or key in ("backspace", "delete", "enter", "tab", "escape", "left", "right", "up", "down", "home", "end"):
        return False
    return isinstance(char, str) and len(char) == 1 and char.isprintable()


def _targeted_extracted_text_from_op(op: Operation) -> Optional[str]:
    """Return extracted text that is strong enough to act as a field/value
    checkpoint rather than generic page OCR."""
    raw = op.raw_event or {}
    value = context_get(raw, "extracted_text")
    if not isinstance(value, dict):
        return None
    source = value.get("source")
    text = value.get("text")
    if not isinstance(text, str) or not text:
        return None
    if source in {"text_input", "browser_form_input", "accessibility", "field_value"}:
        return text
    if source == "text_pattern":
        # Full-page OCR can also be tagged text_pattern. Only treat it as a
        # targeted field/value checkpoint when it looks like a compact
        # single-line value rather than a screen dump.
        if "\n" not in text and "\r" not in text and len(text) <= 256:
            return text
    return None


def _build_text_input_echo_index(events: List[dict], config: Config) -> Tuple[set, set, Dict[str, dict]]:
    """Build evidence-backed suppression sets from text_input_complete.

    Returns:
      related_ids: all raw keystroke IDs explicitly linked to a text-input
                   episode.
      echo_ids:    raw printable keystrokes paired with a related event and
                   therefore treated as recorder echoes for that episode.
      episode_by_related_id: metadata for the text-input episode owning each
                   related event.

    Crucially, we never ask whether repeated characters are "real". The
    recorder itself supplies the semantic membership through related_keystrokes.
    The short time gap is used only to associate the immediately following
    raw echo with its already-authoritative related event.
    """
    related_ids: set = set()
    echo_ids: set = set()
    episode_by_related_id: Dict[str, dict] = {}

    event_by_id = {e.get("event_id"): e for e in events if e.get("event_id")}
    keystrokes = [e for e in events if e.get("event_type") == "keystroke"]

    for complete in (e for e in events if e.get("event_type") == "text_input_complete"):
        payload = complete.get("payload", {}) or {}
        raw_related = payload.get("related_keystrokes", []) or []
        related = [eid for eid in raw_related if eid in event_by_id]
        if not related:
            continue

        related_events = [event_by_id[eid] for eid in related]
        start_ms = min(int(e.get("timestamp_ms", 0) or 0) for e in related_events)
        end_ms = max(int(e.get("timestamp_ms", 0) or 0) for e in related_events)
        target_sigs = {_target_signature_from_event(e) for e in related_events}
        complete_id = complete.get("event_id")
        episode = {
            "complete_event_id": complete_id,
            "related_ids": frozenset(related),
            "start_ms": start_ms,
            "end_ms": end_ms,
            "target_sigs": target_sigs,
            "final_text": payload.get("final_text"),
            "keystroke_count": payload.get("keystroke_count"),
        }

        for eid in related:
            related_ids.add(eid)
            episode_by_related_id[eid] = episode

        # For each semantic/related keystroke, look for its immediate next
        # raw keystroke. In the real data this is the recorder's duplicate
        # stream (often 1-5 ms later, adjacent in sequence number). We do not
        # require identical characters: Shift+number can be represented as a
        # different key/character on the echo event.
        keystroke_index = {e.get("event_id"): i for i, e in enumerate(keystrokes)}
        for eid in related:
            e = event_by_id[eid]
            idx = keystroke_index.get(eid)
            if idx is None:
                continue
            t0 = int(e.get("timestamp_ms", 0) or 0)
            source_sig = _target_signature_from_event(e)

            for cand in keystrokes[idx + 1:]:
                tc = int(cand.get("timestamp_ms", 0) or 0)
                gap = tc - t0
                if gap < 0:
                    continue
                if gap > config.linked_echo_max_gap_ms:
                    break
                cid = cand.get("event_id")
                if cid in related_ids:
                    continue
                if not _is_printable_text_keystroke(cand):
                    continue
                if _target_signature_from_event(cand) != source_sig:
                    continue
                echo_ids.add(cid)
                break

    return related_ids, echo_ids, episode_by_related_id


def normalize_events(events: List[dict], config: Config, tracer: Tracer) -> List[Operation]:
    ops: List[Operation] = []
    related_ids, linked_echo_ids, _episode_by_related_id = _build_text_input_echo_index(events, config)
    general_echo_ids = _build_general_command_echo_index(events, config)
    i = 0
    n = len(events)
    while i < n:
        e = events[i]
        tracer.raw_event(e)
        et = e.get("event_type")

        if et == "keystroke":
            event_id = e.get("event_id")

            # Real-data rule: when a text_input_complete event explicitly
            # identifies the semantic keystrokes, a paired printable event
            # outside that related set is a recorder echo, not a second user
            # character. This runs before the older modifier heuristics.
            if event_id in linked_echo_ids:
                tracer.decision(
                    event_id or "?",
                    "suppressed_as_text_input_linked_echo",
                    "event is the non-related paired printable keystroke following a related text-input event",
                )
                i += 1
                continue

            if event_id in general_echo_ids:
                tracer.decision(
                    event_id or "?",
                    "suppressed_as_general_command_release_echo",
                    "same-key unmodified keystroke immediately follows a command-modifier keystroke in the observed recorder pattern",
                )
                i += 1
                continue

            mods = get_modifiers(e)
            if command_modifier_active(mods):
                combo, consumed, j = _resolve_command_combo(events, i, config, tracer)
                op = _combo_to_operation(combo, consumed)
                ops.append(op)
                tracer.operation(op)
                i = j
                continue
            elif shift_only(mods):
                # When this keystroke is explicitly listed by
                # text_input_complete, keep it as the semantic event and let
                # the following linked echo be filtered on its own iteration.
                # This also avoids putting the recorder echo into the logical
                # operation's source_event_ids.
                if event_id in related_ids:
                    consumed, j = [e], i + 1
                else:
                    consumed, j = _resolve_shift_echo(events, i, config, tracer)
                op = _keystroke_to_operation(consumed, mods)
                if op is not None:
                    ops.append(op)
                    tracer.operation(op)
                i = j
                continue
            else:
                op = _keystroke_to_operation([e], mods)
                if op is not None:
                    ops.append(op)
                    tracer.operation(op)
                i += 1
                continue

        elif et == "shortcut":
            # A shortcut event not consumed as part of a command-combo
            # scan above (e.g. appears without a preceding modified
            # keystroke in this stream). Keep it as evidence; it carries
            # no text-mutating effect on its own.
            op = Operation(
                op_type="SHORTCUT_EVENT_ONLY",
                timestamp_ms=e.get("timestamp_ms", 0),
                timestamp_iso=e.get("timestamp_iso", ""),
                source_event_ids=[e.get("event_id")] if e.get("event_id") else [],
                raw_event_types=[et],
                context_snapshot=_context_snapshot(e),
                raw_event=e,
            )
            ops.append(op)
            tracer.operation(op)
            i += 1
            continue

        else:
            op = _non_keystroke_to_operation(e)
            if op is not None:
                ops.append(op)
                tracer.operation(op)
            i += 1
            continue

    return ops


# --------------------------------------------------------------------------
# Phase B -- stateful text-buffer engine
# --------------------------------------------------------------------------


class TextRunEngine:
    def __init__(self):
        self.buffer: List[str] = []
        self.cursor: int = 0
        self.selection: Optional[Tuple[int, int]] = None
        self._undo_stack: List[tuple] = []
        self._redo_stack: List[tuple] = []
        self.undo_used = False

    # -- snapshotting --
    def _snapshot(self) -> tuple:
        return (tuple(self.buffer), self.cursor, self.selection)

    def _restore(self, snap: tuple) -> None:
        self.buffer = list(snap[0])
        self.cursor = snap[1]
        self.selection = snap[2]

    def text(self) -> str:
        return "".join(self.buffer)

    # -- selection helpers --
    def _delete_selection(self) -> str:
        assert self.selection is not None
        lo, hi = self.selection
        lo, hi = max(0, min(lo, hi)), min(len(self.buffer), max(lo, hi))
        removed = "".join(self.buffer[lo:hi])
        del self.buffer[lo:hi]
        self.cursor = lo
        self.selection = None
        return removed

    def _push_undo(self):
        self._undo_stack.append(self._snapshot())
        self._redo_stack.clear()

    # -- apply a single Operation, returns dict of side-effect info
    # (e.g. {'cut_text': ...}) used by the caller for clipboard handling --
    def apply(self, op: Operation, clipboard: "SessionClipboard", tracer: Tracer) -> dict:
        info: dict = {}
        t = op.op_type

        if t == "INSERT":
            self._push_undo()
            if self.selection is not None:
                self._delete_selection()
            self.buffer.insert(self.cursor, op.char)
            self.cursor += 1

        elif t == "BACKSPACE":
            self._push_undo()
            if self.selection is not None:
                self._delete_selection()
            elif self.cursor > 0:
                del self.buffer[self.cursor - 1]
                self.cursor -= 1

        elif t == "DELETE":
            self._push_undo()
            if self.selection is not None:
                self._delete_selection()
            elif self.cursor < len(self.buffer):
                del self.buffer[self.cursor]

        elif t == "DELETE_WORD_BACK":
            self._push_undo()
            if self.selection is not None:
                self._delete_selection()
            else:
                idx = self.cursor
                # skip trailing whitespace, then delete back to previous
                # whitespace boundary (simple word-boundary model).
                while idx > 0 and self.buffer[idx - 1] == " ":
                    idx -= 1
                while idx > 0 and self.buffer[idx - 1] != " ":
                    idx -= 1
                del self.buffer[idx:self.cursor]
                self.cursor = idx

        elif t in ("MOVE_LEFT", "MOVE_RIGHT", "MOVE_HOME", "MOVE_END", "MOVE_UP", "MOVE_DOWN"):
            anchor = self.selection[0] if self.selection else self.cursor
            if t == "MOVE_LEFT":
                new_cursor = max(0, self.cursor - 1)
            elif t == "MOVE_RIGHT":
                new_cursor = min(len(self.buffer), self.cursor + 1)
            elif t == "MOVE_HOME":
                new_cursor = 0
            elif t == "MOVE_END":
                new_cursor = len(self.buffer)
            else:
                new_cursor = self.cursor  # single-line buffer model: UP/DOWN no-op
            if op.extend_selection:
                self.selection = (anchor, new_cursor)
            else:
                self.selection = None
            self.cursor = new_cursor

        elif t in ("MOVE_WORD_LEFT", "MOVE_WORD_RIGHT"):
            idx = self.cursor
            if t == "MOVE_WORD_LEFT":
                while idx > 0 and self.buffer[idx - 1] == " ":
                    idx -= 1
                while idx > 0 and self.buffer[idx - 1] != " ":
                    idx -= 1
            else:
                n = len(self.buffer)
                while idx < n and self.buffer[idx] == " ":
                    idx += 1
                while idx < n and self.buffer[idx] != " ":
                    idx += 1
            self.cursor = idx
            self.selection = None

        elif t == "SELECT_ALL":
            self.selection = (0, len(self.buffer))
            self.cursor = len(self.buffer)

        elif t == "COPY":
            content = self._delete_selection_preview() if self.selection else clipboard.content
            if self.selection:
                lo, hi = sorted(self.selection)
                content = "".join(self.buffer[lo:hi])
                info["copied_text"] = content

        elif t == "CUT":
            self._push_undo()
            if self.selection is not None:
                removed = self._delete_selection()
                info["cut_text"] = removed
            else:
                info["cut_text"] = ""

        elif t == "PASTE":
            self._push_undo()
            content = clipboard.content
            if content is None:
                info["paste_content_unknown"] = True
            else:
                if self.selection is not None:
                    self._delete_selection()
                for ch in content:
                    self.buffer.insert(self.cursor, ch)
                    self.cursor += 1

        elif t == "UNDO":
            if self._undo_stack:
                self._redo_stack.append(self._snapshot())
                self._restore(self._undo_stack.pop())
                self.undo_used = True

        elif t == "REDO":
            if self._redo_stack:
                self._undo_stack.append(self._snapshot())
                self._restore(self._redo_stack.pop())

        # ENTER / TAB / ESCAPE / SHORTCUT / *_EVENT / etc. are handled as
        # boundaries by the caller (build_activities), not by the buffer
        # engine -- they don't mutate text state.

        tracer.text_state(None, self.text(), self.cursor, self.selection)
        return info

    def _delete_selection_preview(self) -> str:
        if not self.selection:
            return ""
        lo, hi = sorted(self.selection)
        return "".join(self.buffer[lo:hi])


class SessionClipboard:
    """Tracks the most recently observed clipboard content for a whole
    session. Populated primarily by clipboard_change events (the
    recorder's direct observation of the OS clipboard), which are treated
    as authoritative over a COPY/CUT operation's own guess -- multiple
    candidate payload keys are tried defensively since the exact field
    name is not pinned down in the schema doc."""

    _CANDIDATE_KEYS = ("content", "new_content", "text", "new_value", "value", "data")

    def __init__(self):
        self.content: Optional[str] = None

    def observe_clipboard_change_event(self, e: dict) -> None:
        payload = e.get("payload", {}) or {}
        for key in self._CANDIDATE_KEYS:
            if key in payload and isinstance(payload[key], str):
                self.content = payload[key]
                return
        # nested shape, e.g. {"new": {"text": ...}}
        for outer in ("new", "to", "after"):
            inner = payload.get(outer)
            if isinstance(inner, dict):
                for key in self._CANDIDATE_KEYS:
                    if key in inner and isinstance(inner[key], str):
                        self.content = inner[key]
                        return

    def observe_copied_text(self, text: str) -> None:
        # Fallback only: used if no clipboard_change event corroborates a
        # COPY operation's selection-derived guess.
        if self.content is None and text:
            self.content = text


# --------------------------------------------------------------------------
# Phase C -- checkpoint reconciliation
# --------------------------------------------------------------------------


def reconcile_checkpoints(
    reconstructed_text: str,
    browser_values: List[str],
    screen_texts: List[str],
    input_complete_values: Optional[List[str]] = None,
    targeted_screen_values: Optional[List[str]] = None,
) -> dict:
    """Compare reconstruction against structured and screen evidence.

    Absence from generic full-screen OCR is *not* treated as a contradiction:
    a screenshot can simply be showing a different part of the page, or a
    password field may be masked. A true screen conflict requires a targeted
    extracted value (for example source=text_pattern) that disagrees with the
    reconstruction.
    """
    input_complete_values = input_complete_values or []
    targeted_screen_values = targeted_screen_values or []

    input_match = None
    for value in input_complete_values:
        if value is not None and value == reconstructed_text:
            input_match = True
            break
    if input_complete_values and input_match is None:
        input_match = False

    browser_match = None
    for bv in browser_values:
        if bv is not None and bv == reconstructed_text:
            browser_match = True
            break
    if browser_values and browser_match is None:
        browser_match = False

    targeted_screen_match = None
    for value in targeted_screen_values:
        if value is not None and value == reconstructed_text:
            targeted_screen_match = True
            break
    if targeted_screen_values and targeted_screen_match is None:
        targeted_screen_match = False

    # Generic OCR is positive evidence when it contains the reconstructed
    # text, but its failure to contain the text is intentionally neutral.
    generic_screen_match = None
    for st in screen_texts:
        if st and reconstructed_text and reconstructed_text in st:
            generic_screen_match = True
            break

    matches = [m for m in (input_match, browser_match, targeted_screen_match) if m is not None]
    true_match_count = sum(m is True for m in matches)
    if False in matches:
        status = "CONFLICT"
    elif true_match_count >= 2:
        status = "RECONCILED"
    elif input_match is True:
        status = "VERIFIED_INPUT_COMPLETE"
    elif browser_match is True:
        status = "VERIFIED_BROWSER"
    elif targeted_screen_match is True or generic_screen_match is True:
        status = "VERIFIED_SCREEN"
    else:
        status = "RECONSTRUCTED"

    return {
        "verification_status": status,
        "browser_value": browser_values[-1] if browser_values else None,
        "screen_value": targeted_screen_values[-1] if targeted_screen_values else None,
        "input_complete_value": input_complete_values[-1] if input_complete_values else None,
    }


# --------------------------------------------------------------------------
# Entity extraction (best-effort, deliberately conservative)
# --------------------------------------------------------------------------

_ID_RE = re.compile(r"\b[A-Z]{1,5}-\d{4,8}-\d{2,4}\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_FILENAME_RE = re.compile(
    r"\b[\w\-. ]+\.(?:xlsx|xls|docx|doc|pdf|csv|pptx|ppt|txt|png|jpg|jpeg)\b", re.IGNORECASE
)
_URL_RE = re.compile(r"https?://[^\s\"'<>]+")
_PRIVATE_HOST_RE = re.compile(
    r"^(localhost|127\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|"
    r"172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+|::1)"
)
_NUMBER_RE = re.compile(r"\b\d+\b")

_ID_PREFIX_TYPE = {
    "INV": "INVOICE_ID",
    "EMP": "EMPLOYEE_ID",
    "CS": "CASE_ID",
    "CASE": "CASE_ID",
    "DOC": "DOCUMENT_ID",
    "CU": "CUSTOMER_ID",
    "CUST": "CUSTOMER_ID",
}


def _is_infra_url(url: str) -> bool:
    m = re.match(r"https?://([^/:\s]+)", url)
    if not m:
        return False
    host = m.group(1)
    return bool(_PRIVATE_HOST_RE.match(host))


def extract_entities(text: str, screen_text: str, config: Config) -> List[dict]:
    entities: List[dict] = []
    if not text and not screen_text:
        return entities
    combined = " ".join(t for t in (text, screen_text) if t)

    for m in _ID_RE.finditer(combined):
        val = m.group(0)
        prefix = val.split("-")[0]
        etype = _ID_PREFIX_TYPE.get(prefix, "ID_CANDIDATE")
        entities.append({"type": etype, "value": val})

    for m in _EMAIL_RE.finditer(combined):
        entities.append({"type": "EMAIL", "value": m.group(0)})

    for m in _FILENAME_RE.finditer(combined):
        entities.append({"type": "FILENAME", "value": m.group(0)})

    for m in _URL_RE.finditer(combined):
        url = m.group(0)
        if not _is_infra_url(url):
            entities.append({"type": "URL", "value": url})

    already_covered_spans = set()
    for m in _ID_RE.finditer(combined):
        already_covered_spans.update(range(m.start(), m.end()))
    for m in _NUMBER_RE.finditer(combined):
        if m.start() in already_covered_spans:
            continue
        if len(m.group(0)) >= config.min_number_candidate_digits:
            entities.append({"type": "NUMBER_CANDIDATE", "value": m.group(0)})

    # de-duplicate while preserving order
    seen = set()
    deduped = []
    for ent in entities:
        key = (ent["type"], ent["value"])
        if key not in seen:
            seen.add(key)
            deduped.append(ent)
    return deduped


# --------------------------------------------------------------------------
# Phase D -- activity grouping
# --------------------------------------------------------------------------


def _target_signature(ctx: dict) -> tuple:
    tf = ctx.get("target_field")
    if isinstance(tf, dict):
        sig = (
            tf.get("automation_id"),
            tf.get("class_name"),
            tf.get("control_type"),
            tf.get("name"),
        )
    else:
        sig = (tf,)
    return (ctx.get("app_name"), ctx.get("window_title"), sig)


class _ActivityBuilder:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self._counter = 0
        self.activities: List[dict] = []

    def _next_id(self) -> str:
        self._counter += 1
        return f"act_{self.session_id}_{self._counter:06d}"

    def emit(self, **fields) -> dict:
        base = {
            "activity_id": self._next_id(),
            "session_id": self.session_id,
            "start": None,
            "end": None,
            "type": "OTHER",
            "app": None,
            "window": None,
            "browser_tab": None,
            "browser_url": None,
            "target_field": None,
            "text": "",
            "screen_text": "",
            "entities": [],
            "source_event_ids": [],
            "triggered_by": [],
            "source_event_types": [],
            "source_layers": [],
            "chunk_ids": [],
            "assignment": "UNKNOWN",
        }
        base.update(fields)
        self.activities.append(base)
        return base


class _TextRun:
    def __init__(self, run_key: tuple, first_op: Operation):
        self.run_key = run_key
        self.engine = TextRunEngine()
        self.start_ts = first_op.timestamp_iso
        self.start_ms = first_op.timestamp_ms
        self.last_ms = first_op.timestamp_ms
        self.last_ts = first_op.timestamp_iso
        self.source_event_ids: List[str] = []
        self.raw_event_types: set = set()
        self.source_layers: set = set()
        self.chunk_ids: set = set()
        self.triggered_by: set = set()
        self.browser_values: List[str] = []
        self.screen_texts: List[str] = []
        self.targeted_screen_values: List[str] = []
        self.input_complete_values: List[str] = []
        self.input_complete_ids: List[str] = []
        self.context = dict(first_op.context_snapshot)
        self.paste_content_unknown = False
        self.suppressed_echo_event_ids: List[str] = []

    def note_event(self, op: Operation) -> None:
        self.last_ms = op.timestamp_ms
        self.last_ts = op.timestamp_iso
        self.source_event_ids.extend(op.source_event_ids)
        self.raw_event_types.update(op.raw_event_types)
        if op.raw_event is not None:
            layer = op.raw_event.get("layer")
            if layer:
                self.source_layers.add(layer)
            chunk_id = corr_get(op.raw_event, "chunk_id")
            if chunk_id:
                self.chunk_ids.add(chunk_id)
            tb = corr_get(op.raw_event, "triggered_by")
            if tb:
                self.triggered_by.add(tb)
        ctx_text = _extracted_text_value(op.context_snapshot.get("extracted_text"))
        if ctx_text:
            self.screen_texts.append(ctx_text)
        targeted = _targeted_extracted_text_from_op(op)
        if targeted:
            self.targeted_screen_values.append(targeted)


def _open_new_run(op: Operation) -> _TextRun:
    return _TextRun(_target_signature(op.context_snapshot), op)


def build_activities(events: List[dict], session_id: str, config: Config, tracer: Tracer) -> List[dict]:
    ops = normalize_events(events, config, tracer)
    builder = _ActivityBuilder(session_id)
    clipboard = SessionClipboard()

    current_run: Optional[_TextRun] = None
    open_dialog: Optional[dict] = None
    last_clipboard_change_ms: Optional[int] = None
    last_copy_op_ms: Optional[int] = None

    # Bounded record of the most recently closed text activity. Passive
    # evidence can update this activity for a short window when the evidence
    # still belongs to the same active context.
    recent_text_activity: Optional[dict] = None
    recent_text_closed_ms: Optional[int] = None
    recent_browser_values: List[str] = []
    recent_screen_texts: List[str] = []
    recent_targeted_screen_values: List[str] = []
    recent_input_complete_values: List[str] = []
    last_app_signature = None

    def _app_name_from_new_app(value):
        if isinstance(value, dict):
            return value.get("app_name")
        if isinstance(value, (list, tuple)) and value:
            return value[0]
        return value

    def _app_signature(op: Operation) -> tuple:
        # app_switch.payload.new_app is the state being switched to. The
        # active_app context describes the state currently producing the
        # event, so it is not used for deduplicating switch targets.
        new_app = op.payload.get("new_app")
        try:
            new_app_key = json.dumps(new_app, ensure_ascii=False, sort_keys=True, default=str)
        except TypeError:
            new_app_key = repr(new_app)
        return (new_app_key, op.context_snapshot.get("window_title"))

    def _same_active_context(ctx: dict, app: Optional[str], window: Optional[str]) -> bool:
        if app and ctx.get("app_name") and app != ctx.get("app_name"):
            return False
        if window and ctx.get("window_title") and window != ctx.get("window_title"):
            return False
        return True

    def _reconcile_activity_from_recent() -> None:
        nonlocal recent_text_activity
        if recent_text_activity is None:
            return
        recon = reconcile_checkpoints(
            recent_text_activity.get("text", ""),
            recent_browser_values,
            recent_screen_texts,
            recent_input_complete_values,
            recent_targeted_screen_values,
        )
        recent_text_activity["verification_status"] = recon["verification_status"]
        recent_text_activity["browser_value"] = recon["browser_value"]
        recent_text_activity["screen_value"] = recon["screen_value"]
        recent_text_activity["input_complete_value"] = recon["input_complete_value"]
        recent_text_activity["input_complete_count"] = len(recent_input_complete_values)
        recent_text_activity["screen_text"] = " ".join(recent_screen_texts)
        recent_text_activity["entities"] = extract_entities(
            recent_text_activity.get("text", ""),
            recent_text_activity.get("screen_text", ""),
            config,
        )

    def _attach_passive_evidence_to_current(op: Operation) -> bool:
        if current_run is None:
            return False
        t = op.op_type
        if t == "BROWSER_FORM_INPUT":
            val = op.payload.get("value")
            if isinstance(val, str):
                current_run.browser_values.append(val)
                return True
        elif t == "TEXT_INPUT_COMPLETE_HINT":
            val = op.payload.get("final_text")
            if isinstance(val, str):
                current_run.input_complete_values.append(val)
                if op.source_event_ids:
                    current_run.input_complete_ids.extend(op.source_event_ids)
                return True
        else:
            txt = _extracted_text_value(op.context_snapshot.get("extracted_text"))
            if txt:
                current_run.screen_texts.append(txt)
                targeted = _targeted_extracted_text_from_op(op)
                if targeted:
                    current_run.targeted_screen_values.append(targeted)
                return True
        return False

    def _attach_passive_evidence_to_recent(op: Operation, allow_window_mismatch: bool = False) -> bool:
        nonlocal recent_text_activity
        if recent_text_activity is None or recent_text_closed_ms is None:
            return False
        gap = op.timestamp_ms - recent_text_closed_ms
        if gap < 0 or gap > config.recent_evidence_window_ms:
            return False

        if op.context_snapshot.get("app_name") and recent_text_activity.get("app"):
            if op.context_snapshot.get("app_name") != recent_text_activity.get("app"):
                return False
        if not allow_window_mismatch:
            if op.context_snapshot.get("window_title") and recent_text_activity.get("window"):
                if op.context_snapshot.get("window_title") != recent_text_activity.get("window"):
                    return False

        # A later checkpoint from the same application/window can still be a
        # different form field. Do not attach it to the previous text run
        # unless the target-field signature is compatible.
        op_target_sig = _target_signature(op.context_snapshot)
        recent_target_sig = _target_signature({
            "app_name": recent_text_activity.get("app"),
            "window_title": recent_text_activity.get("window"),
            "target_field": recent_text_activity.get("target_field"),
        })
        if op.context_snapshot.get("target_field") is not None and recent_text_activity.get("target_field") is not None:
            if op_target_sig != recent_target_sig:
                return False

        attached = False
        t = op.op_type
        # Structured input/browser checkpoints belong to the text run that
        # produced them. Once a run is closed, accepting a later
        # text_input_complete would frequently attach the NEXT field to the
        # previous field, as observed in the real session. Only passive
        # screen/app-switch evidence is eligible for the bounded post-run
        # window.
        if t in ("BROWSER_FORM_INPUT", "TEXT_INPUT_COMPLETE_HINT"):
            return False

        txt = _extracted_text_value(op.context_snapshot.get("extracted_text"))
        if txt:
            recent_screen_texts.append(txt)
            targeted = _targeted_extracted_text_from_op(op)
            if targeted:
                recent_targeted_screen_values.append(targeted)
            attached = True

        if attached:
            _reconcile_activity_from_recent()
        return attached

    def close_run():
        nonlocal current_run
        nonlocal recent_text_activity, recent_text_closed_ms
        nonlocal recent_browser_values, recent_screen_texts, recent_targeted_screen_values, recent_input_complete_values

        if current_run is None:
            return
        r = current_run
        text = r.engine.text()
        recon = reconcile_checkpoints(
            text,
            r.browser_values,
            r.screen_texts,
            r.input_complete_values,
            r.targeted_screen_values,
        )
        entities = extract_entities(text, " ".join(r.screen_texts), config)
        target_field = r.context.get("target_field")

        activity = builder.emit(
            start=r.start_ts,
            end=r.last_ts,
            type="TEXT_ENTRY",
            app=r.context.get("app_name"),
            window=r.context.get("window_title"),
            browser_tab=r.context.get("browser_title"),
            browser_url=r.context.get("browser_url"),
            target_field=target_field,
            text=text,
            screen_text=" ".join(r.screen_texts),
            entities=entities,
            source_event_ids=list(dict.fromkeys(r.source_event_ids)),
            triggered_by=sorted(r.triggered_by),
            source_event_types=sorted(r.raw_event_types),
            source_layers=sorted(r.source_layers),
            chunk_ids=sorted(r.chunk_ids),
            verification_status=recon["verification_status"],
            browser_value=recon["browser_value"],
            screen_value=recon["screen_value"],
            input_complete_value=recon["input_complete_value"],
            input_complete_count=len(r.input_complete_values),
            undo_used=r.engine.undo_used,
            paste_content_unknown=r.paste_content_unknown,
        )

        # Only text runs initiated by an actual text mutation reach this
        # point, so an empty control-only run is no longer possible.
        recent_text_activity = activity
        recent_text_closed_ms = r.last_ms
        recent_browser_values = list(r.browser_values)
        recent_screen_texts = list(r.screen_texts)
        recent_targeted_screen_values = list(r.targeted_screen_values)
        recent_input_complete_values = list(r.input_complete_values)
        current_run = None

    def close_dialog(end_ts: str):
        nonlocal open_dialog
        if open_dialog is None:
            return
        builder.emit(
            start=open_dialog["start"],
            end=end_ts,
            type="DIALOG",
            app=open_dialog["app"],
            window=open_dialog["window"],
            source_event_ids=open_dialog["source_event_ids"],
            source_event_types=["dialog_opened", "dialog_closed"],
            source_layers=open_dialog["source_layers"],
            chunk_ids=open_dialog["chunk_ids"],
        )
        open_dialog = None

    for op in ops:
        t = op.op_type

        if t in _TEXT_DOMAIN_OPS:
            sig = _target_signature(op.context_snapshot)
            gap = op.timestamp_ms - current_run.last_ms if current_run else 0

            if current_run is not None and (current_run.run_key != sig or gap > config.inactivity_gap_ms):
                close_run()

            # Control-only operations may modify the state of an already open
            # text run, but they never create a brand-new empty TEXT_ENTRY.
            if current_run is None and t not in _TEXT_MUTATING_OPS:
                continue

            # An unknown clipboard paste gives us no text state. Starting a
            # TEXT_ENTRY here only creates an empty activity that cannot be
            # reconstructed or verified. Drop the operation from the activity
            # layer until a real text mutation/checkpoint establishes content.
            if current_run is None and t == "PASTE" and clipboard.content is None:
                continue

            if current_run is None:
                current_run = _open_new_run(op)

            info = current_run.engine.apply(op, clipboard, tracer)
            current_run.note_event(op)

            if t == "COPY" and "copied_text" in info:
                clipboard.observe_copied_text(info["copied_text"])
                last_copy_op_ms = op.timestamp_ms
            if t == "CUT" and "cut_text" in info and info["cut_text"]:
                clipboard.observe_copied_text(info["cut_text"])
            if t == "PASTE" and info.get("paste_content_unknown"):
                current_run.paste_content_unknown = True
            continue

        if t in ("ENTER", "TAB", "ESCAPE"):
            if current_run is not None:
                current_run.note_event(op)
                close_run()
            continue

        if t == "CLICK_EVENT" or t == "DOUBLE_CLICK_EVENT" or t == "BROWSER_CLICK_EVENT":
            close_run()
            elem = op.payload.get("element") if t == "BROWSER_CLICK_EVENT" else None
            builder.emit(
                start=op.timestamp_iso,
                end=op.timestamp_iso,
                type="CLICK",
                app=op.context_snapshot.get("app_name"),
                window=op.context_snapshot.get("window_title"),
                browser_tab=op.context_snapshot.get("browser_title"),
                browser_url=op.context_snapshot.get("browser_url"),
                target_field=elem,
                source_event_ids=op.source_event_ids,
                source_event_types=op.raw_event_types,
                source_layers=[op.raw_event.get("layer")] if op.raw_event else [],
                chunk_ids=[corr_get(op.raw_event, "chunk_id")] if corr_get(op.raw_event, "chunk_id") else [],
            )
            continue

        if t == "APP_SWITCH_EVENT":
            # The active_app context on the app_switch event describes the
            # window that produced the event. It can therefore carry the final
            # OCR checkpoint for a text run that is about to close, even when
            # payload.new_app points somewhere else.
            if current_run is not None:
                _attach_passive_evidence_to_current(op)

                same_active_context = _same_active_context(
                    current_run.context,
                    op.context_snapshot.get("app_name"),
                    op.context_snapshot.get("window_title"),
                )
                if same_active_context:
                    # Repeated app_switch snapshots inside the same active
                    # context are recorder noise; do not split the text run.
                    continue
                close_run()
            else:
                # No open text run: a short-lived just-closed activity can
                # still receive a same-app OCR checkpoint from this event.
                _attach_passive_evidence_to_recent(op, allow_window_mismatch=False)

            sig = _app_signature(op)
            if sig == last_app_signature:
                continue

            close_dialog(op.timestamp_iso)
            builder.emit(
                start=op.timestamp_iso,
                end=op.timestamp_iso,
                type="APP_SWITCH",
                app=op.payload.get("new_app"),
                window=op.context_snapshot.get("window_title"),
                source_event_ids=op.source_event_ids,
                source_event_types=op.raw_event_types,
                source_layers=[op.raw_event.get("layer")] if op.raw_event else [],
                chunk_ids=[corr_get(op.raw_event, "chunk_id")] if corr_get(op.raw_event, "chunk_id") else [],
                triggered_by=[op.payload.get("previous_app")] if op.payload.get("previous_app") else [],
            )
            last_app_signature = sig
            continue

        if t in ("NAVIGATE_EVENT", "TAB_EVENT"):
            close_run()
            builder.emit(
                start=op.timestamp_iso,
                end=op.timestamp_iso,
                type="NAVIGATE",
                app=op.context_snapshot.get("app_name"),
                window=op.context_snapshot.get("window_title"),
                browser_tab=op.context_snapshot.get("browser_title"),
                browser_url=op.context_snapshot.get("browser_url"),
                source_event_ids=op.source_event_ids,
                source_event_types=op.raw_event_types,
                source_layers=[op.raw_event.get("layer")] if op.raw_event else [],
                chunk_ids=[corr_get(op.raw_event, "chunk_id")] if corr_get(op.raw_event, "chunk_id") else [],
            )
            continue

        if t == "SCROLL_EVENT" or t == "DRAG_DROP_EVENT":
            builder.emit(
                start=op.timestamp_iso,
                end=op.timestamp_iso,
                type="SCROLL" if t == "SCROLL_EVENT" else "OTHER",
                app=op.context_snapshot.get("app_name"),
                window=op.context_snapshot.get("window_title"),
                source_event_ids=op.source_event_ids,
                source_event_types=op.raw_event_types,
                source_layers=[op.raw_event.get("layer")] if op.raw_event else [],
                chunk_ids=[corr_get(op.raw_event, "chunk_id")] if corr_get(op.raw_event, "chunk_id") else [],
            )
            continue

        if t == "DIALOG_OPEN":
            close_dialog(op.timestamp_iso)
            open_dialog = {
                "start": op.timestamp_iso,
                "app": op.context_snapshot.get("app_name"),
                "window": op.context_snapshot.get("window_title"),
                "source_event_ids": list(op.source_event_ids),
                "source_layers": [op.raw_event.get("layer")] if op.raw_event else [],
                "chunk_ids": [corr_get(op.raw_event, "chunk_id")] if corr_get(op.raw_event, "chunk_id") else [],
            }
            continue

        if t == "DIALOG_CLOSE":
            if open_dialog is not None:
                open_dialog["source_event_ids"].extend(op.source_event_ids)
            close_dialog(op.timestamp_iso)
            continue

        if t == "CLIPBOARD_CHANGE":
            if op.raw_event is not None:
                clipboard.observe_clipboard_change_event(op.raw_event)
            gap_from_copy = (
                op.timestamp_ms - last_copy_op_ms if last_copy_op_ms is not None else None
            )
            externally_triggered = gap_from_copy is None or gap_from_copy > 1000
            last_clipboard_change_ms = op.timestamp_ms
            if externally_triggered:
                builder.emit(
                    start=op.timestamp_iso,
                    end=op.timestamp_iso,
                    type="COPY",
                    app=op.context_snapshot.get("app_name"),
                    window=op.context_snapshot.get("window_title"),
                    text=clipboard.content or "",
                    source_event_ids=op.source_event_ids,
                    source_event_types=op.raw_event_types,
                    source_layers=[op.raw_event.get("layer")] if op.raw_event else [],
                    chunk_ids=[corr_get(op.raw_event, "chunk_id")] if corr_get(op.raw_event, "chunk_id") else [],
                )
            continue

        if t in ("BROWSER_FORM_INPUT", "TEXT_INPUT_COMPLETE_HINT"):
            if current_run is not None:
                _attach_passive_evidence_to_current(op)
            else:
                _attach_passive_evidence_to_recent(op)
            continue

        if t == "SHORTCUT" or t == "SHORTCUT_EVENT_ONLY":
            close_run()
            label = op.combo_label or ""
            # Empty shortcut events are recorder bookkeeping, not useful
            # activities. Keep labeled shortcuts only.
            if not label:
                continue
            builder.emit(
                start=op.timestamp_iso,
                end=op.timestamp_iso,
                type="SHORTCUT",
                app=op.context_snapshot.get("app_name"),
                window=op.context_snapshot.get("window_title"),
                text=label,
                source_event_ids=op.source_event_ids,
                source_event_types=op.raw_event_types,
                source_layers=[op.raw_event.get("layer")] if op.raw_event else [],
                chunk_ids=[corr_get(op.raw_event, "chunk_id")] if corr_get(op.raw_event, "chunk_id") else [],
            )
            continue

        if t in ("SCREENSHOT", "WINDOW_CONTEXT"):
            # Attach passive OCR to the active run when possible; otherwise
            # allow a short bounded post-run evidence update.
            if current_run is not None:
                _attach_passive_evidence_to_current(op)
            else:
                _attach_passive_evidence_to_recent(op)
            continue

        if t == "SYSTEM_EVENT":
            builder.emit(
                start=op.timestamp_iso,
                end=op.timestamp_iso,
                type="OTHER",
                source_event_ids=op.source_event_ids,
                source_event_types=op.raw_event_types,
                source_layers=[op.raw_event.get("layer")] if op.raw_event else [],
                chunk_ids=[corr_get(op.raw_event, "chunk_id")] if corr_get(op.raw_event, "chunk_id") else [],
            )
            continue

        builder.emit(
            start=op.timestamp_iso,
            end=op.timestamp_iso,
            type="OTHER",
            app=op.context_snapshot.get("app_name"),
            window=op.context_snapshot.get("window_title"),
            source_event_ids=op.source_event_ids,
            source_event_types=op.raw_event_types,
            source_layers=[op.raw_event.get("layer")] if op.raw_event else [],
            chunk_ids=[corr_get(op.raw_event, "chunk_id")] if corr_get(op.raw_event, "chunk_id") else [],
        )

    close_run()
    if open_dialog is not None:
        close_dialog(open_dialog["start"])

    builder.activities.sort(key=lambda a: (a["start"] or "", a["activity_id"]))
    return builder.activities


# --------------------------------------------------------------------------
# Session / chunk loading
# --------------------------------------------------------------------------


def load_session_events(session_dir: Path) -> List[dict]:
    events: List[dict] = []
    for chunk_dir in sorted(p for p in session_dir.iterdir() if p.is_dir() and p.name.startswith("chunk_")):
        events_path = chunk_dir / "events.jsonl"
        if not events_path.exists():
            continue
        with events_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                e = json.loads(line)
                e.setdefault("correlation", {})
                if not e["correlation"].get("chunk_id"):
                    e["correlation"]["chunk_id"] = chunk_dir.name
                events.append(e)

    def sort_key(e: dict):
        return (
            e.get("timestamp_ms", 0),
            corr_get(e, "sequence_number", default=0) or 0,
            e.get("event_id", ""),
        )

    events.sort(key=sort_key)
    return events


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def process_session(session_dir: Path, config: Config, tracer: Tracer) -> List[dict]:
    events = load_session_events(session_dir)
    return build_activities(events, session_dir.name, config, tracer)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Extract atomic activities from raw operation logs.")
    parser.add_argument("--data-root", required=True, help="Root directory containing dataset_a/dataset_b")
    parser.add_argument("--dataset", required=True, help="dataset_a or dataset_b")
    parser.add_argument("--session", default=None, help="Single session directory name; omit to process all")
    parser.add_argument("--output", required=True, help="Output JSONL path")
    parser.add_argument("--inactivity-gap-ms", type=int, default=Config.inactivity_gap_ms)
    parser.add_argument("--echo-structural-max-gap-ms", type=int, default=Config.echo_structural_max_gap_ms)
    parser.add_argument("--linked-echo-max-gap-ms", type=int, default=Config.linked_echo_max_gap_ms)
    parser.add_argument("--recent-evidence-window-ms", type=int, default=Config.recent_evidence_window_ms)
    args = parser.parse_args(argv)

    config = Config(
        inactivity_gap_ms=args.inactivity_gap_ms,
        echo_structural_max_gap_ms=args.echo_structural_max_gap_ms,
        linked_echo_max_gap_ms=args.linked_echo_max_gap_ms,
        recent_evidence_window_ms=args.recent_evidence_window_ms,
    )
    tracer = Tracer()

    dataset_dir = Path(args.data_root) / args.dataset
    if args.session:
        session_dirs = [dataset_dir / args.session]
    else:
        session_dirs = sorted(p for p in dataset_dir.iterdir() if p.is_dir() and p.name.startswith("ses_"))

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    with out_path.open("w", encoding="utf-8") as f:
        for session_dir in session_dirs:
            if not session_dir.exists():
                print(f"warning: session directory not found: {session_dir}", file=sys.stderr)
                continue
            activities = process_session(session_dir, config, tracer)
            for a in activities:
                f.write(json.dumps(a, ensure_ascii=False) + "\n")
            total += len(activities)
            print(f"{session_dir.name}: {len(activities)} activities", file=sys.stderr)

    print(f"wrote {total} activities to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
