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
    holdMask_ = 0;
    pairReported_ = false;
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
            if (state.stablePressed && isToggleButton(number) && !state.longReported && !state.swallowed &&
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
            // Second key of the pairing combo: neither key runs its action or toggles BLE.
            const uint8_t partner = pairPartner(number);
            state.swallowed = partner != 0 && states_[partner - 1].stablePressed;
            if (state.swallowed) {
                states_[partner - 1].swallowed = true;
                // The first key may already own a hold. Pairing swallows its later
                // release even when the combo is cancelled, so release ownership now.
                emit(handler, partner, ButtonEventType::Released, 0);
                emit(handler, number, ButtonEventType::Released, 0);
            }
            if (!isToggleButton(number) && !state.swallowed) {
                emit(handler, number, ButtonEventType::Pressed, 0);
            }
            continue;
        }

        const uint32_t heldMs = static_cast<uint32_t>(now - state.pressedAtMs);
        if (state.swallowed) continue;
        if (isToggleButton(number)) {
            if (!state.longReported) {
                emit(handler, number, ButtonEventType::Pressed, heldMs);
                emit(handler, number, ButtonEventType::Released, heldMs);
            }
        } else {
            emit(handler, number, ButtonEventType::Released, heldMs);
        }
    }
    checkPair(now, handler);
}

uint8_t ButtonScanner::pairPartner(uint8_t number) const {
    const uint8_t first = config::kPairButtons[0], second = config::kPairButtons[1];
    if (first == second || first > settings_.buttonCount || second > settings_.buttonCount) return 0;
    if (number == first) return second;
    if (number == second) return first;
    return 0;
}

void ButtonScanner::checkPair(uint32_t now, ButtonEventHandler handler) {
    const uint8_t first = config::kPairButtons[0];
    const uint8_t second = pairPartner(first);
    if (second == 0) return;
    const State& a = states_[first - 1];
    const State& b = states_[second - 1];
    if (!a.stablePressed || !b.stablePressed) {
        pairReported_ = false;
        return;
    }
    // Both swallowed means one went down while the other was held, i.e. a real combo.
    const uint32_t held = min(now - a.pressedAtMs, now - b.pressedAtMs);
    if (!pairReported_ && a.swallowed && b.swallowed && held >= settings_.holdMs) {
        pairReported_ = true;
        emit(handler, second, ButtonEventType::PairRequested, held);
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
