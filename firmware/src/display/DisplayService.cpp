#include "DisplayService.h"

#include <qrcode.h>

#include "config/PinConfig.h"
#include "config/SystemConfig.h"

bool DisplayService::begin() {
  pinMode(PinConfig::TFT_BACKLIGHT, OUTPUT);
  digitalWrite(PinConfig::TFT_BACKLIGHT,
               PinConfig::TFT_BACKLIGHT_ACTIVE_HIGH ? HIGH : LOW);
  spi_.begin(PinConfig::TFT_SCLK, -1, PinConfig::TFT_MOSI,
             PinConfig::TFT_CS);
  display_ = Adafruit_ST7789(&spi_, PinConfig::TFT_CS, PinConfig::TFT_DC,
                             PinConfig::TFT_RST);
  display_.init(SystemConfig::TFT_WIDTH, SystemConfig::TFT_HEIGHT);
  display_.setRotation(0);
  display_.setTextWrap(true);
  ready_ = true;
  showIdle();
  return true;
}

void DisplayService::header(const String& title, uint16_t color) {
  if (!ready_) return;
  display_.fillScreen(ST77XX_BLACK);
  display_.fillRect(0, 0, SystemConfig::TFT_WIDTH, 38, color);
  display_.setTextColor(ST77XX_BLACK);
  display_.setTextSize(2);
  display_.setCursor(10, 11);
  display_.print(title);
}

void DisplayService::centeredText(const String& text, int16_t y, uint8_t size,
                                  uint16_t color) {
  display_.setTextSize(size);
  display_.setTextColor(color, ST77XX_BLACK);
  int16_t x1 = 0;
  int16_t y1 = 0;
  uint16_t width = 0;
  uint16_t height = 0;
  display_.getTextBounds(text, 0, y, &x1, &y1, &width, &height);
  display_.setCursor(max(0, (SystemConfig::TFT_WIDTH - width) / 2), y);
  display_.print(text);
}

void DisplayService::showIdle() {
  showMainMenu();
}

void DisplayService::showMainMenu() {
  header("SMARTBOX", ST77XX_CYAN);
  centeredText("1 - GUI HANG", 76, 2, ST77XX_WHITE);
  centeredText("2 - NHAN HANG", 112, 2, ST77XX_WHITE);
  centeredText("A Xac nhan", 170, 1, ST77XX_GREEN);
  centeredText("* Xoa  |  C Huy", 192, 1, ST77XX_YELLOW);
}

void DisplayService::showBoxSelect() {
  header("CHON KICH THUOC", ST77XX_CYAN);
  centeredText("1 - Ngan S", 82, 2, ST77XX_WHITE);
  centeredText("2 - Ngan M", 122, 2, ST77XX_WHITE);
  centeredText("C - Quay lai", 194, 1, ST77XX_YELLOW);
}

void DisplayService::showInput(const String& title, const String& value,
                               bool secret) {
  header(title, ST77XX_BLUE);
  String shown = value;
  if (secret) {
    shown = "";
    for (size_t index = 0; index < value.length(); ++index) shown += '*';
  }
  if (shown.isEmpty()) shown = "_";
  centeredText(shown, 95, 3, ST77XX_WHITE);
  centeredText("A Xac nhan", 178, 1, ST77XX_GREEN);
  centeredText("* Xoa  |  C Huy", 200, 1, ST77XX_YELLOW);
}

void DisplayService::showMessage(const String& title, const String& message,
                                 uint16_t color) {
  header(title, color);
  display_.setTextColor(ST77XX_WHITE);
  display_.setTextSize(2);
  display_.setCursor(12, 70);
  display_.print(message);
  centeredText("Nhan C de quay lai", 208, 1, ST77XX_YELLOW);
}

bool DisplayService::drawQr(const String& data, int16_t top) {
  if (data.isEmpty()) return false;
  constexpr uint8_t version = 10;
  uint8_t buffer[qrcode_getBufferSize(version)];
  QRCode qrCode;
  qrcode_initText(&qrCode, buffer, version, ECC_LOW, data.c_str());
  const uint8_t scale = max(1, 180 / qrCode.size);
  const int16_t qrPixels = qrCode.size * scale;
  const int16_t left = (SystemConfig::TFT_WIDTH - qrPixels) / 2;
  display_.fillRect(left - 4, top - 4, qrPixels + 8, qrPixels + 8,
                    ST77XX_WHITE);
  for (uint8_t y = 0; y < qrCode.size; ++y) {
    for (uint8_t x = 0; x < qrCode.size; ++x) {
      if (qrcode_getModule(&qrCode, x, y)) {
        display_.fillRect(left + x * scale, top + y * scale, scale, scale,
                          ST77XX_BLACK);
      }
    }
  }
  return true;
}

void DisplayService::showPayment(const String& orderCode, uint32_t amount,
                                 const String& qrData) {
  header("THANH TOAN", ST77XX_YELLOW);
  display_.setTextColor(ST77XX_WHITE);
  display_.setTextSize(1);
  display_.setCursor(8, 44);
  display_.printf("Don %s - %lu VND", orderCode.c_str(), amount);
  if (!drawQr(qrData, 60)) {
    showMessage("LOI QR", "Khong co du lieu QR", ST77XX_RED);
  }
}

void DisplayService::showEnterOtp(const String& orderCode) {
  header("NHAP OTP", ST77XX_GREEN);
  centeredText(String("Don ") + orderCode, 70, 2, ST77XX_WHITE);
  centeredText("Nhap ma OTP", 112, 2, ST77XX_WHITE);
  centeredText("roi nhan #", 144, 2, ST77XX_WHITE);
}

void DisplayService::showDoorGuide(const String& mode, uint8_t box) {
  header(mode == "deposit" ? "GUI HANG" : "NHAN HANG", ST77XX_GREEN);
  centeredText(String("Ngan ") + String(box + 1), 76, 3, ST77XX_WHITE);
  centeredText("Nhan A de mo tu", 135, 2, ST77XX_GREEN);
  centeredText("Dong cua sau khi thao tac", 184, 1, ST77XX_YELLOW);
}

void DisplayService::showResult(const String& otp, uint8_t box) {
  header("THANH TOAN XONG", ST77XX_GREEN);
  centeredText(String("Ngan ") + String(box + 1), 55, 2, ST77XX_WHITE);
  centeredText("MA NHAN HANG", 94, 1, ST77XX_YELLOW);
  centeredText(otp, 120, 3, ST77XX_WHITE);
  centeredText("Luu ma - Tu dang mo", 190, 1, ST77XX_GREEN);
}

void DisplayService::showOpening(const String& mode, uint8_t box) {
  header("THANH TOAN XONG", ST77XX_GREEN);
  centeredText(String("Ngan ") + String(box + 1), 76, 3, ST77XX_WHITE);
  centeredText("Dang mo khoa...", 132, 2, ST77XX_GREEN);
  centeredText(mode == "pickup" ? "Lay hang va dong cua"
                                  : "Dat hang va dong cua",
               184, 1, ST77XX_YELLOW);
}

void DisplayService::showOverdue(uint8_t box, uint16_t days,
                                 uint32_t dailyRate, uint32_t amount) {
  header("QUA HAN", ST77XX_RED);
  centeredText(String("Ngan ") + String(box + 1), 50, 2, ST77XX_WHITE);
  centeredText(String("Tre ") + String(days) + " ngay", 84, 2, ST77XX_YELLOW);
  centeredText(String(dailyRate) + " VND/ngay", 120, 1, ST77XX_WHITE);
  centeredText(String("Tong: ") + String(amount) + " VND", 150, 2,
               ST77XX_WHITE);
  centeredText("Cho ma QR thanh toan", 200, 1, ST77XX_GREEN);
}

void DisplayService::showLoading(const String& mode) {
  header("DANG XU LY", ST77XX_BLUE);
  centeredText(mode == "verify_otp" ? "Dang xac thuc OTP"
                                      : "Vui long cho",
               104, 2, ST77XX_WHITE);
}

void DisplayService::showFinishPrompt(const String& mode, uint8_t box) {
  header("DA DONG CUA", ST77XX_GREEN);
  centeredText(String("Ngan ") + String(box + 1), 74, 3, ST77XX_WHITE);
  centeredText("Nhan A de hoan tat", 135, 2, ST77XX_GREEN);
  centeredText(mode == "deposit" ? "Xac nhan gui hang" : "Xac nhan nhan hang",
               182, 1, ST77XX_YELLOW);
}

