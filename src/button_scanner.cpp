#include "button_scanner.h"

#include "config.h"

namespace {
void emit(ButtonEventHandler handler, uint8_t number, ButtonEventType type, uint32_t heldMs) {
    if (handler != nullptr) {
        ButtonEvent event;
        event.number = number;
        event.type = type;
        event.heldMs = heldMs;
        handler(event);
    }
}
}  // namespace

void ButtonScanner::begin(const DeviceSettings& settings) {
    settings_ = settings;
    const uint32_t now = millis();
    for (size_t i = 0; i < settings_.buttonCount; ++i) {
        pinMode(settings_.pins[i], INPUT_PULLUP);
        const bool pressed = digitalRead(settings_.pins[i]) == LOW;
        states_[i].rawPressed = pressed;
        states_[i].stablePressed = pressed;
        states_[i].lastChangeMs = now;
        states_[i].pressedAtMs = now;
        // Held at power-on (boot gesture or a stuck switch): ignore it until
        // released, so it can neither run a macro nor toggle Bluetooth.
        states_[i].longReported = pressed;
    }
}

void ButtonScanner::update(uint32_t now, ButtonEventHandler handler) {
    for (size_t i = 0; i < settings_.buttonCount; ++i) {
        State& state = states_[i];
        const uint8_t number = static_cast<uint8_t>(i + 1);
        const bool rawPressed = digitalRead(settings_.pins[i]) == LOW;

        if (rawPressed != state.rawPressed) {
            state.rawPressed = rawPressed;
            state.lastChangeMs = now;
        }
        if (state.rawPressed == state.stablePressed ||
            static_cast<uint32_t>(now - state.lastChangeMs) < settings_.debounceMs) {
            if (state.stablePressed && isToggleButton(number) && !state.longReported &&
                static_cast<uint32_t>(now - state.pressedAtMs) >= settings_.holdMs) {
                state.longReported = true;
                emit(handler, number, ButtonEventType::LongPressed,
                     static_cast<uint32_t>(now - state.pressedAtMs));
            }
            continue;
        }

        state.stablePressed = state.rawPressed;
        if (state.stablePressed) {
            state.pressedAtMs = now;
            state.longReported = false;
            ++state.pressCount;
            if (!isToggleButton(number)) {
                emit(handler, number, ButtonEventType::Pressed, 0);
            }
            continue;
        }

        const uint32_t heldMs = static_cast<uint32_t>(now - state.pressedAtMs);
        if (isToggleButton(number)) {
            if (!state.longReported) {
                emit(handler, number, ButtonEventType::Pressed, heldMs);
                emit(handler, number, ButtonEventType::Released, heldMs);
            }
        } else {
            emit(handler, number, ButtonEventType::Released, heldMs);
        }
    }
}

uint32_t ButtonScanner::pressCount(uint8_t number) const {
    return number >= 1 && number <= settings_.buttonCount ? states_[number - 1].pressCount : 0;
}

bool ButtonScanner::pressed(uint8_t number) const {
    return number >= 1 && number <= settings_.buttonCount && states_[number - 1].stablePressed;
}

uint8_t ButtonScanner::pin(uint8_t number) const {
    return number >= 1 && number <= settings_.buttonCount ? settings_.pins[number - 1] : 0;
}
