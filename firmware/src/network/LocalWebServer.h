#pragma once

#include <Arduino.h>
#include <WebServer.h>

#include "devices/LimitSwitchDriver.h"
#include "devices/PcaServoDriver.h"
#include "network/MqttService.h"
#include "network/NetworkManager.h"
#include "storage/StorageManager.h"

class LocalWebServer {
 public:
  LocalWebServer(NetworkManager& network, StorageManager& storage,
                 MqttService& mqtt,
                 PcaServoDriver& servo, LimitSwitchDriver& switches);

  void begin();
  void loop();

 private:
  void handleRoot();
  void handleStatus();
  void handleWifi();
  void handleServoCalibration();
  void handleReboot();
  void sendJsonError(int code, const char* message);

  NetworkManager& network_;
  StorageManager& storage_;
  MqttService& mqtt_;
  PcaServoDriver& servo_;
  LimitSwitchDriver& switches_;
  WebServer server_{80};
};

