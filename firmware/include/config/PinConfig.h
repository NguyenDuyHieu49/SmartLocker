#pragma once

#include <Arduino.h>

namespace PinConfig {

// Hardware profile imported from HN-main: ESP32-S3 SmartBox (5 compartments).
// Keep this file as the single source of truth for the physical wiring.
constexpr uint8_t I2C_SDA = 8;
constexpr uint8_t I2C_SCL = 9;

constexpr uint8_t LIMIT_SWITCH_PINS[] = {4, 5, 6, 7, 47};
constexpr bool LIMIT_SWITCH_ACTIVE_LOW = true;
constexpr bool LIMIT_SWITCH_USE_INTERNAL_PULLUP = true;

// Keypad 4x4. Thứ tự tương ứng R1..R4 và C1..C4.
constexpr uint8_t KEYPAD_ROW_PINS[] = {17, 18, 21, 38};
constexpr uint8_t KEYPAD_COL_PINS[] = {39, 40, 41, 42};

// TFT ST7789 240x240 over write-only SPI (MISO is not connected).
constexpr uint8_t TFT_SCLK = 12;
constexpr uint8_t TFT_MOSI = 11;
constexpr uint8_t TFT_CS = 10;
constexpr uint8_t TFT_DC = 2;
constexpr uint8_t TFT_RST = 14;
constexpr uint8_t TFT_BACKLIGHT = 15;
constexpr bool TFT_BACKLIGHT_ACTIVE_HIGH = true;

// Optional hardware present in the HN-main wiring profile.
constexpr uint8_t BUZZER = 16;
constexpr bool BUZZER_ACTIVE_HIGH = true;
constexpr uint8_t TEST_LED = 48;

}  // namespace PinConfig

