#pragma once

#include <Arduino.h>

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
    void begin();
    void update(uint32_t now, ButtonEventHandler handler);
    uint32_t pressCount(uint8_t number) const;
    bool pressed(uint8_t number) const;

private:
    struct State {
        bool rawPressed = false;
        bool stablePressed = false;
        bool longReported = false;
        uint32_t lastChangeMs = 0;
        uint32_t pressedAtMs = 0;
        uint32_t pressCount = 0;
    };

    State states_[4]{};
};
