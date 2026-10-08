#include "ble_controller.h"

#include <cstring>
#include <cstdlib>

namespace {
constexpr uint32_t kInterKeyDelayMs = 8;

bool equalsIgnoreCase(const char* left, const char* right) {
    while (*left != '\0' && *right != '\0') {
        char a = *left++;
        char b = *right++;
        if (a >= 'A' && a <= 'Z') a = static_cast<char>(a + ('a' - 'A'));
        if (b >= 'A' && b <= 'Z') b = static_cast<char>(b + ('a' - 'A'));
        if (a != b) return false;
    }
    return *left == '\0' && *right == '\0';
}

bool isModifier(const char* name) {
    return equalsIgnoreCase(name, "ctrl") || equalsIgnoreCase(name, "control") ||
           equalsIgnoreCase(name, "shift") || equalsIgnoreCase(name, "alt") ||
           equalsIgnoreCase(name, "cmd") || equalsIgnoreCase(name, "win") ||
           equalsIgnoreCase(name, "windows");
}

uint8_t functionKey(const char* name) {
    if (name[0] != 'F' && name[0] != 'f') return 0;
    char* end = nullptr;
    const long number = strtol(name + 1, &end, 10);
    return *end == '\0' && number >= 1 && number <= 24
               ? static_cast<uint8_t>(KEY_F1 + number - 1)
               : 0;
}
}  // namespace

void BleController::begin(bool enabled) {
    enabled_ = enabled;
    if (enabled_) {
        keyboard_.setDelay(kInterKeyDelayMs);
        keyboard_.begin();
    }
}

bool BleController::enabled() const {
    return enabled_;
}

bool BleController::connected() {
    return enabled_ && keyboard_.isConnected();
}

bool BleController::execute(const MacroAction& action) {
    if (!connected()) return false;
    switch (action.kind) {
        case ActionKind::None:
            return true;
        case ActionKind::Hotkey:
            return executeHotkey(action.value);
        case ActionKind::Sequence:
            return executeSequence(action.value);
        case ActionKind::Text:
            keyboard_.print(action.value);
            return true;
        case ActionKind::LockScreen:
            return executeHotkey("Win+L");
        case ActionKind::CloseApp:
            return executeHotkey("Alt+F4");
        default:
            // OS actions such as opening an app or locking the session belong to the host app.
            return false;
    }
}

bool BleController::executeHotkey(const char* value) {
    char copy[config::kActionValueCapacity];
    strncpy(copy, value, sizeof(copy) - 1);
    copy[sizeof(copy) - 1] = '\0';
    return executeChord(copy);
}

bool BleController::executeSequence(const char* value) {
    char copy[config::kActionValueCapacity];
    strncpy(copy, value, sizeof(copy) - 1);
    copy[sizeof(copy) - 1] = '\0';
    char* cursor = copy;
    while (cursor != nullptr && *cursor != '\0') {
        char* next = strchr(cursor, ',');
        if (next != nullptr) *next++ = '\0';
        trim(cursor);
        if (!executeChord(cursor)) return false;
        cursor = next;
        if (cursor != nullptr) delay(kInterKeyDelayMs);
    }
    return true;
}

bool BleController::executeChord(const char* value) {
    char copy[96];
    strncpy(copy, value, sizeof(copy) - 1);
    copy[sizeof(copy) - 1] = '\0';
    uint8_t pressed[6]{};
    size_t pressedCount = 0;
    bool mediaUsed = false;
    char* token = copy;
    bool ok = true;
    while (token != nullptr && *token != '\0') {
        char* next = strchr(token, '+');
        if (next != nullptr) *next++ = '\0';
        trim(token);
        bool media = false;
        if (isModifier(token)) {
            uint8_t key = equalsIgnoreCase(token, "ctrl") || equalsIgnoreCase(token, "control")
                              ? KEY_LEFT_CTRL
                          : equalsIgnoreCase(token, "shift") ? KEY_LEFT_SHIFT
                          : equalsIgnoreCase(token, "alt") ? KEY_LEFT_ALT
                                                            : KEY_LEFT_GUI;
            keyboard_.press(key);
            pressed[pressedCount++] = key;
        } else {
            const uint8_t key = keyCodeForName(token, media);
            if (media) {
                if (pressedCount != 0) ok = false;
                mediaUsed = true;
                break;
            }
            if (key == 0) {
                ok = false;
                break;
            }
            keyboard_.press(key);
            pressed[pressedCount++] = key;
        }
        token = next;
    }
    keyboard_.releaseAll();
    return ok && (mediaUsed || pressedCount > 0);
}

uint8_t BleController::keyCodeForName(const char* name, bool& isMedia) {
    isMedia = false;
    if (strlen(name) == 1) {
        char key = name[0];
        if (key >= 'A' && key <= 'Z') key = static_cast<char>(key + ('a' - 'A'));
        return static_cast<uint8_t>(key);
    }
    const uint8_t function = functionKey(name);
    if (function != 0) return function;
    if (equalsIgnoreCase(name, "enter") || equalsIgnoreCase(name, "return")) {
        return KEY_RETURN;
    }
    if (equalsIgnoreCase(name, "tab")) return KEY_TAB;
    if (equalsIgnoreCase(name, "space")) return ' ';
    if (equalsIgnoreCase(name, "backspace")) return KEY_BACKSPACE;
    if (equalsIgnoreCase(name, "delete")) return KEY_DELETE;
    if (equalsIgnoreCase(name, "insert")) return KEY_INSERT;
    if (equalsIgnoreCase(name, "home")) return KEY_HOME;
    if (equalsIgnoreCase(name, "end")) return KEY_END;
    if (equalsIgnoreCase(name, "page_up") || equalsIgnoreCase(name, "pageup")) return KEY_PAGE_UP;
    if (equalsIgnoreCase(name, "page_down") || equalsIgnoreCase(name, "pagedown")) return KEY_PAGE_DOWN;
    if (equalsIgnoreCase(name, "up") || equalsIgnoreCase(name, "down") ||
        equalsIgnoreCase(name, "left") || equalsIgnoreCase(name, "right")) {
        if (equalsIgnoreCase(name, "up")) return KEY_UP_ARROW;
        if (equalsIgnoreCase(name, "down")) return KEY_DOWN_ARROW;
        if (equalsIgnoreCase(name, "left")) return KEY_LEFT_ARROW;
        return KEY_RIGHT_ARROW;
    }
    if (equalsIgnoreCase(name, "esc") || equalsIgnoreCase(name, "escape")) return KEY_ESC;
    if (equalsIgnoreCase(name, "print_screen") || equalsIgnoreCase(name, "prtsc")) return KEY_PRTSC;
    if (equalsIgnoreCase(name, "caps_lock")) return KEY_CAPS_LOCK;
    if (equalsIgnoreCase(name, "media_volume_up")) {
        keyboard_.write(KEY_MEDIA_VOLUME_UP);
        isMedia = true;
        return 0;
    }
    if (equalsIgnoreCase(name, "media_volume_down")) {
        keyboard_.write(KEY_MEDIA_VOLUME_DOWN);
        isMedia = true;
        return 0;
    }
    if (equalsIgnoreCase(name, "media_volume_mute")) {
        keyboard_.write(KEY_MEDIA_MUTE);
        isMedia = true;
        return 0;
    }
    if (equalsIgnoreCase(name, "media_play_pause")) {
        keyboard_.write(KEY_MEDIA_PLAY_PAUSE);
        isMedia = true;
        return 0;
    }
    if (equalsIgnoreCase(name, "plus")) return '+';
    return 0;
}

void BleController::trim(char* text) {
    char* start = text;
    while (*start == ' ' || *start == '\t') ++start;
    if (start != text) memmove(text, start, strlen(start) + 1);
    char* end = text + strlen(text);
    while (end > text && (end[-1] == ' ' || end[-1] == '\t')) --end;
    *end = '\0';
}
