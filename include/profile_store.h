#pragma once

#include <Arduino.h>
#include <Preferences.h>

#include "macro_types.h"

// Board identity and wiring the app can change without reflashing.
struct DeviceSettings {
    char name[config::kMaxNameLength + 1] = {};
    uint8_t pins[config::kMaxButtons] = {};
    uint8_t buttonCount = 0;
    uint16_t debounceMs = config::kDefaultDebounceMs;
    uint16_t holdMs = config::kDefaultHoldMs;
};

class ProfileStore {
public:
    // Actions are stored for every slot so growing the button count keeps assignments.
    static constexpr uint8_t kButtonCount = config::kMaxButtons;

    void begin();
    const MacroAction& action(uint8_t number) const;
    bool setStaged(uint8_t number, ActionKind kind, const char* value);
    bool commitStaged();

    bool bleEnabled() const;
    void setBleEnabled(bool enabled);
    bool standalone() const { return standalone_; }
    void setStandalone(bool enabled);

    const DeviceSettings& device() const { return device_; }
    // Validates, persists, then reloads from NVS so the caller reports what was stored.
    const char* saveDevice(const DeviceSettings& settings);
    static const char* validateDevice(const DeviceSettings& settings);

private:
    static constexpr const char* kNamespace = "macropad";
    MacroAction actions_[kButtonCount]{};
    MacroAction staged_[kButtonCount]{};
    bool bleEnabled_ = true;
    bool standalone_ = false;
    DeviceSettings device_{};
    Preferences preferences_;

    void setDefaults();
    void loadDevice();
    void copyAction(MacroAction& destination, ActionKind kind, const char* value);
    bool validAction(ActionKind kind, const char* value) const;
};
