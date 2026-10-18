#pragma once

#include <Adafruit_ST7789.h>
#include <Arduino.h>
#include <SPI.h>

class DisplayService {
 public:
  bool begin();
  void showIdle();
  void showMainMenu();
  void showBoxSelect();
  void showInput(const String& title, const String& value, bool secret = false);
  void showMessage(const String& title, const String& message,
                   uint16_t color = ST77XX_WHITE);
  void showPayment(const String& orderCode, uint32_t amount,
                   const String& qrData);
  void showEnterOtp(const String& orderCode);
  void showDoorGuide(const String& mode, uint8_t box);
  void showResult(const String& otp, uint8_t box);
  void showOverdue(uint8_t box, uint16_t days, uint32_t dailyRate,
                   uint32_t amount);
  void showLoading(const String& mode);
  void showFinishPrompt(const String& mode, uint8_t box);

 private:
  void header(const String& title, uint16_t color);
  void centeredText(const String& text, int16_t y, uint8_t size,
                    uint16_t color);
  bool drawQr(const String& data, int16_t top);

  SPIClass spi_{FSPI};
  Adafruit_ST7789 display_{&spi_, -1, -1, -1};
  bool ready_ = false;
};

