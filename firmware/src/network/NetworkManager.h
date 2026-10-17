#pragma once

#include <Arduino.h>

#include "storage/StorageManager.h"

class NetworkManager {
 public:
  explicit NetworkManager(StorageManager& storage);

  void begin();
  void loop();
  void reconnectWith(const String& ssid, const String& password);
  bool isConnected() const;
  bool isFallbackApActive() const;
  String currentSsid() const;
  String ipAddress() const;
  int32_t rssi() const;

 private:
  void connectStation();
  void startFallbackAp();

  StorageManager& storage_;
  String ssid_;
  String password_;
  uint32_t connectStartedAt_ = 0;
  uint32_t lastRetryAt_ = 0;
  bool fallbackApActive_ = false;
};

