#pragma once

#include <Arduino.h>

#include "profile_store.h"

enum class ButtonEventType : uint8_t {
    Pressed,
    Released,
    LongPressed,
};

struct ButtonEvent {
    uint8_t number = 0;
    ButtonEventType type = ButtonEventType::Released;
    uint32_t heldMs = 0;
};

using ButtonEventHandler = void (*)(const ButtonEvent& event);

class ButtonScanner {
public:
    void begin(const DeviceSettings& settings);
    void update(uint32_t now, ButtonEventHandler handler);
    uint32_t pressCount(uint8_t number) const;
    bool pressed(uint8_t number) const;
    uint8_t count() const { return settings_.buttonCount; }
    uint8_t pin(uint8_t number) const;

private:
    struct State {
        bool rawPressed = false;
        bool stablePressed = false;
        bool longReported = false;
        uint32_t lastChangeMs = 0;
        uint32_t pressedAtMs = 0;
        uint32_t pressCount = 0;
    };

    DeviceSettings settings_{};
    State states_[config::kMaxButtons]{};

    // The last button doubles as the Bluetooth on/off switch when held.
    bool isToggleButton(uint8_t number) const { return number == settings_.buttonCount; }
};
