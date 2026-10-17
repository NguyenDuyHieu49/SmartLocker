#pragma once

#include <Arduino.h>

namespace PinConfig {

// Thay các GPIO này theo sơ đồ đấu thực tế của bạn trước khi nạp firmware.
constexpr uint8_t I2C_SDA = 8;
constexpr uint8_t I2C_SCL = 9;

constexpr uint8_t LIMIT_SWITCH_PINS[] = {4, 5, 6, 7, 10};
constexpr bool LIMIT_SWITCH_ACTIVE_LOW = true;
constexpr bool LIMIT_SWITCH_USE_INTERNAL_PULLUP = true;

// Keypad 4x4. Thứ tự tương ứng R1..R4 và C1..C4.
constexpr uint8_t KEYPAD_ROW_PINS[] = {11, 12, 13, 14};
constexpr uint8_t KEYPAD_COL_PINS[] = {15, 16, 17, 18};

// TFT ST7789 240x240 qua SPI. Xác nhận lại pinout module thực tế.
constexpr uint8_t TFT_SCLK = 36;
constexpr uint8_t TFT_MOSI = 35;
constexpr uint8_t TFT_CS = 34;
constexpr uint8_t TFT_DC = 33;
constexpr uint8_t TFT_RST = 21;
constexpr uint8_t TFT_BACKLIGHT = 47;
constexpr bool TFT_BACKLIGHT_ACTIVE_HIGH = true;

}  // namespace PinConfig

