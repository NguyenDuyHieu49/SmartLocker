#pragma once

#include <Arduino.h>
#include <Keypad.h>

#include "config/SystemConfig.h"
#include "display/DisplayService.h"

using KeypadEventCallback = void (*)(const String& action, const String& value,
                                     const String& extra);

class KeypadService {
 public:
  explicit KeypadService(DisplayService& display);
  void begin(KeypadEventCallback callback);
  void loop();
  void reset();
  void showScene(const String& screen, const String& mode = "",
                 int8_t box = -1);
  void onDoorStateChanged(uint8_t box, bool closed);

 private:
  enum class State {
    MAIN_MENU,
    BOX_SELECT,
    ENTER_PHONE,
    ENTER_OTP,
    WAITING_SERVER,
    CONFIRM_OPEN,
    WAITING_DOOR,
    CONFIRM_FINISH,
  };
  void render();
  void submit();
  void emit(const String& action, const String& value = "",
            const String& extra = "");

  DisplayService& display_;
  Keypad keypad_;
  KeypadEventCallback callback_ = nullptr;
  State state_ = State::MAIN_MENU;
  String input_;
  String selectedSize_;
  String activeMode_;
  int8_t activeBox_ = -1;
  bool activeDoorOpened_ = false;
};
