#pragma once

#include <Arduino.h>
#include <BleKeyboard.h>

#include "macro_types.h"

class BleController {
public:
    void begin(bool enabled);
    bool enabled() const;
    bool connected();
    bool execute(const MacroAction& action);

private:
    bool enabled_ = false;
    BleKeyboard keyboard_{"timewo-macropad", "PhanNguyen", 100};

    bool executeHotkey(const char* value);
    bool executeSequence(const char* value);
    bool executeChord(const char* value);
    uint8_t keyCodeForName(const char* name, bool& isMedia);
    static void trim(char* text);
};
