#pragma once

#include <Arduino.h>
#include <Preferences.h>

#include "macro_types.h"

class ProfileStore {
public:
    static constexpr uint8_t kButtonCount = 4;

    void begin();
    const MacroAction& action(uint8_t number) const;
    bool setStaged(uint8_t number, ActionKind kind, const char* value);
    bool commitStaged();

    bool bleEnabled() const;
    void setBleEnabled(bool enabled);

private:
    static constexpr const char* kNamespace = "macropad";
    MacroAction actions_[kButtonCount]{};
    MacroAction staged_[kButtonCount]{};
    bool bleEnabled_ = true;
    Preferences preferences_;

    void setDefaults();
    void copyAction(MacroAction& destination, ActionKind kind, const char* value);
    bool validAction(ActionKind kind, const char* value) const;
};
