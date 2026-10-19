#pragma once

#include <Arduino.h>

#include "button_scanner.h"
#include "macro_types.h"
#include "profile_store.h"

enum class UsbCommandType : uint8_t {
    None,
    Status,
    SyncAction,
    SyncCommit,
    SetBle,
    SetMode,
    AppLease,    // The app is running and will execute presses; renew every second.
    AppRelease,  // The app is closing; the board types locally right away.
    Info,        // Report chip, firmware, capabilities, limits and device settings.
    Dump,        // Report every stored action so the app can verify a save.
    SetConfig,   // Store name/wiring/timing, report it back, then restart.
};

struct UsbCommand {
    UsbCommandType type = UsbCommandType::None;
    uint8_t button = 0;
    ActionKind actionKind = ActionKind::None;
    bool bleEnabled = false;
    bool standalone = false;
    char value[config::kActionValueCapacity] = {};
    DeviceSettings device{};
};

class UsbProtocol {
public:
    bool update(UsbCommand& command);
    bool feed(uint8_t byte, UsbCommand& command);
    void resetInput(bool discard = false);
    bool connected() const;
    void printStatus(const ButtonScanner& buttons, const ProfileStore& profile, bool bleConnected) const;
    void printButton(const ButtonEvent& event, uint8_t pin, uint32_t pressCount) const;
    void printMessage(const char* message) const;
    void printInfo(const DeviceSettings& settings) const;
    void printConfig(const DeviceSettings& settings) const;
    void printActions(const ProfileStore& profile) const;

private:
    static constexpr size_t kLineCapacity = 2304;
    bool wasConnected_ = false;
    char line_[kLineCapacity]{};
    size_t lineLength_ = 0;
    bool discard_ = false;

    bool parseLine(UsbCommand& command);
    static void printHex(const char* text);
    static int hexValue(char value);
    static bool decodeHex(const char* source, char* destination, size_t capacity);
};
