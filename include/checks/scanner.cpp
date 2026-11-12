// From repo root: c++ -std=c++11 -DCONFIG_IDF_TARGET_ESP32C3 -Iinclude/checks -Iinclude include/checks/scanner.cpp src/button_scanner.cpp -o scanner-check && ./scanner-check
#include <cassert>
#include <vector>
#include "button_scanner.h"

bool down[64] = {};
std::vector<ButtonEvent> events;
void capture(const ButtonEvent& event) { events.push_back(event); }

int main() {
    DeviceSettings settings;
    settings.buttonCount = 9;
    settings.debounceMs = 5;
    settings.holdMs = 500;
    for (uint8_t i = 0; i < 9; ++i) settings.pins[i] = i;
    ButtonScanner scanner;
    scanner.begin(settings);
    scanner.setHoldButtons((1U << 5) | (1U << 8));
    auto edge = [&](uint8_t button, bool pressed, uint32_t now) {
        down[button - 1] = pressed;
        scanner.update(now, capture);
        scanner.update(now + 5, capture);
    };
    auto expect = [](uint8_t button, ButtonEventType type) {
        assert(!events.empty());
        assert(events.back().number == button && events.back().type == type);
    };

    edge(9, true, 10);
    expect(9, ButtonEventType::Pressed);
    scanner.update(600, capture);
    assert(events.size() == 1);  // Last HoldKey never toggles BLE.
    edge(6, true, 610);
    assert(events.size() == 3);
    assert(events[1].number == 9 && events[1].type == ButtonEventType::Released);
    expect(6, ButtonEventType::Released);  // Swallow cleans holds immediately.
    edge(6, false, 620);
    edge(9, false, 630);
    assert(events.size() == 3);  // Aborted pair emits no macro or duplicate up.

    edge(9, true, 700);
    edge(6, true, 710);
    scanner.update(1215, capture);
    expect(6, ButtonEventType::PairRequested);  // Pair gesture still works.
    edge(6, false, 1220);
    edge(9, false, 1230);
    events.clear();
    edge(6, true, 1300);
    expect(6, ButtonEventType::Pressed);
    edge(9, true, 1310);
    assert(events[1].number == 6 && events[1].type == ButtonEventType::Released);
    expect(9, ButtonEventType::Released);  // Reverse order also cleans owner.
    edge(9, false, 1320);
    edge(6, false, 1330);

    events.clear();
    edge(9, true, 1340);
    expect(9, ButtonEventType::Pressed);
    scanner.cancelDeferredPresses();
    scanner.setHoldButtons(0);  // Sync changed a physically held HoldKey to a tap.
    edge(9, false, 1350);
    assert(events.size() == 1);  // Old release cannot create a new profile's press.
    events.clear();
    edge(9, true, 1400);
    assert(events.empty());
    edge(9, false, 1410);
    assert(events.size() == 2);  // Ordinary last button keeps tap-on-release.
    assert(events[0].type == ButtonEventType::Pressed);
    expect(9, ButtonEventType::Released);
    events.clear();
    edge(9, true, 1500);
    scanner.update(2005, capture);
    expect(9, ButtonEventType::LongPressed);
    edge(9, false, 2010);
    assert(events.size() == 1);
}
