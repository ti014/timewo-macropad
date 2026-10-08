#include <Arduino.h>

#include "config.h"
#include "profile_store.h"
#include "usb_protocol.h"
#include "ble_controller.h"
#include "button_scanner.h"

namespace {
ButtonScanner buttons;
ProfileStore profile;
UsbProtocol usb;
BleController ble;
bool serialWasConnected = false;

void handleButton(const ButtonEvent& event) {
    usb.printButton(event, buttons.pressCount(event.number));
    if (event.type == ButtonEventType::LongPressed &&
        event.number == config::kBleToggleButton) {
        profile.setBleEnabled(!profile.bleEnabled());
        usb.printMessage(profile.bleEnabled() ? "BLE enabled; restarting."
                                              : "BLE disabled; restarting.");
        delay(120);
        ESP.restart();
        return;
    }
    if (event.type != ButtonEventType::Pressed || usb.connected()) return;
    ble.execute(profile.action(event.number));
}

void handleUsbCommand(const UsbCommand& command) {
    switch (command.type) {
        case UsbCommandType::Status:
            usb.printStatus(buttons, profile, ble.connected());
            break;
        case UsbCommandType::SyncAction:
            usb.printMessage(profile.setStaged(command.button, command.actionKind, command.value)
                                 ? "SYNC ACTION OK"
                                 : "SYNC ACTION ERROR");
            break;
        case UsbCommandType::SyncCommit:
            profile.commitStaged();
            usb.printMessage("SYNC COMMIT OK");
            break;
        case UsbCommandType::SetBle:
            profile.setBleEnabled(command.bleEnabled);
            usb.printMessage(command.bleEnabled ? "BLE ON; restarting."
                                                : "BLE OFF; restarting.");
            delay(120);
            ESP.restart();
            break;
        case UsbCommandType::None:
            break;
    }
}
}  // namespace

void setup() {
    Serial.begin(config::kSerialBaud);
    buttons.begin();
    profile.begin();
    ble.begin(profile.bleEnabled());
}

void loop() {
    const bool serialConnected = usb.connected();
    if (serialConnected && !serialWasConnected) {
        usb.printStatus(buttons, profile, ble.connected());
    }
    serialWasConnected = serialConnected;

    UsbCommand command;
    if (usb.update(command)) handleUsbCommand(command);
    buttons.update(millis(), handleButton);
    delay(1);
}
