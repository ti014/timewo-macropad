#pragma once
#include <cstddef>
#include <cstdint>
#include <algorithm>
using std::min;
constexpr int INPUT_PULLUP = 2;
constexpr int LOW = 0;
extern bool down[64];
inline uint32_t millis() { return 0; }
inline void pinMode(uint8_t, int) {}
inline int digitalRead(uint8_t pin) { return down[pin] ? LOW : 1; }
