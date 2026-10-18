#include "RtcDriver.h"

bool RtcDriver::begin() {
  ready_ = rtc_.begin();
  if (!ready_) return false;

  if (rtc_.lostPower()) {
    rtc_.adjust(DateTime(F(__DATE__), F(__TIME__)));
  }
  return true;
}

bool RtcDriver::isReady() const { return ready_; }

uint32_t RtcDriver::epoch() {
  return ready_ ? rtc_.now().unixtime() : 0;
}

void RtcDriver::syncFromEpoch(uint32_t epochValue) {
  if (!ready_) return;
  rtc_.adjust(DateTime(epochValue));
}
