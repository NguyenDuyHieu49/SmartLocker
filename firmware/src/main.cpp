#include <Arduino.h>
#include <Wire.h>
#include <time.h>

#include "config/NetworkConfig.h"
#include "config/PinConfig.h"
#include "devices/BuzzerDriver.h"
#include "devices/KeypadService.h"
#include "devices/LimitSwitchDriver.h"
#include "devices/PcaServoDriver.h"
#include "devices/RtcDriver.h"
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
BuzzerDriver buzzer;
RtcDriver rtc;
MqttService mqtt(network, storage, servo, switches, display, keypad);
LocalWebServer localWeb(network, storage, mqtt, servo, switches);

namespace {
uint32_t doorOpenedAt[SystemConfig::TOTAL_BOXES] = {};
bool rtcSyncedFromNtp = false;

void updateDoorAlarm() {
  const uint32_t now = millis();
  bool overdueDoor = false;
  for (uint8_t box = 0; box < SystemConfig::TOTAL_BOXES; ++box) {
    if (doorOpenedAt[box] != 0 &&
        now - doorOpenedAt[box] >= SystemConfig::DOOR_OPEN_ALARM_MS) {
      overdueDoor = true;
      break;
    }
  }
  if (overdueDoor) {
    buzzer.startAlarm();
  } else {
    buzzer.stopAlarm();
  }
}

void syncRtcWhenNtpIsReady() {
  if (rtcSyncedFromNtp || !rtc.isReady() || !network.isConnected()) return;
  const time_t now = time(nullptr);
  constexpr time_t MIN_VALID_EPOCH = 1704067200;  // 2024-01-01 UTC
  if (now < MIN_VALID_EPOCH) return;
  rtc.syncFromEpoch(static_cast<uint32_t>(now));
  rtcSyncedFromNtp = true;
  Serial.println("[RTC] Synced from NTP");
}
}  // namespace

void onDoorChanged(uint8_t box, bool doorClosed) {
  Serial.printf("[DOOR] box=%u closed=%s\n", box,
                doorClosed ? "true" : "false");
  doorOpenedAt[box] = doorClosed ? 0 : millis();
  mqtt.publishDoorEvent(box, doorClosed);
}

void onAccessRequest(const String& action, const String& value,
                     const String& orderCode) {
  buzzer.beep(50);
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

  if (!rtc.begin()) {
    Serial.println("[WARN] DS3231 not detected; continuing without RTC");
  }

  switches.begin(onDoorChanged);
  for (uint8_t box = 0; box < SystemConfig::TOTAL_BOXES; ++box) {
    if (!switches.isDoorClosed(box)) doorOpenedAt[box] = millis();
  }
  buzzer.begin();
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
  updateDoorAlarm();
  syncRtcWhenNtpIsReady();
  buzzer.loop();
  keypad.loop();
  servo.loop();
  localWeb.loop();
  delay(2);
}

