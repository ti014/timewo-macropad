#pragma once

#include <Arduino.h>

namespace config {
// Temporary wiring: connect each normally-open button between its GPIO and GND.
// INPUT_PULLUP means LOW = pressed. Change this list to match your wiring.
constexpr uint8_t kButtonPins[] = {3, 4, 5, 6};
constexpr uint32_t kDebounceMs = 30;
constexpr uint32_t kSerialBaud = 115200;
constexpr uint8_t kBleToggleButton = 4;
constexpr uint32_t kBleToggleHoldMs = 2500;
constexpr size_t kActionValueCapacity = 513;
}  // namespace config
