#include "LocalWebServer.h"

#include <ArduinoJson.h>

#include "config/NetworkConfig.h"
#include "config/SystemConfig.h"

LocalWebServer::LocalWebServer(NetworkManager& network, StorageManager& storage,
                               MqttService& mqtt,
                               PcaServoDriver& servo,
                               LimitSwitchDriver& switches)
    : network_(network),
      storage_(storage),
      mqtt_(mqtt),
      servo_(servo),
      switches_(switches) {}

void LocalWebServer::begin() {
  server_.on("/", HTTP_GET, [this]() { handleRoot(); });
  server_.on("/api/status", HTTP_GET, [this]() { handleStatus(); });
  server_.on("/api/wifi", HTTP_POST, [this]() { handleWifi(); });
  server_.on("/api/servo/calib", HTTP_POST,
             [this]() { handleServoCalibration(); });
  server_.on("/api/reboot", HTTP_POST, [this]() { handleReboot(); });
  server_.onNotFound([this]() { sendJsonError(404, "not_found"); });
  server_.begin();
}

void LocalWebServer::loop() { server_.handleClient(); }

void LocalWebServer::handleRoot() {
  static const char page[] PROGMEM = R"HTML(
<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SmartBox Local</title></head><body>
<h1>SmartBox Local</h1>
<p>Thiết bị: SB-001</p>
<p><a href="/api/status">Xem trạng thái JSON</a></p>
<p>Cấu hình Wi-Fi và servo qua các endpoint trong API_SPECIFICATION.md.</p>
</body></html>)HTML";
  server_.send(200, "text/html; charset=utf-8", page);
}

void LocalWebServer::handleStatus() {
  JsonDocument document;
  document["device_id"] = NetworkConfig::DEVICE_ID;
  document["firmware"] = "0.1.0-mvp";
  document["uptime_s"] = millis() / 1000UL;
  JsonObject wifi = document["wifi"].to<JsonObject>();
  wifi["ssid"] = network_.currentSsid();
  wifi["rssi"] = network_.rssi();
  wifi["ip"] = network_.ipAddress();
  document["mqtt_connected"] = mqtt_.isConnected();
  JsonArray boxes = document["boxes"].to<JsonArray>();
  for (uint8_t box = 0; box < SystemConfig::TOTAL_BOXES; ++box) {
    JsonObject item = boxes.add<JsonObject>();
    item["box"] = box;
    item["occupied"] = storage_.getOccupied(box);
    item["door_closed"] = switches_.isDoorClosed(box);
  }
  String payload;
  serializeJson(document, payload);
  server_.send(200, "application/json", payload);
}

void LocalWebServer::handleWifi() {
  JsonDocument document;
  if (deserializeJson(document, server_.arg("plain")) !=
      DeserializationError::Ok) {
    sendJsonError(400, "invalid_json");
    return;
  }
  const String ssid = document["ssid"] | "";
  const String password = document["password"] | "";
  if (ssid.isEmpty()) {
    sendJsonError(422, "ssid_required");
    return;
  }
  network_.reconnectWith(ssid, password);
  server_.send(200, "application/json",
               R"({"success":true,"message":"WiFi config saved. Reconnecting..."})");
}

void LocalWebServer::handleServoCalibration() {
  JsonDocument document;
  if (deserializeJson(document, server_.arg("plain")) !=
      DeserializationError::Ok) {
    sendJsonError(400, "invalid_json");
    return;
  }
  const int box = document["box"] | -1;
  const int lockAngle = document["lock_angle"] | -1;
  const int unlockAngle = document["unlock_angle"] | -1;
  if (box < 0 || box >= SystemConfig::TOTAL_BOXES || lockAngle < 0 ||
      lockAngle > 180 || unlockAngle < 0 || unlockAngle > 180) {
    sendJsonError(422, "invalid_calibration");
    return;
  }

  const bool success = servo_.calibrate(static_cast<uint8_t>(box), lockAngle,
                                        unlockAngle);
  JsonDocument response;
  response["success"] = success;
  response["box"] = box;
  response["lock_angle"] = lockAngle;
  response["unlock_angle"] = unlockAngle;
  String payload;
  serializeJson(response, payload);
  server_.send(success ? 200 : 503, "application/json", payload);
}

void LocalWebServer::handleReboot() {
  server_.send(200, "application/json",
               R"({"success":true,"message":"Rebooting in 1s..."})");
  delay(1000);
  ESP.restart();
}

void LocalWebServer::sendJsonError(int code, const char* message) {
  JsonDocument document;
  document["success"] = false;
  document["error"] = message;
  String payload;
  serializeJson(document, payload);
  server_.send(code, "application/json", payload);
}

