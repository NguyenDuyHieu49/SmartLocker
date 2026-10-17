#pragma once

#include <Arduino.h>
#include <MQTT.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>

#include "config/SystemConfig.h"
#include "devices/KeypadService.h"
#include "devices/LimitSwitchDriver.h"
#include "devices/PcaServoDriver.h"
#include "display/DisplayService.h"
#include "network/NetworkManager.h"
#include "storage/StorageManager.h"

class MqttService {
 public:
  MqttService(NetworkManager& network, StorageManager& storage,
              PcaServoDriver& servo, LimitSwitchDriver& switches,
              DisplayService& display, KeypadService& keypad);

  void begin();
  void loop();
  bool isConnected();

  void publishDoorEvent(uint8_t box, bool doorClosed);
  void publishBoxesStatus();
  void publishAccessRequest(const String& action, const String& value,
                            const String& orderCode);

 private:
  void connect();
  void onMessage(String& topic, String& payload);
  void handleUnlock(const String& payload);
  void handleSetBox(const String& payload);
  void handleReboot(const String& payload);
  void handleUi(const String& payload);
  void publishHeartbeat();
  void publishUnlockResult(uint8_t box, const String& requestId, bool success,
                           const char* error);
  void publishSetBoxResult(uint8_t box, const String& requestId, bool success);
  void rememberRequest(const String& requestId);
  bool wasRequestProcessed(const String& requestId) const;
  String topic(const char* suffix) const;
  uint32_t timestamp() const;

  NetworkManager& network_;
  StorageManager& storage_;
  PcaServoDriver& servo_;
  LimitSwitchDriver& switches_;
  DisplayService& display_;
  KeypadService& keypad_;
  WiFiClient wifiClient_;
  WiFiClientSecure secureClient_;
  MQTTClient client_;
  uint32_t lastConnectAttemptAt_ = 0;
  uint32_t lastHeartbeatAt_ = 0;
  uint32_t lastStatusAt_ = 0;
  bool rebootPending_ = false;
  uint32_t rebootAt_ = 0;
  String processedRequests_[SystemConfig::PROCESSED_REQUEST_CACHE_SIZE];
  size_t requestCursor_ = 0;
};

