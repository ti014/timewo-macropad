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

    // Drain what has arrived instead of one byte per loop: a hex SYNC line can be 1 KB.
    while (Serial.available() > 0) {
        if (feed(static_cast<uint8_t>(Serial.read()), command)) return true;
    }
    return false;
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
    Serial.printf("ESP32 macropad: %u-button test ready.\n", static_cast<unsigned>(buttons.count()));
    Serial.printf("BLE %s%s\n", profile.bleEnabled() ? "ON" : "OFF",
                  bleConnected ? " CONNECTED" : "");
    Serial.println("Send '?' to show current state and press counts.");
    for (uint8_t number = 1; number <= buttons.count(); ++number) {
        Serial.printf("BTN%u GPIO%u %s count=%lu\n", static_cast<unsigned>(number),
                      static_cast<unsigned>(buttons.pin(number)),
                      buttons.pressed(number) ? "PRESSED" : "RELEASED",
                      static_cast<unsigned long>(buttons.pressCount(number)));
    }
}

void UsbProtocol::printButton(const ButtonEvent& event, uint8_t pin, uint32_t pressCount) const {
    if (!connected()) return;
    const char* state = event.type == ButtonEventType::Pressed ? "PRESSED" : "RELEASED";
    Serial.printf("BTN%u GPIO%u %s count=%lu\n", static_cast<unsigned>(event.number),
                  static_cast<unsigned>(pin), state, static_cast<unsigned long>(pressCount));
}

void UsbProtocol::printHex(const char* text) {
    if (*text == '\0') {
        Serial.print('-');
        return;
    }
    for (; *text != '\0'; ++text) Serial.printf("%02X", static_cast<uint8_t>(*text));
}

void UsbProtocol::printConfig(const DeviceSettings& settings) const {
    if (!connected()) return;
    Serial.print("CONFIG ");
    printHex(settings.name);
    Serial.print(' ');
    for (uint8_t i = 0; i < settings.buttonCount; ++i) {
        Serial.printf(i == 0 ? "%u" : ",%u", static_cast<unsigned>(settings.pins[i]));
    }
    Serial.printf(" %u %u\n", static_cast<unsigned>(settings.debounceMs),
                  static_cast<unsigned>(settings.holdMs));
}

void UsbProtocol::printInfo(const DeviceSettings& settings) const {
    if (!connected()) return;
    Serial.printf("DEVICE 1 %s %s %s\n", CONFIG_IDF_TARGET, config::kFirmwareVersion,
                  config::kBoardId);
    // What this firmware can do on its own; the app hides the rest for this board.
    Serial.println("CAPS ble_hid hotkey sequence wait media lock_screen close_app");
    Serial.printf("LIMITS %u %u %u %u %u %u %u\n", static_cast<unsigned>(config::kMaxButtons),
                  static_cast<unsigned>(config::kActionValueCapacity - 1),
                  static_cast<unsigned>(config::kMaxNameLength),
                  static_cast<unsigned>(config::kMinDebounceMs),
                  static_cast<unsigned>(config::kMaxDebounceMs),
                  static_cast<unsigned>(config::kMinHoldMs),
                  static_cast<unsigned>(config::kMaxHoldMs));
    Serial.print("PINS_OK");
    char separator = ' ';
    for (uint8_t pin = 0; pin < 64; ++pin) {
        if (!config::pinUsable(pin)) continue;
        Serial.printf("%c%u", separator, static_cast<unsigned>(pin));
        separator = ',';
    }
    Serial.println();
    printConfig(settings);
    Serial.println("INFO END");
}

void UsbProtocol::printActions(const ProfileStore& profile) const {
    if (!connected()) return;
    for (uint8_t number = 1; number <= ProfileStore::kButtonCount; ++number) {
        const MacroAction& action = profile.action(number);
        Serial.printf("ACT %u %u ", static_cast<unsigned>(number),
                      static_cast<unsigned>(action.kind));
        printHex(action.value);
        Serial.println();
    }
    Serial.println("DUMP END");
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
    if (equals(verb, "SYNC_COMMIT") || equals(verb, "INFO") || equals(verb, "DUMP")) {
        if (strtok(nullptr, " \t") != nullptr) return false;
        command.type = equals(verb, "INFO")   ? UsbCommandType::Info
                       : equals(verb, "DUMP") ? UsbCommandType::Dump
                                              : UsbCommandType::SyncCommit;
        return true;
    }
    if (equals(verb, "CFG")) {
        // CFG <name hex> <pin,pin,...> <debounce ms> <hold ms>
        char* name = strtok(nullptr, " \t");
        char* pins = strtok(nullptr, " \t");
        char* debounceText = strtok(nullptr, " \t");
        char* holdText = strtok(nullptr, " \t");
        uint32_t debounce = 0;
        uint32_t hold = 0;
        DeviceSettings& device = command.device;
        if (name == nullptr || pins == nullptr || strtok(nullptr, " \t") != nullptr ||
            !decodeHex(name, device.name, sizeof(device.name)) ||
            !parseUnsigned(debounceText, debounce) || !parseUnsigned(holdText, hold) ||
            debounce > 0xFFFF || hold > 0xFFFF) {
            return false;
        }
        for (char* cursor = pins; *cursor != '\0';) {
            char* end = nullptr;
            const unsigned long pin = strtoul(cursor, &end, 10);
            if (end == cursor || pin > 255 || device.buttonCount >= config::kMaxButtons) {
                return false;
            }
            device.pins[device.buttonCount++] = static_cast<uint8_t>(pin);
            if (*end == ',') ++end;
            else if (*end != '\0') return false;
            cursor = end;
        }
        device.debounceMs = static_cast<uint16_t>(debounce);
        device.holdMs = static_cast<uint16_t>(hold);
        command.type = UsbCommandType::SetConfig;
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
        button < 1 || button > ProfileStore::kButtonCount || kind > 9 || encoded == nullptr ||
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
