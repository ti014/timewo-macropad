#include "profile_store.h"

#include <cstring>

namespace {
constexpr const char* kBleKey = "ble";
}

void ProfileStore::begin() {
    setDefaults();
    preferences_.begin(kNamespace, false);
    bleEnabled_ = preferences_.getBool(kBleKey, true);

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
    bleEnabled_ = enabled;
    preferences_.putBool(kBleKey, enabled);
}

void ProfileStore::setDefaults() {
    copyAction(actions_[0], ActionKind::Hotkey, "Ctrl+C");
    copyAction(actions_[1], ActionKind::Hotkey, "Ctrl+V");
    copyAction(actions_[2], ActionKind::Hotkey, "Alt+Tab");
    copyAction(actions_[3], ActionKind::Hotkey, "Ctrl+S");
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
            return true;
    }
    return false;
}
