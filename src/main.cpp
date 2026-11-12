#include <Arduino.h>
#include <BLEDevice.h>
#include <esp_mac.h>

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
bool appHeld[config::kMaxButtons] = {};
uint32_t bleDisconnectCount = 0;

void notifyButton(uint8_t number, bool pressed) {
    ++eventSequence;
    ble.bridge().updateState(profile.standalone(), bootSession, eventSequence);
    if (usb.connected()) {
        Serial.printf("EVT %lu %lu %u %s\n", static_cast<unsigned long>(bootSession),
                      static_cast<unsigned long>(eventSequence), number,
                      pressed ? "PRESSED" : "RELEASED");
    }
    ble.bridge().notifyButton(number, pressed, bootSession, eventSequence);
}

void releaseHolds() {
    buttons.cancelDeferredPresses();
    for (uint8_t i = 0; i < config::kMaxButtons; ++i) {
        if (appHeld[i]) notifyButton(i + 1, false);
        appHeld[i] = false;
    }
    ble.releaseAll();
}

void refreshHoldButtons() {
    uint16_t mask = 0;
    for (uint8_t number = 1; number <= buttons.count(); ++number) {
        if (profile.action(number).kind == ActionKind::HoldKey) mask |= 1U << (number - 1);
    }
    buttons.setHoldButtons(mask);
}

// A running app renews this lease; without it (app closed, crashed, or another
// machine) the board itself is the keyboard, so it works anywhere it is paired.
bool appPresent() {
    if (appLeased && static_cast<uint32_t>(millis() - appLeaseAtMs) >= config::kAppLeaseMs) {
        releaseHolds();
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

// Must run before Bluetooth starts: the BLE address is derived from the base MAC.
void applyBleIdentity(uint8_t identity) {
    if (identity == 0) return;
    uint8_t mac[6];
    if (esp_efuse_mac_get_default(mac) != ESP_OK) return;
    mac[0] |= 0x02;  // locally administered, so it never equals another chip's factory address
    mac[5] = static_cast<uint8_t>(mac[5] + identity);
    esp_base_mac_addr_set(mac);
}

// Hosts paired before keep the old address and stop finding the board; the next host
// sees a brand-new device to pair, like the "pair new" key on multi-host keyboards.
void pairNewHost() {
    releaseHolds();
    profile.setBleEnabled(true);
    profile.nextBleIdentity();
    ble.bridge().forgetBonds();
    usb.printMessage("PAIR NEW RESTART");
    Serial.flush();
    delay(300);
    ESP.restart();
}

void handleButton(const ButtonEvent& event) {
    if (event.type == ButtonEventType::PairRequested) {
        pairNewHost();
        return;
    }
    if (event.number < 1 || event.number > buttons.count()) return;
    const bool local = profile.standalone() || !appPresent();
    const MacroAction& action = profile.action(event.number);
    const bool hold = action.kind == ActionKind::HoldKey;
    // An app must not also execute a press the board types itself.
    if (!local) usb.printButton(event, buttons.pin(event.number), buttons.pressCount(event.number));
    if (event.type == ButtonEventType::LongPressed &&
        event.number == buttons.count() && !hold) {
        releaseHolds();
        profile.setBleEnabled(!profile.bleEnabled());
        ble.setEnabled(profile.bleEnabled());
        status();
        return;
    }
    if (event.type == ButtonEventType::Released) {
        // Release only the original owner, never the current profile/lease owner.
        ble.release(event.number);
        if (appHeld[event.number - 1]) {
            notifyButton(event.number, false);
            appHeld[event.number - 1] = false;
        }
        return;
    }
    if (event.type != ButtonEventType::Pressed) return;
    if (local) {
        ++eventSequence;
        ble.bridge().updateState(profile.standalone(), bootSession, eventSequence);
        if (hold) ble.hold(event.number, action);
        else ble.execute(action);
        return;
    }
    if (hold) appHeld[event.number - 1] = true;
    notifyButton(event.number, true);
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
            releaseHolds();
            profile.commitStaged();
            refreshHoldButtons();
            usb.printMessage("SYNC COMMIT OK");
            break;
        case UsbCommandType::SetBle:
            if (!command.bleEnabled) releaseHolds();
            profile.setBleEnabled(command.bleEnabled);
            ble.setEnabled(command.bleEnabled);
            status();
            break;
        case UsbCommandType::SetMode:
            if (profile.standalone() != command.standalone) releaseHolds();
            profile.setStandalone(command.standalone);
            status();
            break;
        case UsbCommandType::AppLease:
            if (!appPresent()) releaseHolds();
            appLeased = true;
            appLeaseAtMs = millis();
            break;
        case UsbCommandType::AppRelease:
            releaseHolds();
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
            releaseHolds();
            // Echo what NVS now holds; the app only reports success when it matches.
            usb.printConfig(profile.device());
            usb.printMessage("CFG OK RESTART");
            Serial.flush();
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
    applyBleIdentity(profile.bleIdentity());
    buttons.begin(profile.device());
    refreshHoldButtons();
    bootSession = esp_random();
    ble.begin(profile.device().name, profile.bleEnabled(),
              buttons.pressed(config::kBleForgetButton));
    status();
}

void loop() {
    appPresent();
    const uint32_t disconnects = ble.bridge().disconnectCount();
    if (disconnects != bleDisconnectCount) {
        releaseHolds();
        appLeased = false;
        bleDisconnectCount = disconnects;
    }
    const bool serialConnected = usb.connected();
    if (serialWasConnected && !serialConnected) {
        releaseHolds();
        appLeased = false;
    }
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
