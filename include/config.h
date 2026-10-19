#pragma once

#include <Arduino.h>

namespace config {
// Each board env in platformio.ini sets its default wiring and name. The app can change
// both at runtime (saved in NVS); these are only the first-boot / factory values.
// Buttons connect between GPIO and GND; INPUT_PULLUP means LOW = pressed.
#ifndef MACROPAD_PINS
#define MACROPAD_PINS 3, 4, 5, 6
#endif
#ifndef MACROPAD_NAME
#define MACROPAD_NAME "timewo-macropad"
#endif
#ifndef MACROPAD_BOARD
#define MACROPAD_BOARD "macropad4"
#endif
constexpr char kFirmwareVersion[] = "0.11.0";
constexpr char kBoardId[] = MACROPAD_BOARD;
constexpr uint8_t kDefaultPins[] = {MACROPAD_PINS};
constexpr char kDefaultName[] = MACROPAD_NAME;
// shortcut: desktop profiles hold exactly 4 actions, raise both together for bigger boards.
constexpr uint8_t kMaxButtons = 4;
static_assert(sizeof(kDefaultPins) >= 1 && sizeof(kDefaultPins) <= kMaxButtons, "1 to 4 buttons");
// The hand-built advertising packet has room for exactly 15 name bytes (see ble_bridge.cpp).
constexpr size_t kMaxNameLength = 15;
static_assert(sizeof(kDefaultName) - 1 <= kMaxNameLength, "name must fit the advertisement");

constexpr uint16_t kDefaultDebounceMs = 30;
constexpr uint16_t kMinDebounceMs = 5;
constexpr uint16_t kMaxDebounceMs = 200;
constexpr uint16_t kDefaultHoldMs = 2500;
constexpr uint16_t kMinHoldMs = 500;
constexpr uint16_t kMaxHoldMs = 10000;

constexpr uint32_t kSerialBaud = 115200;
// The app renews its lease every second; after this long the board types by itself.
constexpr uint32_t kAppLeaseMs = 3000;
// Hold this button while powering on to forget every Bluetooth pairing.
constexpr uint8_t kBleForgetButton = 1;
constexpr size_t kActionValueCapacity = 513;
// Longest total of all "wait:<ms>" steps in one sequence.
constexpr uint32_t kMaxWaitMs = 3000;

// GPIOs that can take a button with the internal pull-up and are not used by flash,
// PSRAM or the native USB port of this chip.
#if defined(CONFIG_IDF_TARGET_ESP32C3)
constexpr uint64_t kUsablePins = 0x7FFULL | (1ULL << 20) | (1ULL << 21);
#elif defined(CONFIG_IDF_TARGET_ESP32S3)
constexpr uint64_t kUsablePins = 0x7FFFFULL | (1ULL << 21) | (0x7FFULL << 38);
#elif defined(CONFIG_IDF_TARGET_ESP32)
constexpr uint64_t kUsablePins = (1ULL << 0) | (1ULL << 2) | (1ULL << 4) | (1ULL << 5) |
                                 (0xFFULL << 12) | (0x7ULL << 21) | (0x7ULL << 25) |
                                 (1ULL << 32) | (1ULL << 33);
#else
#error "Unsupported chip: this firmware needs Bluetooth LE"
#endif

constexpr bool pinUsable(uint8_t pin) {
    return pin < 64 && ((kUsablePins >> pin) & 1ULL) != 0;
}
}  // namespace config
