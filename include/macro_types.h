#pragma once

#include <Arduino.h>

#include "config.h"

enum class ActionKind : uint8_t {
    None = 0,
    Hotkey = 1,
    Text = 2,
    Sequence = 3,
    LockScreen = 4,
    Screenshot = 5,
    CloseApp = 6,
    App = 7,
    Url = 8,
    Script = 9,  // Runs a script on the computer; the board only reports the press.
};

struct MacroAction {
    ActionKind kind = ActionKind::None;
    char value[config::kActionValueCapacity] = {};
};
