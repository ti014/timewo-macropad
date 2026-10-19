#pragma once

#include <Arduino.h>
#include <BleKeyboard.h>

#include "macro_types.h"
#include "ble_bridge.h"

class BleController {
public:
    void begin(const char* name, bool enabled, bool forgetBonds = false);
    bool enabled() const;
    bool connected();
    bool execute(const MacroAction& action);
    void setEnabled(bool enabled);
    BridgeKeyboard& bridge() { return keyboard_; }

private:
    bool enabled_ = false;
    BridgeKeyboard keyboard_;

    bool executeHotkey(const char* value);
    bool executeSequence(const char* value);
    bool executeChord(const char* value);
    uint8_t keyCodeForName(const char* name, bool& isMedia);
    static void trim(char* text);
};
