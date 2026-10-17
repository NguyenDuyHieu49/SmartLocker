#include "KeypadService.h"

#include "config/PinConfig.h"

namespace {
char keys[4][4] = {
    {'1', '2', '3', 'A'},
    {'4', '5', '6', 'B'},
    {'7', '8', '9', 'C'},
    {'*', '0', '#', 'D'},
};
byte rowPins[4] = {
    PinConfig::KEYPAD_ROW_PINS[0], PinConfig::KEYPAD_ROW_PINS[1],
    PinConfig::KEYPAD_ROW_PINS[2], PinConfig::KEYPAD_ROW_PINS[3]};
byte colPins[4] = {
    PinConfig::KEYPAD_COL_PINS[0], PinConfig::KEYPAD_COL_PINS[1],
    PinConfig::KEYPAD_COL_PINS[2], PinConfig::KEYPAD_COL_PINS[3]};
}  // namespace

KeypadService::KeypadService(DisplayService& display)
    : display_(display),
      keypad_(makeKeymap(keys), rowPins, colPins, 4, 4) {}

void KeypadService::begin(AccessRequestCallback callback) {
  callback_ = callback;
  reset();
}

void KeypadService::loop() {
  const char key = keypad_.getKey();
  if (key == NO_KEY) return;

  if (key == 'C') {
    reset();
    return;
  }
  if (state_ == State::IDLE) {
    if (key == 'A') {
      state_ = State::DEPOSIT_CODE;
      input_ = "";
      render();
    } else if (key == 'B') {
      state_ = State::PICKUP_ORDER;
      input_ = "";
      render();
    }
    return;
  }
  if (key == '*') {
    if (!input_.isEmpty()) input_.remove(input_.length() - 1);
    render();
    return;
  }
  if (key == '#') {
    submit();
    return;
  }
  if (key >= '0' && key <= '9' &&
      input_.length() < SystemConfig::MAX_KEYPAD_INPUT_LENGTH) {
    input_ += key;
    render();
  }
}

void KeypadService::startPickupOtp(const String& orderCode) {
  orderCode_ = orderCode;
  input_ = "";
  state_ = State::PICKUP_OTP;
  render();
}

void KeypadService::reset() {
  state_ = State::IDLE;
  input_ = "";
  orderCode_ = "";
  display_.showIdle();
}

void KeypadService::render() {
  switch (state_) {
    case State::DEPOSIT_CODE:
      display_.showInput("MA GUI HANG", input_, true);
      break;
    case State::PICKUP_ORDER:
      display_.showInput("MA DON HANG", input_);
      break;
    case State::PICKUP_OTP:
      display_.showInput("OTP NHAN HANG", input_, true);
      break;
    default:
      display_.showIdle();
      break;
  }
}

void KeypadService::submit() {
  if (input_.length() < 4 || callback_ == nullptr) {
    display_.showMessage("MA KHONG HOP LE", "Vui long nhap lai", ST77XX_RED);
    return;
  }
  if (state_ == State::DEPOSIT_CODE) {
    callback_("deposit", input_, "");
    display_.showMessage("DANG KIEM TRA", "Cho phan hoi may chu", ST77XX_BLUE);
  } else if (state_ == State::PICKUP_ORDER) {
    orderCode_ = input_;
    callback_("pickup_start", "", orderCode_);
    display_.showMessage("DANG KIEM TRA", "Dang tinh phi luu tru", ST77XX_BLUE);
  } else if (state_ == State::PICKUP_OTP) {
    callback_("pickup_otp", input_, orderCode_);
    display_.showMessage("DANG KIEM TRA", "Dang xac minh OTP", ST77XX_BLUE);
  }
  input_ = "";
}

