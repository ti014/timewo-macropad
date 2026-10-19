#pragma once

#include <BleKeyboard.h>
#include <esp_gap_ble_api.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include "usb_protocol.h"

// HID and app GATT share one bonded BLE connection, never two competing radios.
class BridgeKeyboard : public BleKeyboard {
public:
    BridgeKeyboard() : BleKeyboard(config::kDefaultName, "timewo", 100) {}
    // forgetBonds clears every stored pairing so a host with a stale key can pair again.
    void start(const char* name, bool enabled, bool forgetBonds = false);
    void setEnabled(bool enabled);
    void updateState(bool standalone, uint32_t session, uint32_t sequence);
    void notifyPress(uint8_t button, uint32_t session, uint32_t sequence);
    bool pollCommand(UsbCommand& command);

protected:
    using BleKeyboard::onConnect;
    void onStarted(BLEServer* server) override;
    void onConnect(BLEServer* server, esp_ble_gatts_cb_param_t* param) override;
    void onDisconnect(BLEServer* server) override;

private:
    struct Chunk { uint8_t length; uint8_t data[64]; };
    class Commands : public BLECharacteristicCallbacks {
    public:
        explicit Commands(BridgeKeyboard& owner) : owner_(owner) {}
        void onWrite(BLECharacteristic* characteristic) override;
    private:
        BridgeKeyboard& owner_;
    } commands_{*this};
    BLEServer* server_ = nullptr;
    BLECharacteristic* events_ = nullptr;
    BLECharacteristic* state_ = nullptr;
    QueueHandle_t chunks_ = nullptr;
    UsbProtocol decoder_;
    Chunk pending_{};
    size_t pendingOffset_ = 0;
    volatile bool overflow_ = false;
    volatile bool enabled_ = true;
    bool started_ = false;
};
