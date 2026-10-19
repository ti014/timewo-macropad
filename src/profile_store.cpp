#include "profile_store.h"

#include <cstring>

namespace {
constexpr const char* kBleKey = "ble";
}

void ProfileStore::begin() {
    setDefaults();
    preferences_.begin(kNamespace, false);
    bleEnabled_ = preferences_.getBool(kBleKey, true);
    standalone_ = preferences_.getBool("standalone", false);

    for (uint8_t i = 0; i < kButtonCount; ++i) {
        char kindKey[8];
        char valueKey[8];
        snprintf(kindKey, sizeof(kindKey), "k%u", static_cast<unsigned>(i));
        snprintf(valueKey, sizeof(valueKey), "v%u", static_cast<unsigned>(i));
        const uint8_t rawKind = preferences_.getUChar(kindKey, static_cast<uint8_t>(actions_[i].kind));
        const String value = preferences_.getString(valueKey, actions_[i].value);
        const ActionKind kind = static_cast<ActionKind>(rawKind);
        if (validAction(kind, value.c_str())) {
            copyAction(actions_[i], kind, value.c_str());
        }
    }
    memcpy(staged_, actions_, sizeof(actions_));
    loadDevice();
}

void ProfileStore::loadDevice() {
    DeviceSettings defaults;
    strncpy(defaults.name, config::kDefaultName, config::kMaxNameLength);
    defaults.buttonCount = sizeof(config::kDefaultPins);
    memcpy(defaults.pins, config::kDefaultPins, sizeof(config::kDefaultPins));

    DeviceSettings stored = defaults;
    const String name = preferences_.getString("name", defaults.name);
    strncpy(stored.name, name.c_str(), config::kMaxNameLength);
    stored.name[config::kMaxNameLength] = '\0';
    if (preferences_.isKey("pins")) {
        stored.buttonCount = static_cast<uint8_t>(
            preferences_.getBytes("pins", stored.pins, sizeof(stored.pins)));
    }
    stored.debounceMs = preferences_.getUShort("debounce", defaults.debounceMs);
    stored.holdMs = preferences_.getUShort("hold", defaults.holdMs);
    // Corrupt or out-of-range NVS must never leave the board without working buttons.
    device_ = validateDevice(stored) == nullptr ? stored : defaults;
}

const char* ProfileStore::validateDevice(const DeviceSettings& settings) {
    const size_t nameLength = strnlen(settings.name, sizeof(settings.name));
    if (nameLength == 0 || nameLength > config::kMaxNameLength) return "name";
    for (size_t i = 0; i < nameLength; ++i) {
        const uint8_t c = static_cast<uint8_t>(settings.name[i]);
        if (c < 0x20 || c == 0x7F) return "name";
    }
    if (settings.buttonCount < 1 || settings.buttonCount > config::kMaxButtons) return "count";
    for (uint8_t i = 0; i < settings.buttonCount; ++i) {
        if (!config::pinUsable(settings.pins[i])) return "pin";
        for (uint8_t j = 0; j < i; ++j) {
            if (settings.pins[i] == settings.pins[j]) return "duplicate";
        }
    }
    if (settings.debounceMs < config::kMinDebounceMs ||
        settings.debounceMs > config::kMaxDebounceMs) {
        return "debounce";
    }
    if (settings.holdMs < config::kMinHoldMs || settings.holdMs > config::kMaxHoldMs) return "hold";
    return nullptr;
}

const char* ProfileStore::saveDevice(const DeviceSettings& settings) {
    const char* error = validateDevice(settings);
    if (error != nullptr) return error;
    if (preferences_.putString("name", settings.name) == 0 ||
        preferences_.putBytes("pins", settings.pins, settings.buttonCount) != settings.buttonCount ||
        preferences_.putUShort("debounce", settings.debounceMs) == 0 ||
        preferences_.putUShort("hold", settings.holdMs) == 0) {
        return "storage";
    }
    loadDevice();
    return nullptr;
}

const MacroAction& ProfileStore::action(uint8_t number) const {
    static const MacroAction empty{};
    return number >= 1 && number <= kButtonCount ? actions_[number - 1] : empty;
}

bool ProfileStore::setStaged(uint8_t number, ActionKind kind, const char* value) {
    if (number < 1 || number > kButtonCount || value == nullptr || !validAction(kind, value)) {
        return false;
    }
    copyAction(staged_[number - 1], kind, value);
    return true;
}

bool ProfileStore::commitStaged() {
    for (uint8_t i = 0; i < kButtonCount; ++i) {
        char kindKey[8];
        char valueKey[8];
        snprintf(kindKey, sizeof(kindKey), "k%u", static_cast<unsigned>(i));
        snprintf(valueKey, sizeof(valueKey), "v%u", static_cast<unsigned>(i));
        // The app syncs on every save and connect; skip unchanged entries to spare flash.
        if (staged_[i].kind == actions_[i].kind && strcmp(staged_[i].value, actions_[i].value) == 0) {
            continue;
        }
        preferences_.putUChar(kindKey, static_cast<uint8_t>(staged_[i].kind));
        preferences_.putString(valueKey, staged_[i].value);
    }
    memcpy(actions_, staged_, sizeof(actions_));
    return true;
}

bool ProfileStore::bleEnabled() const {
    return bleEnabled_;
}

void ProfileStore::setBleEnabled(bool enabled) {
    if (bleEnabled_ == enabled) return;
    bleEnabled_ = enabled;
    preferences_.putBool(kBleKey, enabled);
}

void ProfileStore::setStandalone(bool enabled) {
    if (standalone_ == enabled) return;
    standalone_ = enabled;
    preferences_.putBool("standalone", enabled);
}

void ProfileStore::setDefaults() {
    static const char* const defaults[] = {"Ctrl+C", "Ctrl+V", "Alt+Tab", "Ctrl+S"};
    for (uint8_t i = 0; i < kButtonCount; ++i) {
        copyAction(actions_[i], ActionKind::Hotkey, defaults[i]);
    }
    memcpy(staged_, actions_, sizeof(actions_));
}

void ProfileStore::copyAction(MacroAction& destination, ActionKind kind, const char* value) {
    destination.kind = kind;
    strncpy(destination.value, value, sizeof(destination.value) - 1);
    destination.value[sizeof(destination.value) - 1] = '\0';
}

bool ProfileStore::validAction(ActionKind kind, const char* value) const {
    if (value == nullptr || strlen(value) >= config::kActionValueCapacity) {
        return false;
    }
    switch (kind) {
        case ActionKind::None:
        case ActionKind::Hotkey:
        case ActionKind::Text:
        case ActionKind::Sequence:
        case ActionKind::LockScreen:
        case ActionKind::Screenshot:
        case ActionKind::CloseApp:
        case ActionKind::App:
        case ActionKind::Url:
        case ActionKind::Script:
            return true;
    }
    return false;
}
