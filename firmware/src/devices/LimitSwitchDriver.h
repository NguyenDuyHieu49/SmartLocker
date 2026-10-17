#pragma once

#include <Arduino.h>

#include "config/SystemConfig.h"

using DoorStateCallback = void (*)(uint8_t box, bool doorClosed);

class LimitSwitchDriver {
 public:
  void begin(DoorStateCallback callback);
  void loop();
  bool isDoorClosed(uint8_t box) const;

 private:
  bool readClosed(uint8_t box) const;

  DoorStateCallback callback_ = nullptr;
  bool stableState_[SystemConfig::TOTAL_BOXES] = {};
  bool rawState_[SystemConfig::TOTAL_BOXES] = {};
  uint32_t changedAt_[SystemConfig::TOTAL_BOXES] = {};
};

