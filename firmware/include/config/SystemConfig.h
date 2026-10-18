#pragma once

#include <Arduino.h>

namespace SystemConfig {

constexpr uint8_t TOTAL_BOXES = 5;
constexpr uint8_t PCA9685_ADDRESS = 0x40;
constexpr uint8_t RTC_DS3231_ADDRESS = 0x68;
constexpr float SERVO_FREQUENCY_HZ = 50.0F;

constexpr uint16_t DEFAULT_LOCK_ANGLE = 0;
constexpr uint16_t DEFAULT_UNLOCK_ANGLE = 90;
constexpr uint16_t SERVO_MIN_PULSE_US = 500;
constexpr uint16_t SERVO_MAX_PULSE_US = 2500;
constexpr uint32_t SERVO_UNLOCK_HOLD_MS = 1200;
constexpr uint32_t DOOR_OPEN_ALARM_MS = 15000;

constexpr uint32_t SWITCH_DEBOUNCE_MS = 50;
constexpr uint32_t WIFI_CONNECT_TIMEOUT_MS = 15000;
constexpr uint32_t WIFI_RETRY_INTERVAL_MS = 10000;
constexpr uint32_t MQTT_RETRY_INTERVAL_MS = 3000;
constexpr uint32_t HEARTBEAT_INTERVAL_MS = 5000;
constexpr uint32_t STATUS_REPORT_INTERVAL_MS = 30000;
constexpr uint32_t REBOOT_DELAY_MS = 1000;

constexpr size_t MQTT_BUFFER_SIZE = 4096;
constexpr size_t PROCESSED_REQUEST_CACHE_SIZE = 16;
constexpr size_t MAX_KEYPAD_INPUT_LENGTH = 12;
constexpr uint16_t TFT_WIDTH = 240;
constexpr uint16_t TFT_HEIGHT = 240;

}  // namespace SystemConfig

