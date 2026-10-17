#pragma once

#include <Adafruit_PWMServoDriver.h>
#include <Arduino.h>

#include "config/SystemConfig.h"
#include "storage/StorageManager.h"

class PcaServoDriver {
 public:
  explicit PcaServoDriver(StorageManager& storage);

  bool begin();
  bool requestUnlock(uint8_t box);
  bool lockNow(uint8_t box);
  bool calibrate(uint8_t box, uint16_t lockAngle, uint16_t unlockAngle);
  void loop();
  bool isBusy() const;

 private:
  uint16_t angleToPulse(uint16_t angle) const;
  bool writeAngle(uint8_t box, uint16_t angle);

  StorageManager& storage_;
  Adafruit_PWMServoDriver pwm_;
  bool ready_ = false;
  int8_t activeBox_ = -1;
  uint32_t returnToLockAt_ = 0;
};

