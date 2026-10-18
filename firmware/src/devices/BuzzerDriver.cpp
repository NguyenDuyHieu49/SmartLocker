#include "BuzzerDriver.h"

#include "config/PinConfig.h"

namespace {
constexpr uint32_t ALARM_TOGGLE_INTERVAL_MS = 300;
}

void BuzzerDriver::begin() {
  pinMode(PinConfig::BUZZER, OUTPUT);
  write(false);
  beep();
}

void BuzzerDriver::loop() {
  const uint32_t now = millis();

  if (beeping_ && static_cast<int32_t>(now - beepUntil_) >= 0) {
    beeping_ = false;
    if (!alarming_) write(false);
  }

  if (alarming_ && now - lastAlarmToggleAt_ >= ALARM_TOGGLE_INTERVAL_MS) {
    lastAlarmToggleAt_ = now;
    write(!outputOn_);
  }
}

void BuzzerDriver::beep(uint16_t durationMs) {
  write(true);
  beeping_ = true;
  beepUntil_ = millis() + durationMs;
}

void BuzzerDriver::startAlarm() {
  if (alarming_) return;
  alarming_ = true;
  beeping_ = false;
  lastAlarmToggleAt_ = millis();
  write(true);
}

void BuzzerDriver::stopAlarm() {
  if (!alarming_) return;
  alarming_ = false;
  write(false);
}

bool BuzzerDriver::isAlarming() const { return alarming_; }

void BuzzerDriver::write(bool enabled) {
  outputOn_ = enabled;
  const bool level = PinConfig::BUZZER_ACTIVE_HIGH ? enabled : !enabled;
  digitalWrite(PinConfig::BUZZER, level ? HIGH : LOW);
}
