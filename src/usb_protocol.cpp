#include "usb_protocol.h"

#include <cstring>

namespace {
bool equals(const char* left, const char* right) {
    return strcmp(left, right) == 0;
}

bool parseUnsigned(const char* text, uint32_t& result) {
    if (text == nullptr || *text == '\0') return false;
    char* end = nullptr;
    const unsigned long value = strtoul(text, &end, 10);
    if (*end != '\0' || value > 0xFFFFFFFFUL) return false;
    result = static_cast<uint32_t>(value);
    return true;
}
}  // namespace

bool UsbProtocol::update(UsbCommand& command) {
    command = UsbCommand{};
    const bool nowConnected = static_cast<bool>(Serial);
    if (nowConnected && !wasConnected_) {
        lineLength_ = 0;
        wasConnected_ = true;
    } else if (!nowConnected) {
        wasConnected_ = false;
        lineLength_ = 0;
        return false;
    }

    if (Serial.available() <= 0) return false;
    return feed(static_cast<uint8_t>(Serial.read()), command);
}

void UsbProtocol::resetInput(bool discard) {
    lineLength_ = 0;
    discard_ = discard;
}

bool UsbProtocol::feed(uint8_t byte, UsbCommand& command) {
    command = UsbCommand{};
    const char input = static_cast<char>(byte);
    if (discard_) {
        if (input == '\n') resetInput();
        return false;
    }
    if (input == '?') {
        command.type = UsbCommandType::Status;
        return true;
    }
    if (input == '\r') return false;
    if (input != '\n') {
        if (lineLength_ + 1 < sizeof(line_)) {
            line_[lineLength_++] = input;
        } else {
            resetInput(true);
        }
        return false;
    }

    line_[lineLength_] = '\0';
    const bool parsed = parseLine(command);
    lineLength_ = 0;
    return parsed;
}

bool UsbProtocol::connected() const {
    return static_cast<bool>(Serial);
}

void UsbProtocol::printStatus(const ButtonScanner& buttons, const ProfileStore& profile,
                              bool bleConnected) const {
    if (!connected()) return;
    Serial.println("ESP32-C3 macropad: 4-button test ready.");
    Serial.printf("BLE %s%s\n", profile.bleEnabled() ? "ON" : "OFF",
                  bleConnected ? " CONNECTED" : "");
    Serial.println("Send '?' to show current state and press counts.");
    for (uint8_t number = 1; number <= ProfileStore::kButtonCount; ++number) {
        Serial.printf("BTN%u GPIO%u %s count=%lu\n", static_cast<unsigned>(number),
                      static_cast<unsigned>(config::kButtonPins[number - 1]),
                      buttons.pressed(number) ? "PRESSED" : "RELEASED",
                      static_cast<unsigned long>(buttons.pressCount(number)));
    }
}

void UsbProtocol::printButton(const ButtonEvent& event, uint32_t pressCount) const {
    if (!connected()) return;
    const char* state = event.type == ButtonEventType::Pressed ? "PRESSED" : "RELEASED";
    Serial.printf("BTN%u GPIO%u %s count=%lu\n", static_cast<unsigned>(event.number),
                  static_cast<unsigned>(config::kButtonPins[event.number - 1]), state,
                  static_cast<unsigned long>(pressCount));
}

void UsbProtocol::printMessage(const char* message) const {
    if (connected()) Serial.println(message);
}

bool UsbProtocol::parseLine(UsbCommand& command) {
    char* verb = strtok(line_, " \t");
    if (verb == nullptr) return false;
    if (equals(verb, "MODE")) {
        const char* mode = strtok(nullptr, " \t");
        if (!mode || strtok(nullptr, " \t") != nullptr) return false;
        if (!equals(mode, "APP") && !equals(mode, "HID")) return false;
        command.type = UsbCommandType::SetMode;
        command.standalone = equals(mode, "HID");
        return true;
    }
    if (equals(verb, "APP")) {
        const char* value = strtok(nullptr, " \t");
        if (value == nullptr) {
            command.type = UsbCommandType::AppLease;
            return true;
        }
        if (!equals(value, "OFF") || strtok(nullptr, " \t") != nullptr) return false;
        command.type = UsbCommandType::AppRelease;
        return true;
    }
    if (equals(verb, "SYNC_COMMIT")) {
        command.type = UsbCommandType::SyncCommit;
        return true;
    }
    if (equals(verb, "BLE")) {
        char* value = strtok(nullptr, " \t");
        if (value == nullptr) return false;
        if (equals(value, "ON")) command.bleEnabled = true;
        else if (equals(value, "OFF")) command.bleEnabled = false;
        else return false;
        command.type = UsbCommandType::SetBle;
        return true;
    }
    if (!equals(verb, "SYNC")) return false;
    char* buttonText = strtok(nullptr, " \t");
    char* kindText = strtok(nullptr, " \t");
    char* encoded = strtok(nullptr, " \t");
    uint32_t button = 0;
    uint32_t kind = 0;
    if (!parseUnsigned(buttonText, button) || !parseUnsigned(kindText, kind) ||
        button < 1 || button > ProfileStore::kButtonCount || kind > 8 || encoded == nullptr ||
        !(equals(encoded, "-") || decodeHex(encoded, command.value, sizeof(command.value)))) {
        return false;
    }
    if (equals(encoded, "-")) command.value[0] = '\0';
    command.type = UsbCommandType::SyncAction;
    command.button = static_cast<uint8_t>(button);
    command.actionKind = static_cast<ActionKind>(kind);
    return true;
}

int UsbProtocol::hexValue(char value) {
    if (value >= '0' && value <= '9') return value - '0';
    if (value >= 'a' && value <= 'f') return value - 'a' + 10;
    if (value >= 'A' && value <= 'F') return value - 'A' + 10;
    return -1;
}

bool UsbProtocol::decodeHex(const char* source, char* destination, size_t capacity) {
    const size_t length = strlen(source);
    if ((length & 1U) != 0 || length / 2 >= capacity) return false;
    for (size_t i = 0; i < length; i += 2) {
        const int high = hexValue(source[i]);
        const int low = hexValue(source[i + 1]);
        if (high < 0 || low < 0) return false;
        destination[i / 2] = static_cast<char>((high << 4) | low);
    }
    destination[length / 2] = '\0';
    return true;
}
