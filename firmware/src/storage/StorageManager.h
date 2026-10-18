#pragma once

#include <Arduino.h>
#include <Preferences.h>

#include "config/SystemConfig.h"

class StorageManager {
 public:
  bool begin();

  uint16_t getLockAngle(uint8_t box) const;
  uint16_t getUnlockAngle(uint8_t box) const;
  bool setServoCalibration(uint8_t box, uint16_t lockAngle,
                           uint16_t unlockAngle);

  String getWifiSsid() const;
  String getWifiPassword() const;
  void setWifiCredentials(const String& ssid, const String& password);

  String getLastRequestId() const;
  void setLastRequestId(const String& requestId);

 private:
  String keyFor(const char* prefix, uint8_t box) const;
  mutable Preferences preferences_;
  bool ready_ = false;
};

