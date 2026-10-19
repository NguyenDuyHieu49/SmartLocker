#include "MqttService.h"

#include <ArduinoJson.h>
#include <time.h>

#include "config/NetworkConfig.h"

MqttService::MqttService(NetworkManager& network, StorageManager& storage,
                         PcaServoDriver& servo, LimitSwitchDriver& switches,
                         DisplayService& display, KeypadService& keypad,
                         RtcDriver& rtc)
    : network_(network),
      storage_(storage),
      servo_(servo),
      switches_(switches),
      display_(display),
      keypad_(keypad),
      rtc_(rtc),
      client_(SystemConfig::MQTT_BUFFER_SIZE) {}

void MqttService::begin() {
  if (NetworkConfig::MQTT_USE_TLS) {
    if (strlen(NetworkConfig::MQTT_ROOT_CA) > 0) {
      secureClient_.setCACert(NetworkConfig::MQTT_ROOT_CA);
    } else if (NetworkConfig::MQTT_TLS_INSECURE) {
      secureClient_.setInsecure();
    }
    client_.begin(NetworkConfig::MQTT_HOST, NetworkConfig::MQTT_PORT,
                  secureClient_);
  } else {
    client_.begin(NetworkConfig::MQTT_HOST, NetworkConfig::MQTT_PORT,
                  wifiClient_);
  }
  client_.onMessage([this](String& incomingTopic, String& payload) {
    onMessage(incomingTopic, payload);
  });
  client_.setWill(topic("status/availability").c_str(), "offline", true, 1);
}

String MqttService::topic(const char* suffix) const {
  return String("smartbox/") + NetworkConfig::DEVICE_ID + "/" + suffix;
}

void MqttService::connect() {
  if (!network_.isConnected() || client_.connected()) return;
  if (millis() - lastConnectAttemptAt_ < SystemConfig::MQTT_RETRY_INTERVAL_MS) {
    return;
  }
  lastConnectAttemptAt_ = millis();

  const String clientId = String("smartbox-") + NetworkConfig::DEVICE_ID;
  bool connected = false;
  if (strlen(NetworkConfig::MQTT_USERNAME) > 0) {
    connected = client_.connect(clientId.c_str(), NetworkConfig::MQTT_USERNAME,
                                NetworkConfig::MQTT_PASSWORD);
  } else {
    connected = client_.connect(clientId.c_str());
  }
  if (!connected) return;

  client_.subscribe(topic("cmd/unlock"), 1);
  client_.subscribe(topic("cmd/reboot"), 1);
  client_.subscribe(topic("cmd/request_status"), 0);
  client_.subscribe(topic("cmd/ui"), 1);
  client_.publish(topic("status/availability"), "online", true, 1);
  publishBoxesStatus();
}

void MqttService::loop() {
  connect();
  client_.loop();

  if (client_.connected()) {
    const uint32_t now = millis();
    if (now - lastHeartbeatAt_ >= SystemConfig::HEARTBEAT_INTERVAL_MS) {
      publishHeartbeat();
      lastHeartbeatAt_ = now;
    }
    if (now - lastStatusAt_ >= SystemConfig::STATUS_REPORT_INTERVAL_MS) {
      publishBoxesStatus();
      lastStatusAt_ = now;
    }
  }

  if (rebootPending_ &&
      static_cast<int32_t>(millis() - rebootAt_) >= 0) {
    ESP.restart();
  }
}

bool MqttService::isConnected() { return client_.connected(); }

void MqttService::onMessage(String& incomingTopic, String& payload) {
  if (incomingTopic == topic("cmd/unlock")) {
    handleUnlock(payload);
  } else if (incomingTopic == topic("cmd/reboot")) {
    handleReboot(payload);
  } else if (incomingTopic == topic("cmd/request_status")) {
    publishBoxesStatus();
  } else if (incomingTopic == topic("cmd/ui")) {
    handleUi(payload);
  }
}

void MqttService::handleUi(const String& payload) {
  JsonDocument document;
  if (deserializeJson(document, payload) != DeserializationError::Ok) return;
  const String screen = document["screen"] | "message";
  const String orderCode = document["order_code"] | "";
  const String mode = document["mode"] | "";
  const int8_t box = document["box"] | -1;
  if (screen == "idle" || screen == "main_menu") {
    keypad_.showScene(screen);
  } else if (screen == "box_select" || screen == "enter_phone" ||
             screen == "enter_otp") {
    keypad_.showScene(screen);
  } else if (screen == "payment") {
    const uint32_t amount = document["amount_vnd"] | 0;
    const String qrCode = document["qr_code"] | "";
    display_.showPayment(orderCode, amount, qrCode);
    keypad_.showScene(screen);
  } else if (screen == "door_guide") {
    const bool autoOpen = document["auto_open"] | false;
    if (autoOpen) {
      display_.showOpening(mode, static_cast<uint8_t>(box));
      keypad_.showScene("opening", mode, box);
    } else {
      display_.showDoorGuide(mode, static_cast<uint8_t>(box));
      keypad_.showScene(screen, mode, box);
    }
  } else if (screen == "result") {
    const String otp = document["otp"] | "";
    const bool autoOpen = document["auto_open"] | false;
    display_.showResult(otp, static_cast<uint8_t>(box));
    keypad_.showScene(autoOpen ? "opening" : screen, "deposit", box);
  } else if (screen == "opening") {
    display_.showOpening(mode, static_cast<uint8_t>(box));
    keypad_.showScene(screen, mode, box);
  } else if (screen == "overdue") {
    display_.showOverdue(static_cast<uint8_t>(box),
                         document["overdue_days"] | 0,
                         document["daily_rate"] | 0,
                         document["amount_vnd"] | 0);
    keypad_.showScene(screen);
  } else if (screen == "loading") {
    const String loadingMode = document["loading_mode"] | "";
    display_.showLoading(loadingMode);
    keypad_.showScene(screen);
  } else {
    const String title = document["title"] | "THONG BAO";
    const String message = document["message"] | "";
    const bool success = document["success"] | false;
    display_.showMessage(title, message, success ? ST77XX_GREEN : ST77XX_RED);
  }
}

void MqttService::handleUnlock(const String& payload) {
  JsonDocument document;
  if (deserializeJson(document, payload) != DeserializationError::Ok) return;

  const int boxValue = document["box"] | -1;
  const String requestId = document["request_id"] | "";
  if (boxValue < 0 || boxValue >= SystemConfig::TOTAL_BOXES) {
    publishUnlockResult(static_cast<uint8_t>(max(boxValue, 0)), requestId, false,
                        "invalid_box");
    return;
  }
  const uint8_t box = static_cast<uint8_t>(boxValue);
  if (requestId.isEmpty()) {
    publishUnlockResult(box, requestId, false, "invalid_request");
    return;
  }

  if (wasRequestProcessed(requestId)) {
    publishUnlockResult(box, requestId, true, nullptr);
    return;
  }

  const bool success = servo_.requestUnlock(box);
  if (success) rememberRequest(requestId);
  publishUnlockResult(box, requestId, success,
                      success ? nullptr : "servo_fault");
}

void MqttService::handleReboot(const String& payload) {
  JsonDocument document;
  if (deserializeJson(document, payload) != DeserializationError::Ok) return;
  const String requestId = document["request_id"] | "";
  if (requestId.isEmpty() || wasRequestProcessed(requestId)) return;

  rememberRequest(requestId);
  JsonDocument response;
  response["request_id"] = requestId;
  response["reboot_in_ms"] = SystemConfig::REBOOT_DELAY_MS;
  String serialized;
  serializeJson(response, serialized);
  client_.publish(topic("evt/reboot_ack"), serialized, false, 1);
  rebootPending_ = true;
  rebootAt_ = millis() + SystemConfig::REBOOT_DELAY_MS;
}

void MqttService::publishUnlockResult(uint8_t box, const String& requestId,
                                      bool success, const char* error) {
  JsonDocument document;
  document["box"] = box;
  document["request_id"] = requestId;
  document["success"] = success;
  if (error == nullptr) {
    document["error"] = nullptr;
  } else {
    document["error"] = error;
  }
  String payload;
  serializeJson(document, payload);
  client_.publish(topic("evt/unlock_result"), payload, false, 1);
}

void MqttService::publishDoorEvent(uint8_t box, bool doorClosed) {
  if (!client_.connected()) return;
  JsonDocument document;
  document["box"] = box;
  document["door_closed"] = doorClosed;
  document["timestamp"] = timestamp();
  String payload;
  serializeJson(document, payload);
  client_.publish(topic("evt/door"), payload, false, 1);
  publishBoxesStatus();
}

void MqttService::publishKeypadEvent(const String& action, const String& value,
                                     const String& extra) {
  if (!client_.connected()) {
    display_.showMessage("MAT KET NOI", "Thu lai khi co mang", ST77XX_RED);
    return;
  }
  JsonDocument document;
  document["action"] = action;
  if (action == "deposit_confirmed" || action == "pickup_confirmed") {
    publishConfirmFinish(action, static_cast<uint8_t>(value.toInt()));
    return;
  }
  document["value"] = value;
  if (!extra.isEmpty()) document["extra"] = extra;
  document["timestamp"] = timestamp();
  String payload;
  serializeJson(document, payload);
  client_.publish(topic("evt/keypad"), payload, false, 1);
}

void MqttService::publishConfirmFinish(const String& action, uint8_t box) {
  JsonDocument document;
  document["action"] = action;
  document["box"] = box;
  document["timestamp"] = timestamp();
  String payload;
  serializeJson(document, payload);
  client_.publish(topic("evt/confirm_finish"), payload, false, 1);
}

void MqttService::publishBoxesStatus() {
  if (!client_.connected()) return;
  JsonDocument document;
  document["device_id"] = NetworkConfig::DEVICE_ID;
  document["timestamp"] = timestamp();
  JsonArray boxes = document["boxes"].to<JsonArray>();
  static const char* sizes[] = {"S", "S", "M", "S", "TECH"};
  for (uint8_t box = 0; box < SystemConfig::TOTAL_BOXES; ++box) {
    JsonObject item = boxes.add<JsonObject>();
    item["box"] = box;
    item["size"] = sizes[box];
    item["door_closed"] = switches_.isDoorClosed(box);
  }
  String payload;
  serializeJson(document, payload);
  client_.publish(topic("status/boxes"), payload, true, 0);
}

void MqttService::publishHeartbeat() {
  JsonDocument document;
  document["device_id"] = NetworkConfig::DEVICE_ID;
  document["uptime_s"] = millis() / 1000UL;
  document["wifi_rssi"] = network_.rssi();
  document["free_heap"] = ESP.getFreeHeap();
  document["timestamp"] = timestamp();
  String payload;
  serializeJson(document, payload);
  client_.publish(topic("status/heartbeat"), payload, true, 0);
}

void MqttService::rememberRequest(const String& requestId) {
  processedRequests_[requestCursor_] = requestId;
  requestCursor_ =
      (requestCursor_ + 1) % SystemConfig::PROCESSED_REQUEST_CACHE_SIZE;
  storage_.setLastRequestId(requestId);
}

bool MqttService::wasRequestProcessed(const String& requestId) const {
  if (requestId.isEmpty()) return false;
  if (storage_.getLastRequestId() == requestId) return true;
  for (const String& processed : processedRequests_) {
    if (processed == requestId) return true;
  }
  return false;
}

uint32_t MqttService::timestamp() {
  const time_t now = time(nullptr);
  if (now > 1700000000) return static_cast<uint32_t>(now);
  const uint32_t rtcEpoch = rtc_.epoch();
  return rtcEpoch > 1700000000 ? rtcEpoch : millis() / 1000UL;
}

