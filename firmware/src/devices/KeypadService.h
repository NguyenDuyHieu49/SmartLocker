#pragma once

#include <Arduino.h>
#include <Keypad.h>

#include "config/SystemConfig.h"
#include "display/DisplayService.h"

using AccessRequestCallback = void (*)(const String& action, const String& value,
                                       const String& orderCode);

class KeypadService {
 public:
  explicit KeypadService(DisplayService& display);

  void begin(AccessRequestCallback callback);
  void loop();
  void startPickupOtp(const String& orderCode);
  void reset();

 private:
  enum class State { IDLE, DEPOSIT_CODE, PICKUP_ORDER, PICKUP_OTP };

  void render();
  void submit();

  DisplayService& display_;
  Keypad keypad_;
  AccessRequestCallback callback_ = nullptr;
  State state_ = State::IDLE;
  String input_;
  String orderCode_;
};

