#include "StorageManager.h"

bool StorageManager::begin() {
  ready_ = preferences_.begin("smartbox", false);
  return ready_;
}

String StorageManager::keyFor(const char* prefix, uint8_t box) const {
  return String(prefix) + String(box);
}

uint16_t StorageManager::getLockAngle(uint8_t box) const {
  if (!ready_ || box >= SystemConfig::TOTAL_BOXES) {
    return SystemConfig::DEFAULT_LOCK_ANGLE;
  }
  return preferences_.getUShort(keyFor("lock", box).c_str(),
                                SystemConfig::DEFAULT_LOCK_ANGLE);
}

uint16_t StorageManager::getUnlockAngle(uint8_t box) const {
  if (!ready_ || box >= SystemConfig::TOTAL_BOXES) {
    return SystemConfig::DEFAULT_UNLOCK_ANGLE;
  }
  return preferences_.getUShort(keyFor("open", box).c_str(),
                                SystemConfig::DEFAULT_UNLOCK_ANGLE);
}

bool StorageManager::setServoCalibration(uint8_t box, uint16_t lockAngle,
                                         uint16_t unlockAngle) {
  if (!ready_ || box >= SystemConfig::TOTAL_BOXES || lockAngle > 180 ||
      unlockAngle > 180) {
    return false;
  }

  preferences_.putUShort(keyFor("lock", box).c_str(), lockAngle);
  preferences_.putUShort(keyFor("open", box).c_str(), unlockAngle);
  return true;
}

String StorageManager::getWifiSsid() const {
  return ready_ ? preferences_.getString("wifi_ssid", "") : "";
}

String StorageManager::getWifiPassword() const {
  return ready_ ? preferences_.getString("wifi_pass", "") : "";
}

void StorageManager::setWifiCredentials(const String& ssid,
                                        const String& password) {
  if (!ready_) return;
  preferences_.putString("wifi_ssid", ssid);
  preferences_.putString("wifi_pass", password);
}

String StorageManager::getLastRequestId() const {
  return ready_ ? preferences_.getString("last_req", "") : "";
}

void StorageManager::setLastRequestId(const String& requestId) {
  if (!ready_ || requestId.isEmpty()) return;
  preferences_.putString("last_req", requestId);
}

