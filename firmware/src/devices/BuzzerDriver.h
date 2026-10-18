#pragma once

#include <Arduino.h>

class BuzzerDriver {
 public:
  void begin();
  void loop();
  void beep(uint16_t durationMs = 80);
  void startAlarm();
  void stopAlarm();
  bool isAlarming() const;

 private:
  void write(bool enabled);

  bool alarming_ = false;
  bool beeping_ = false;
  bool outputOn_ = false;
  uint32_t beepUntil_ = 0;
  uint32_t lastAlarmToggleAt_ = 0;
};
