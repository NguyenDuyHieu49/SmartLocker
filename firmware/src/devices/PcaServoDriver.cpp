#include "PcaServoDriver.h"

#include <Wire.h>

PcaServoDriver::PcaServoDriver(StorageManager& storage)
    : storage_(storage), pwm_(SystemConfig::PCA9685_ADDRESS) {}

bool PcaServoDriver::begin() {
  if (!pwm_.begin()) return false;
  pwm_.setPWMFreq(SystemConfig::SERVO_FREQUENCY_HZ);
  delay(10);

  ready_ = true;
  for (uint8_t box = 0; box < SystemConfig::TOTAL_BOXES; ++box) {
    lockNow(box);
  }
  return true;
}

uint16_t PcaServoDriver::angleToPulse(uint16_t angle) const {
  angle = constrain(angle, 0, 180);
  const uint32_t pulseUs = map(angle, 0, 180,
                               SystemConfig::SERVO_MIN_PULSE_US,
                               SystemConfig::SERVO_MAX_PULSE_US);
  return static_cast<uint16_t>((pulseUs * 4096UL) / 20000UL);
}

bool PcaServoDriver::writeAngle(uint8_t box, uint16_t angle) {
  if (!ready_ || box >= SystemConfig::TOTAL_BOXES) return false;
  return pwm_.setPWM(box, 0, angleToPulse(angle)) == 0;
}

bool PcaServoDriver::requestUnlock(uint8_t box) {
  if (!ready_ || box >= SystemConfig::TOTAL_BOXES || isBusy()) return false;
  if (!writeAngle(box, storage_.getUnlockAngle(box))) return false;

  activeBox_ = static_cast<int8_t>(box);
  returnToLockAt_ = millis() + SystemConfig::SERVO_UNLOCK_HOLD_MS;
  return true;
}

bool PcaServoDriver::lockNow(uint8_t box) {
  if (!writeAngle(box, storage_.getLockAngle(box))) return false;
  if (activeBox_ == static_cast<int8_t>(box)) {
    activeBox_ = -1;
    returnToLockAt_ = 0;
  }
  return true;
}

bool PcaServoDriver::calibrate(uint8_t box, uint16_t lockAngle,
                               uint16_t unlockAngle) {
  if (!storage_.setServoCalibration(box, lockAngle, unlockAngle)) return false;
  return lockNow(box);
}

void PcaServoDriver::loop() {
  if (activeBox_ < 0) return;
  if (static_cast<int32_t>(millis() - returnToLockAt_) < 0) return;
  lockNow(static_cast<uint8_t>(activeBox_));
}

bool PcaServoDriver::isBusy() const { return activeBox_ >= 0; }

