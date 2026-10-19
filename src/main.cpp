#include <Arduino.h>
#include <BLEDevice.h>

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
uint32_t bootSession = 0;
uint32_t eventSequence = 0;
bool appLeased = false;
uint32_t appLeaseAtMs = 0;

// A running app renews this lease; without it (app closed, crashed, or another
// machine) the board itself is the keyboard, so it works anywhere it is paired.
bool appPresent() {
    if (appLeased && static_cast<uint32_t>(millis() - appLeaseAtMs) >= config::kAppLeaseMs) {
        appLeased = false;
    }
    return appLeased;
}

void status() {
    ble.bridge().updateState(profile.standalone(), bootSession, eventSequence);
    if (usb.connected()) {
        Serial.printf("BRIDGE 1 %lu %u\n", static_cast<unsigned long>(bootSession),
                      profile.standalone() ? 1 : 0);
        Serial.printf("BLE_ADDR %s\n", BLEDevice::getAddress().toString().c_str());
    }
    usb.printStatus(buttons, profile, ble.connected());
}

void handleButton(const ButtonEvent& event) {
    const bool local = profile.standalone() || !appPresent();
    // An app must not also execute a press the board types itself.
    if (!local) usb.printButton(event, buttons.pin(event.number), buttons.pressCount(event.number));
    if (event.type == ButtonEventType::LongPressed &&
        event.number == buttons.count()) {
        profile.setBleEnabled(!profile.bleEnabled());
        ble.setEnabled(profile.bleEnabled());
        status();
        return;
    }
    if (event.type != ButtonEventType::Pressed) return;
    ++eventSequence;
    ble.bridge().updateState(profile.standalone(), bootSession, eventSequence);
    if (local) {
        ble.execute(profile.action(event.number));
        return;
    }
    if (usb.connected()) {
        Serial.printf("EVT %lu %lu %u\n", static_cast<unsigned long>(bootSession),
                      static_cast<unsigned long>(eventSequence), event.number);
    }
    ble.bridge().notifyPress(event.number, bootSession, eventSequence);
}

void handleUsbCommand(const UsbCommand& command) {
    switch (command.type) {
        case UsbCommandType::Status:
            status();
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
            ble.setEnabled(command.bleEnabled);
            status();
            break;
        case UsbCommandType::SetMode:
            profile.setStandalone(command.standalone);
            status();
            break;
        case UsbCommandType::AppLease:
            appLeased = true;
            appLeaseAtMs = millis();
            break;
        case UsbCommandType::AppRelease:
            appLeased = false;
            break;
        case UsbCommandType::Info:
            usb.printInfo(profile.device());
            break;
        case UsbCommandType::Dump:
            usb.printActions(profile);
            break;
        case UsbCommandType::SetConfig: {
            const char* error = profile.saveDevice(command.device);
            if (error != nullptr) {
                if (usb.connected()) Serial.printf("CFG ERROR %s\n", error);
                break;
            }
            // Echo what NVS now holds; the app only reports success when it matches.
            usb.printConfig(profile.device());
            usb.printMessage("CFG OK RESTART");
            Serial.flush();
            ble.bridge().releaseAll();
            // Pins and the BLE name are only applied at boot.
            delay(300);
            ESP.restart();
            break;
        }
        case UsbCommandType::None:
            break;
    }
}
}  // namespace

void setup() {
    Serial.begin(config::kSerialBaud);
    profile.begin();
    buttons.begin(profile.device());
    bootSession = esp_random();
    ble.begin(profile.device().name, profile.bleEnabled(),
              buttons.pressed(config::kBleForgetButton));
    status();
}

void loop() {
    const bool serialConnected = usb.connected();
    if (serialConnected && !serialWasConnected) {
        status();
    }
    serialWasConnected = serialConnected;

    UsbCommand command;
    if (usb.update(command)) handleUsbCommand(command);
    if (ble.bridge().pollCommand(command)) handleUsbCommand(command);
    buttons.update(millis(), handleButton);
    delay(1);
}
