#include <Arduino.h>
#include <Wire.h>
#include <time.h>

#include "config/NetworkConfig.h"
#include "config/PinConfig.h"
#include "devices/KeypadService.h"
#include "devices/LimitSwitchDriver.h"
#include "devices/PcaServoDriver.h"
#include "display/DisplayService.h"
#include "network/LocalWebServer.h"
#include "network/MqttService.h"
#include "network/NetworkManager.h"
#include "storage/StorageManager.h"

StorageManager storage;
NetworkManager network(storage);
DisplayService display;
KeypadService keypad(display);
PcaServoDriver servo(storage);
LimitSwitchDriver switches;
MqttService mqtt(network, storage, servo, switches, display, keypad);
LocalWebServer localWeb(network, storage, mqtt, servo, switches);

void onDoorChanged(uint8_t box, bool doorClosed) {
  Serial.printf("[DOOR] box=%u closed=%s\n", box,
                doorClosed ? "true" : "false");
  mqtt.publishDoorEvent(box, doorClosed);
}

void onAccessRequest(const String& action, const String& value,
                     const String& orderCode) {
  mqtt.publishAccessRequest(action, value, orderCode);
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n[BOOT] SmartBox MVP starting");

  if (!storage.begin()) {
    Serial.println("[FATAL] Cannot initialize NVS");
  }

  Wire.begin(PinConfig::I2C_SDA, PinConfig::I2C_SCL);
  if (!servo.begin()) {
    Serial.println("[FATAL] PCA9685 not detected");
  }

  switches.begin(onDoorChanged);
  display.begin();
  keypad.begin(onAccessRequest);
  network.begin();
  configTime(0, 0, NetworkConfig::NTP_SERVER_1, NetworkConfig::NTP_SERVER_2);
  mqtt.begin();
  localWeb.begin();
}

void loop() {
  network.loop();
  mqtt.loop();
  switches.loop();
  keypad.loop();
  servo.loop();
  localWeb.loop();
  delay(2);
}

