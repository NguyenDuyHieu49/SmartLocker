#include "KeypadService.h"

#include "config/PinConfig.h"

namespace {
char keys[4][4] = {{'1', '2', '3', 'A'}, {'4', '5', '6', 'B'},
                   {'7', '8', '9', 'C'}, {'*', '0', '#', 'D'}};
byte rowPins[4] = {
    PinConfig::KEYPAD_ROW_PINS[0], PinConfig::KEYPAD_ROW_PINS[1],
    PinConfig::KEYPAD_ROW_PINS[2], PinConfig::KEYPAD_ROW_PINS[3]};
byte colPins[4] = {
    PinConfig::KEYPAD_COL_PINS[0], PinConfig::KEYPAD_COL_PINS[1],
    PinConfig::KEYPAD_COL_PINS[2], PinConfig::KEYPAD_COL_PINS[3]};
}  // namespace

KeypadService::KeypadService(DisplayService& display)
    : display_(display), keypad_(makeKeymap(keys), rowPins, colPins, 4, 4) {}

void KeypadService::begin(KeypadEventCallback callback) {
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
  if (state_ == State::MAIN_MENU) {
    if (key == '1') {
      state_ = State::BOX_SELECT;
      render();
    } else if (key == '2') {
      state_ = State::ENTER_OTP;
      input_ = "";
      render();
    }
    return;
  }
  if (state_ == State::BOX_SELECT) {
    if (key == '1' || key == '2') {
      selectedSize_ = key == '1' ? "S" : "M";
      emit("check_box", selectedSize_);
      state_ = State::WAITING_SERVER;
      display_.showLoading("check_box");
    }
    return;
  }
  if (state_ == State::CONFIRM_OPEN && key == 'A') {
    emit("open_confirmed", String(activeBox_), activeMode_);
    state_ = State::WAITING_DOOR;
    return;
  }
  if (state_ == State::CONFIRM_FINISH && key == 'A') {
    emit(activeMode_ == "deposit" ? "deposit_confirmed"
                                   : "pickup_confirmed",
         String(activeBox_));
    state_ = State::WAITING_SERVER;
    display_.showLoading("check_box");
    return;
  }
  if (state_ != State::ENTER_PHONE && state_ != State::ENTER_OTP) return;
  if (key == '*') {
    if (!input_.isEmpty()) input_.remove(input_.length() - 1);
    render();
    return;
  }
  if (key == 'A') {
    submit();
    return;
  }
  const size_t limit = state_ == State::ENTER_PHONE
                           ? SystemConfig::PHONE_LENGTH
                           : SystemConfig::PICKUP_OTP_LENGTH;
  if (key >= '0' && key <= '9' && input_.length() < limit) {
    input_ += key;
    render();
  }
}

void KeypadService::reset() {
  state_ = State::MAIN_MENU;
  input_ = "";
  selectedSize_ = "";
  activeMode_ = "";
  activeBox_ = -1;
  activeDoorOpened_ = false;
  display_.showMainMenu();
}

void KeypadService::showScene(const String& screen, const String& mode,
                              int8_t box) {
  if (screen == "idle" || screen == "main_menu") {
    reset();
  } else if (screen == "box_select") {
    state_ = State::BOX_SELECT;
    render();
  } else if (screen == "enter_phone") {
    state_ = State::ENTER_PHONE;
    input_ = "";
    render();
  } else if (screen == "enter_otp") {
    state_ = State::ENTER_OTP;
    input_ = "";
    render();
  } else if (screen == "door_guide" || screen == "result") {
    activeMode_ = mode;
    activeBox_ = box;
    activeDoorOpened_ = false;
    state_ = State::CONFIRM_OPEN;
  } else if (screen == "opening") {
    activeMode_ = mode;
    activeBox_ = box;
    activeDoorOpened_ = false;
    state_ = State::WAITING_DOOR;
  } else if (screen == "loading" || screen == "payment" ||
             screen == "overdue") {
    state_ = State::WAITING_SERVER;
  }
}

void KeypadService::onDoorStateChanged(uint8_t box, bool closed) {
  if (activeBox_ < 0 || box != static_cast<uint8_t>(activeBox_)) return;
  if (!closed) {
    activeDoorOpened_ = true;
    state_ = State::WAITING_DOOR;
  } else if (activeDoorOpened_ && state_ == State::WAITING_DOOR) {
    state_ = State::CONFIRM_FINISH;
    display_.showFinishPrompt(activeMode_, box);
  }
}

void KeypadService::render() {
  switch (state_) {
    case State::MAIN_MENU:
      display_.showMainMenu();
      break;
    case State::BOX_SELECT:
      display_.showBoxSelect();
      break;
    case State::ENTER_PHONE:
      display_.showInput("SDT NGUOI NHAN", input_);
      break;
    case State::ENTER_OTP:
      display_.showInput("OTP 8 SO", input_, true);
      break;
    default:
      break;
  }
}

void KeypadService::submit() {
  const State submittedState = state_;
  if (submittedState == State::ENTER_PHONE) {
    if (input_.length() != SystemConfig::PHONE_LENGTH || input_[0] != '0') {
      display_.showMessage("SDT KHONG HOP LE", "Nhap dung 10 chu so",
                           ST77XX_RED);
      return;
    }
    emit("deposit_phone", input_, selectedSize_);
  } else if (submittedState == State::ENTER_OTP) {
    if (input_.length() != SystemConfig::PICKUP_OTP_LENGTH) {
      display_.showMessage("OTP KHONG HOP LE", "Nhap dung 8 chu so",
                           ST77XX_RED);
      return;
    }
    emit("pickup_otp", input_);
  }
  input_ = "";
  state_ = State::WAITING_SERVER;
  display_.showLoading(submittedState == State::ENTER_OTP ? "verify_otp"
                                                          : "create_order");
}

void KeypadService::emit(const String& action, const String& value,
                         const String& extra) {
  if (callback_ != nullptr) callback_(action, value, extra);
}
