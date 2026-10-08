"""Convert Qt keyboard events into the shortcut format used by the config parser."""

from PySide6.QtCore import Qt

_MODIFIER_KEYS = {
    Qt.Key.Key_Control,
    Qt.Key.Key_Alt,
    Qt.Key.Key_Shift,
    Qt.Key.Key_Meta,
}

_SPECIAL_KEYS = {
    Qt.Key.Key_Return: "Enter",
    Qt.Key.Key_Enter: "Enter",
    Qt.Key.Key_Tab: "Tab",
    Qt.Key.Key_Space: "Space",
    Qt.Key.Key_Backspace: "Backspace",
    Qt.Key.Key_Delete: "Delete",
    Qt.Key.Key_Insert: "Insert",
    Qt.Key.Key_Home: "Home",
    Qt.Key.Key_End: "End",
    Qt.Key.Key_PageUp: "Page_Up",
    Qt.Key.Key_PageDown: "Page_Down",
    Qt.Key.Key_Up: "Up",
    Qt.Key.Key_Down: "Down",
    Qt.Key.Key_Left: "Left",
    Qt.Key.Key_Right: "Right",
    Qt.Key.Key_CapsLock: "Caps_Lock",
    Qt.Key.Key_Print: "Print_Screen",
}
for _index in range(1, 25):
    _SPECIAL_KEYS[getattr(Qt.Key, f"Key_F{_index}")] = f"F{_index}"


def is_modifier_key(key: int) -> bool:
    """Return whether a Qt key is a modifier without a primary key."""
    return key in _MODIFIER_KEYS


def _primary_key(event) -> str:
    """Get one parser-compatible name for the non-modifier key in an event."""
    key = event.key()
    if key in _SPECIAL_KEYS:
        return _SPECIAL_KEYS[key]

    # Qt gives printable keys their text, which also preserves punctuation and
    # the active keyboard layout. ``plus`` avoids the parser's '+' separator.
    text = event.text()
    # With Ctrl/Alt held, Windows may provide a control character or empty
    # text. Qt's key code still contains the printable ASCII key.
    if not text.isascii() or not text.isprintable():
        text = chr(int(key)) if 0x20 <= int(key) <= 0x7E else text
        text = chr(int(key))
    if text and text.isascii() and text.isprintable():
        if text == "+":
            return "Plus"
        if text == " ":
            return "Space"
        return text.upper() if text.isalpha() else text

    raise ValueError("Không nhận ra phím này. Hãy nhấn một phím chính như S, F5 hoặc Enter.")


def shortcut_from_event(event) -> str:
    """Format a Qt key event as ``Ctrl+Shift+S`` for a single chord.

    Modifier-only key events return an empty string so a recorder can wait for
    the following primary key. A non-modifier event always contains exactly
    one primary key.
    """
    if is_modifier_key(event.key()):
        return ""

    modifiers = event.modifiers()
    names = []
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        names.append("Ctrl")
    if modifiers & Qt.KeyboardModifier.AltModifier:
        names.append("Alt")
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        names.append("Shift")
    if modifiers & Qt.KeyboardModifier.MetaModifier:
        names.append("Win")
    names.append(_primary_key(event))
    return "+".join(names)
