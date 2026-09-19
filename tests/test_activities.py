"""
tests/test_activities.py

Synthetic tests. None of this data is real -- it is built to exercise the
specific recorder patterns and edit operations described in the task spec
(composite Ctrl+X echoes, correction sequences, undo/redo, etc.), since the
actual dataset files were not available in the environment this was
written in. Run this, then validate against real sessions with
debug_text_reconstruction.py and report back anything that doesn't match.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from activities import (  # noqa: E402
    Config,
    Tracer,
    TextRunEngine,
    SessionClipboard,
    normalize_events,
    build_activities,
)

DEFAULT_TARGET = {"automation_id": "field-1", "class_name": "Edit", "control_type": "Edit"}


def mk_event(
    event_id,
    ts_ms,
    event_type,
    layer="L2",
    key=None,
    character=None,
    ctrl=False,
    alt=False,
    shift=False,
    win=False,
    target_field=None,
    app_name="TestApp",
    window_title="TestWindow",
    seq=None,
    triggered_by=None,
    extra_payload=None,
    extracted_text=None,
):
    payload = {}
    if event_type == "keystroke":
        payload = {
            "key": key,
            "character": character,
            "modifiers": {"ctrl": ctrl, "alt": alt, "shift": shift, "win": win},
            "target_field": target_field if target_field is not None else DEFAULT_TARGET,
        }
    elif event_type == "shortcut":
        payload = {"modifiers": {"ctrl": ctrl, "alt": alt, "shift": shift, "win": win}}
    if extra_payload:
        payload.update(extra_payload)

    correlation = {"sequence_number": seq if seq is not None else ts_ms, "chunk_id": "chunk_1"}
    if triggered_by:
        correlation["triggered_by"] = triggered_by

    context = {
        "active_app": {"app_name": app_name, "process_name": app_name, "window_title": window_title},
    }
    if extracted_text:
        context["extracted_text"] = extracted_text

    return {
        "event_id": event_id,
        "session_id": "ses_test",
        "timestamp_ms": ts_ms,
        "timestamp_iso": f"2026-01-01T00:00:{ts_ms:02d}.000Z" if ts_ms < 60 else f"2026-01-01T00:{ts_ms//60:02d}:{ts_ms%60:02d}.000Z",
        "layer": layer,
        "event_type": event_type,
        "payload": payload,
        "correlation": correlation,
        "context": context,
    }


def mk_keys(chars, start_ms=0, **kw):
    """One plain keystroke event per character, 1ms apart."""
    return [
        mk_event(f"e{i}", start_ms + i, "keystroke", key=c, character=c, seq=start_ms + i, **kw)
        for i, c in enumerate(chars)
    ]


def type_and_get_text(events, config=None):
    config = config or Config()
    ops = normalize_events(events, config, Tracer())
    engine = TextRunEngine()
    clipboard = SessionClipboard()
    for op in ops:
        if op.op_type == "CLIPBOARD_CHANGE" and op.raw_event is not None:
            clipboard.observe_clipboard_change_event(op.raw_event)
        if op.op_type in (
            "INSERT", "BACKSPACE", "DELETE", "DELETE_WORD_BACK",
            "MOVE_LEFT", "MOVE_RIGHT", "MOVE_HOME", "MOVE_END",
            "SELECT_ALL", "COPY", "CUT", "PASTE", "UNDO", "REDO",
        ):
            engine.apply(op, clipboard, Tracer())
    return engine, clipboard


class TestBasicTyping(unittest.TestCase):
    def test_basic_typing(self):
        events = mk_keys(list("Hello"))
        engine, _ = type_and_get_text(events)
        self.assertEqual(engine.text(), "Hello")

    def test_real_duplicate_letters_are_kept(self):
        events = mk_keys(list("ll"))
        engine, _ = type_and_get_text(events)
        self.assertEqual(engine.text(), "ll")

    def test_oo_real_duplicate_preserved(self):
        events = mk_keys(list("OO"))
        engine, _ = type_and_get_text(events)
        self.assertEqual(engine.text(), "OO")


class TestCorrections(unittest.TestCase):
    def test_correction_o_o_backspace(self):
        events = mk_keys(["O"]) + mk_keys(["O"], start_ms=1) + [
            mk_event("e2", 2, "keystroke", key="Backspace", seq=2)
        ]
        engine, _ = type_and_get_text(events)
        self.assertEqual(engine.text(), "O")

    def test_multiple_correction(self):
        events = (
            mk_keys(["O"], start_ms=0)
            + mk_keys(["O"], start_ms=1)
            + mk_keys(["O"], start_ms=2)
            + [
                mk_event("e3", 3, "keystroke", key="Backspace", seq=3),
                mk_event("e4", 4, "keystroke", key="Backspace", seq=4),
            ]
        )
        engine, _ = type_and_get_text(events)
        self.assertEqual(engine.text(), "O")

    def test_correction_in_middle(self):
        events = mk_keys(list("hello"), start_ms=0)
        base = len(events)
        events += [
            mk_event(f"l{base}", base, "keystroke", key="Left", seq=base),
            mk_event(f"l{base+1}", base + 1, "keystroke", key="Left", seq=base + 1),
        ]
        events += mk_keys(["X"], start_ms=base + 2)
        engine, _ = type_and_get_text(events)
        self.assertEqual(engine.text(), "helXlo")

    def test_delete(self):
        events = mk_keys(list("abc"), start_ms=0)
        base = len(events)
        events += [
            mk_event(f"l{base}", base, "keystroke", key="Left", seq=base),
            mk_event(f"l{base+1}", base + 1, "keystroke", key="Left", seq=base + 1),
            mk_event(f"l{base+2}", base + 2, "keystroke", key="Left", seq=base + 2),
            mk_event(f"d{base+3}", base + 3, "keystroke", key="Delete", seq=base + 3),
        ]
        engine, _ = type_and_get_text(events)
        self.assertEqual(engine.text(), "bc")


class TestShortcutsAndEchoes(unittest.TestCase):
    def test_ctrl_a_replacement(self):
        events = mk_keys(list("old"), start_ms=0)
        base = len(events)
        events += [
            mk_event(f"ca{base}", base, "keystroke", key="a", character="a", ctrl=True, seq=base),
            mk_event(f"sc{base+1}", base + 1, "shortcut", ctrl=True, seq=base + 1),
            mk_event(f"ca_echo{base+2}", base + 2, "keystroke", key="a", character="a", ctrl=False, seq=base + 2),
        ]
        events += mk_keys(list("hello"), start_ms=base + 3)
        engine, _ = type_and_get_text(events)
        self.assertEqual(engine.text(), "hello")

    def test_shortcut_echo_collapses_to_one_paste_operation(self):
        events = [
            mk_event("v0", 0, "keystroke", key="v", character="v", ctrl=True, seq=0),
            mk_event("v1", 1, "shortcut", ctrl=True, seq=1),
            mk_event("v2", 2, "keystroke", key="v", character="v", ctrl=False, seq=2),
        ]
        config = Config()
        ops = normalize_events(events, config, Tracer())
        # exactly one logical operation should result, not three
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0].op_type, "PASTE")
        self.assertEqual(set(ops[0].source_event_ids), {"v0", "v1", "v2"})

    def test_recorder_duplicate_looking_pattern_stays_oo(self):
        # Two INDEPENDENT plain 'o' keystrokes (no modifier transition) must
        # never be collapsed, however close in time.
        events = [
            mk_event("o0", 0, "keystroke", key="o", character="o", seq=0),
            mk_event("o1", 0, "keystroke", key="o", character="o", seq=1),
        ]
        engine, _ = type_and_get_text(events)
        self.assertEqual(engine.text(), "oo")

    def test_recorder_correction_pattern_o_o_backspace(self):
        events = [
            mk_event("o0", 0, "keystroke", key="o", character="o", seq=0),
            mk_event("o1", 0, "keystroke", key="o", character="o", seq=1),
            mk_event("b2", 0, "keystroke", key="Backspace", seq=2),
        ]
        engine, _ = type_and_get_text(events)
        self.assertEqual(engine.text(), "o")


class TestPasteCutCopy(unittest.TestCase):
    def test_paste_with_known_clipboard(self):
        events = [
            mk_event(
                "cc0", 0, "clipboard_change",
                extra_payload={"content": "pasted-value"},
            ),
            mk_event("v1", 1, "keystroke", key="v", character="v", ctrl=True, seq=1),
            mk_event("v2", 2, "shortcut", ctrl=True, seq=2),
            mk_event("v3", 3, "keystroke", key="v", character="v", ctrl=False, seq=3),
        ]
        engine, clipboard = type_and_get_text(events)
        self.assertEqual(clipboard.content, "pasted-value")
        self.assertEqual(engine.text(), "pasted-value")

    def test_cut_removes_selection(self):
        events = mk_keys(list("hello world"), start_ms=0)
        base = len(events)
        events += [mk_event(f"sa{base}", base, "keystroke", key="a", character="a", ctrl=True, seq=base)]
        events += [
            mk_event(f"x{base+1}", base + 1, "keystroke", key="x", character="x", ctrl=True, seq=base + 1),
        ]
        engine, _ = type_and_get_text(events)
        self.assertEqual(engine.text(), "")

    def test_ctrl_backspace_deletes_word(self):
        events = mk_keys(list("hello world"), start_ms=0)
        base = len(events)
        events += [mk_event(f"cb{base}", base, "keystroke", key="Backspace", character=None, ctrl=True, seq=base)]
        engine, _ = type_and_get_text(events)
        self.assertEqual(engine.text(), "hello ")


class TestUndoRedo(unittest.TestCase):
    def test_undo(self):
        events = mk_keys(list("hello"), start_ms=0)
        base = len(events)
        events += [mk_event(f"bs{base}", base, "keystroke", key="Backspace", seq=base)]
        events += [
            mk_event(f"z{base+1}", base + 1, "keystroke", key="z", character="z", ctrl=True, seq=base + 1),
        ]
        engine, _ = type_and_get_text(events)
        self.assertEqual(engine.text(), "hello")

    def test_undo_then_redo(self):
        events = mk_keys(list("hello"), start_ms=0)
        base = len(events)
        events += [mk_event(f"bs{base}", base, "keystroke", key="Backspace", seq=base)]
        events += [mk_event(f"z{base+1}", base + 1, "keystroke", key="z", character="z", ctrl=True, seq=base + 1)]
        events += [mk_event(f"y{base+2}", base + 2, "keystroke", key="y", character="y", ctrl=True, seq=base + 2)]
        engine, _ = type_and_get_text(events)
        self.assertEqual(engine.text(), "hell")


class TestShift(unittest.TestCase):
    def test_shift_o_produces_single_o(self):
        events = [mk_event("s0", 0, "keystroke", key="o", character="O", shift=True, seq=0)]
        engine, _ = type_and_get_text(events)
        self.assertEqual(engine.text(), "O")

    def test_shift_echo_pattern_not_duplicated(self):
        # Shift+N followed by a redundant unmodified 'n' release echo,
        # linked via correlation.triggered_by -- must not become "Nn".
        events = [
            mk_event("s0", 0, "keystroke", key="n", character="N", shift=True, seq=0),
            mk_event("s1", 1, "keystroke", key="n", character="n", shift=False, seq=1, triggered_by="s0"),
        ]
        engine, _ = type_and_get_text(events)
        self.assertEqual(engine.text(), "N")

    def test_intentional_nn_without_correlation_link_is_kept(self):
        # Two genuinely independent N presses with no shift and no
        # triggered_by linkage back to a shift event must be kept as NN.
        events = [
            mk_event("s0", 0, "keystroke", key="n", character="N", shift=True, seq=0),
            mk_event("s1", 5000, "keystroke", key="n", character="n", shift=False, seq=99),
        ]
        engine, _ = type_and_get_text(events)
        self.assertEqual(engine.text(), "Nn")


class TestActivityGrouping(unittest.TestCase):
    def test_screenshot_between_keys_does_not_split(self):
        events = [
            mk_event("a0", 0, "keystroke", key="a", character="a", seq=0),
            mk_event("sc1", 1, "screenshot_smart", layer="L1", seq=1,
                      extra_payload={"file_reference": {"filename": "x.jpg"}}),
            mk_event("b2", 2, "keystroke", key="b", character="b", seq=2),
        ]
        activities = build_activities(events, "ses_test", Config(), Tracer())
        text_entries = [a for a in activities if a["type"] == "TEXT_ENTRY"]
        self.assertEqual(len(text_entries), 1)
        self.assertEqual(text_entries[0]["text"], "ab")

    def test_window_title_change_does_not_split(self):
        events = [
            mk_event("a0", 0, "keystroke", key="a", character="a", seq=0),
            mk_event("wt1", 1, "window_title_change", seq=1),
            mk_event("b2", 2, "keystroke", key="b", character="b", seq=2),
        ]
        activities = build_activities(events, "ses_test", Config(), Tracer())
        text_entries = [a for a in activities if a["type"] == "TEXT_ENTRY"]
        self.assertEqual(len(text_entries), 1)
        self.assertEqual(text_entries[0]["text"], "ab")

    def test_target_change_splits_activity(self):
        other_target = {"automation_id": "field-2", "class_name": "Edit", "control_type": "Edit"}
        events = mk_keys(list("ab"), start_ms=0)
        events += mk_keys(list("cd"), start_ms=2, target_field=other_target)
        activities = build_activities(events, "ses_test", Config(), Tracer())
        text_entries = [a for a in activities if a["type"] == "TEXT_ENTRY"]
        self.assertEqual(len(text_entries), 2)
        self.assertEqual(text_entries[0]["text"], "ab")
        self.assertEqual(text_entries[1]["text"], "cd")

    def test_app_switch_splits_activity_and_emits_app_switch(self):
        events = mk_keys(list("ab"), start_ms=0)
        events += [
            mk_event(
                "as2", 2, "app_switch",
                app_name="OtherApp", window_title="OtherWindow", seq=2,
                extra_payload={"new_app": "OtherApp", "previous_app": "TestApp"},
            )
        ]
        events += mk_keys(list("cd"), start_ms=3, app_name="OtherApp", window_title="OtherWindow")
        activities = build_activities(events, "ses_test", Config(), Tracer())
        types = [a["type"] for a in activities]
        self.assertIn("APP_SWITCH", types)
        text_entries = [a for a in activities if a["type"] == "TEXT_ENTRY"]
        self.assertEqual(len(text_entries), 2)

    def test_browser_checkpoint_reconciles(self):
        events = mk_keys(list("operator2@nttd.co.jp"), start_ms=0)
        base = len(events)
        events += [
            mk_event(
                f"bf{base}", base, "browser_form_input", layer="L3", seq=base,
                extra_payload={"value": "operator2@nttd.co.jp"},
            )
        ]
        activities = build_activities(events, "ses_test", Config(), Tracer())
        text_entries = [a for a in activities if a["type"] == "TEXT_ENTRY"]
        self.assertEqual(len(text_entries), 1)
        self.assertEqual(text_entries[0]["verification_status"], "VERIFIED_BROWSER")
        self.assertEqual(text_entries[0]["text"], "operator2@nttd.co.jp")

    def test_ocr_checkpoint_verifies_without_overwriting(self):
        events = mk_keys(list("operator2@nttd.co.jp"), start_ms=0)
        base = len(events)
        events += [
            mk_event(
                f"sc{base}", base, "screenshot_smart", layer="L1", seq=base,
                extracted_text="Employee ID  Name  Email  operator2@nttd.co.jp  Status: Pending",
            )
        ]
        activities = build_activities(events, "ses_test", Config(), Tracer())
        text_entries = [a for a in activities if a["type"] == "TEXT_ENTRY"]
        self.assertEqual(text_entries[0]["text"], "operator2@nttd.co.jp")
        self.assertEqual(text_entries[0]["verification_status"], "VERIFIED_SCREEN")


class TestDeterminism(unittest.TestCase):
    def test_same_input_same_output(self):
        events = mk_keys(list("Hello World"), start_ms=0)
        a1 = build_activities(events, "ses_test", Config(), Tracer())
        a2 = build_activities(events, "ses_test", Config(), Tracer())
        self.assertEqual(a1, a2)


if __name__ == "__main__":
    unittest.main()
