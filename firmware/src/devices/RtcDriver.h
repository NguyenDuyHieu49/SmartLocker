#pragma once

#include <Arduino.h>
#include <RTClib.h>

class RtcDriver {
 public:
  bool begin();
  bool isReady() const;
  uint32_t epoch();
  void syncFromEpoch(uint32_t epoch);

 private:
  RTC_DS3231 rtc_;
  bool ready_ = false;
};
