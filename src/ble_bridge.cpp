#include "ble_bridge.h"

#include <BLE2902.h>
#include <BLEDevice.h>
#include <BLEHIDDevice.h>
#include <cstring>
#include <vector>

namespace {
constexpr char kName[] = "timewo-macropad";
constexpr char kService[] = "a9141000-6ed1-4b32-9b4c-cb94de001001";
constexpr char kEvents[] = "a9141001-6ed1-4b32-9b4c-cb94de001001";
constexpr char kCommands[] = "a9141002-6ed1-4b32-9b4c-cb94de001001";
constexpr char kState[] = "a9141003-6ed1-4b32-9b4c-cb94de001001";

void packet(uint8_t* bytes, uint8_t value, uint32_t session, uint32_t sequence) {
    bytes[0] = 1;
    bytes[1] = value;
    for (size_t i = 0; i < 4; ++i) {
        bytes[2 + i] = static_cast<uint8_t>(session >> (8 * i));
        bytes[6 + i] = static_cast<uint8_t>(sequence >> (8 * i));
    }
}

void onGap(esp_gap_ble_cb_event_t event, esp_ble_gap_cb_param_t* param) {
    if (event == ESP_GAP_BLE_AUTH_CMPL_EVT && !param->ble_security.auth_cmpl.success) {
        // A stale key makes every retry fail; drop it so the host's next attempt pairs fresh.
        esp_ble_remove_bond_device(param->ble_security.auth_cmpl.bd_addr);
    }
}

void removeAllBonds() {
    int count = esp_ble_get_bond_device_num();
    if (count <= 0) return;
    std::vector<esp_ble_bond_dev_t> bonds(count);
    if (esp_ble_get_bond_device_list(&count, bonds.data()) != ESP_OK) return;
    for (int i = 0; i < count; ++i) esp_ble_remove_bond_device(bonds[i].bd_addr);
}

template <typename T>
void securityParam(esp_ble_sm_param_t param, T value) {
    esp_ble_gap_set_security_param(param, &value, sizeof(value));
}
}

void BridgeKeyboard::start(bool enabled, bool forgetBonds) {
    enabled_ = enabled;
    BLEDevice::setCustomGapHandler(onGap);
    // Initialize once even when disabled so re-enabling never restarts the MCU.
    begin();
    started_ = true;
    if (forgetBonds) removeAllBonds();
    // No display or keypad: force Just Works. The stack default can make the
    // host ask for a passkey, which neither Windows' prompt nor bleak can supply.
    securityParam<esp_ble_io_cap_t>(ESP_BLE_SM_IOCAP_MODE, ESP_IO_CAP_NONE);
    securityParam<uint8_t>(ESP_BLE_SM_SET_INIT_KEY, ESP_BLE_ENC_KEY_MASK | ESP_BLE_ID_KEY_MASK);
    securityParam<uint8_t>(ESP_BLE_SM_SET_RSP_KEY, ESP_BLE_ENC_KEY_MASK | ESP_BLE_ID_KEY_MASK);

    // Hand-built payloads: the generated one put both UUIDs as 128-bit and
    // overflowed the 31-byte limit, so the stack silently dropped fields.
    BLEAdvertisementData advert;  // 3 + 4 + 4 + 17 = 28 bytes
    advert.setFlags(ESP_BLE_ADV_FLAG_GEN_DISC | ESP_BLE_ADV_FLAG_BREDR_NOT_SPT);
    advert.setAppearance(HID_KEYBOARD);
    advert.setCompleteServices(BLEUUID(static_cast<uint16_t>(0x1812)));
    advert.setName(kName);
    BLEAdvertisementData scanResponse;  // 18 bytes; the desktop app scans actively.
    scanResponse.setCompleteServices(BLEUUID(kService));

    auto* advertising = server_->getAdvertising();
    advertising->stop();
    advertising->setAdvertisementData(advert);
    advertising->setScanResponseData(scanResponse);
    advertising->setMinInterval(32);
    advertising->setMaxInterval(64);
    if (enabled_) advertising->start();
}

void BridgeKeyboard::setEnabled(bool enabled) {
    enabled_ = enabled;
    if (!started_) return;
    if (enabled) {
        if (!isConnected()) server_->getAdvertising()->start();
    } else {
        releaseAll();
        server_->getAdvertising()->stop();
        if (isConnected()) server_->disconnect(server_->getConnId());
    }
}

void BridgeKeyboard::onStarted(BLEServer* server) {
    server_ = server;
    chunks_ = xQueueCreate(32, sizeof(Chunk));
    BLEService* service = server->createService(kService);
    events_ = service->createCharacteristic(kEvents, BLECharacteristic::PROPERTY_NOTIFY);
    auto* subscription = new BLE2902();
    subscription->setAccessPermissions(ESP_GATT_PERM_READ_ENCRYPTED | ESP_GATT_PERM_WRITE_ENCRYPTED);
    events_->addDescriptor(subscription);
    auto* command = service->createCharacteristic(kCommands, BLECharacteristic::PROPERTY_WRITE);
    command->setAccessPermissions(ESP_GATT_PERM_WRITE_ENCRYPTED);
    command->setCallbacks(&commands_);
    state_ = service->createCharacteristic(kState, BLECharacteristic::PROPERTY_READ);
    state_->setAccessPermissions(ESP_GATT_PERM_READ_ENCRYPTED);
    service->start();
}

void BridgeKeyboard::onConnect(BLEServer* server, esp_ble_gatts_cb_param_t* param) {
    // 7.5-15 ms keeps pairing and GATT discovery short; the host may still choose slower.
    server->updateConnParams(param->connect.remote_bda, 6, 12, 0, 400);
}

void BridgeKeyboard::onDisconnect(BLEServer* server) {
    BleKeyboard::onDisconnect(server);
    if (!enabled_) server->getAdvertising()->stop();
    overflow_ = true;  // A partial command must not survive reconnect.
}

void BridgeKeyboard::Commands::onWrite(BLECharacteristic* characteristic) {
    const std::string data = characteristic->getValue();
    if (data.empty()) return;
    if (data.size() > sizeof(Chunk::data) || owner_.chunks_ == nullptr) {
        owner_.overflow_ = true;
        return;
    }
    Chunk chunk{};
    chunk.length = static_cast<uint8_t>(data.size());
    memcpy(chunk.data, data.data(), data.size());
    if (xQueueSend(owner_.chunks_, &chunk, 0) != pdTRUE) owner_.overflow_ = true;
}

bool BridgeKeyboard::pollCommand(UsbCommand& command) {
    if (overflow_) {
        // Fail closed: discard through the next newline after a truncated write.
        decoder_.resetInput(true);
        if (chunks_) xQueueReset(chunks_);
        pendingOffset_ = pending_.length;
        overflow_ = false;
    }
    for (size_t i = 0; i < 64; ++i) {
        if (pendingOffset_ >= pending_.length) {
            if (!chunks_ || xQueueReceive(chunks_, &pending_, 0) != pdTRUE) return false;
            pendingOffset_ = 0;
        }
        if (decoder_.feed(pending_.data[pendingOffset_++], command)) return true;
    }
    return false;
}

void BridgeKeyboard::updateState(bool standalone, uint32_t session, uint32_t sequence) {
    if (!state_) return;
    uint8_t bytes[10];
    packet(bytes, standalone ? 1 : 0, session, sequence);
    state_->setValue(bytes, sizeof(bytes));
}

void BridgeKeyboard::notifyPress(uint8_t button, uint32_t session, uint32_t sequence) {
    if (!enabled_ || !isConnected() || !events_) return;
    uint8_t bytes[10];
    packet(bytes, button, session, sequence);
    events_->setValue(bytes, sizeof(bytes));
    events_->notify();
}
