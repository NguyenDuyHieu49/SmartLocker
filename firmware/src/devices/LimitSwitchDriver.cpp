#include "LimitSwitchDriver.h"

#include "config/PinConfig.h"

void LimitSwitchDriver::begin(DoorStateCallback callback) {
  callback_ = callback;
  for (uint8_t box = 0; box < SystemConfig::TOTAL_BOXES; ++box) {
    pinMode(PinConfig::LIMIT_SWITCH_PINS[box],
            PinConfig::LIMIT_SWITCH_USE_INTERNAL_PULLUP ? INPUT_PULLUP : INPUT);
    stableState_[box] = readClosed(box);
    rawState_[box] = stableState_[box];
    changedAt_[box] = millis();
  }
}

bool LimitSwitchDriver::readClosed(uint8_t box) const {
  const bool level = digitalRead(PinConfig::LIMIT_SWITCH_PINS[box]);
  return PinConfig::LIMIT_SWITCH_ACTIVE_LOW ? !level : level;
}

void LimitSwitchDriver::loop() {
  const uint32_t now = millis();
  for (uint8_t box = 0; box < SystemConfig::TOTAL_BOXES; ++box) {
    const bool current = readClosed(box);
    if (current != rawState_[box]) {
      rawState_[box] = current;
      changedAt_[box] = now;
    }

    if (current != stableState_[box] &&
        now - changedAt_[box] >= SystemConfig::SWITCH_DEBOUNCE_MS) {
      stableState_[box] = current;
      if (callback_ != nullptr) callback_(box, current);
    }
  }
}

bool LimitSwitchDriver::isDoorClosed(uint8_t box) const {
  return box < SystemConfig::TOTAL_BOXES ? stableState_[box] : false;
}

