"""Keyboard recorder normalization tests."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

from macropad.config import parse_hotkey
from macropad.hotkeys import shortcut_from_event


def _event(key, modifiers=Qt.KeyboardModifier.NoModifier, text=""):
    return QKeyEvent(QEvent.Type.KeyPress, key, modifiers, text)


def test_common_chords_are_parser_compatible() -> None:
    cases = [
        (_event(Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier, chr(3)), "Ctrl+C"),
        (
            _event(
                Qt.Key.Key_S,
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
                chr(19),
            ),
            "Ctrl+Shift+S",
        ),
        (_event(Qt.Key.Key_F4, Qt.KeyboardModifier.AltModifier), "Alt+F4"),
        (_event(Qt.Key.Key_E, Qt.KeyboardModifier.MetaModifier, "e"), "Win+E"),
        (_event(Qt.Key.Key_F5), "F5"),
    ]
    for event, expected in cases:
        result = shortcut_from_event(event)
        assert result == expected
        parse_hotkey(result)


def test_special_and_plus_keys() -> None:
    assert shortcut_from_event(_event(Qt.Key.Key_Return)) == "Enter"
    assert shortcut_from_event(_event(Qt.Key.Key_Plus, text="+")) == "Plus"
    parse_hotkey("Ctrl+Plus")


def test_modifier_only_event_waits_for_primary_key() -> None:
    assert shortcut_from_event(_event(Qt.Key.Key_Control)) == ""
