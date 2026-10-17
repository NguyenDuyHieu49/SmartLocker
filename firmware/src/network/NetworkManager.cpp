#include "NetworkManager.h"

#include <WiFi.h>

#include "config/NetworkConfig.h"
#include "config/SystemConfig.h"

NetworkManager::NetworkManager(StorageManager& storage) : storage_(storage) {}

void NetworkManager::begin() {
  ssid_ = storage_.getWifiSsid();
  password_ = storage_.getWifiPassword();
  if (ssid_.isEmpty()) {
    ssid_ = NetworkConfig::WIFI_SSID;
    password_ = NetworkConfig::WIFI_PASSWORD;
  }
  connectStation();
}

void NetworkManager::connectStation() {
  WiFi.mode(WIFI_AP_STA);
  WiFi.begin(ssid_.c_str(), password_.c_str());
  connectStartedAt_ = millis();
  lastRetryAt_ = millis();
}

void NetworkManager::startFallbackAp() {
  if (fallbackApActive_) return;
  fallbackApActive_ = WiFi.softAP(NetworkConfig::FALLBACK_AP_SSID,
                                  NetworkConfig::FALLBACK_AP_PASSWORD);
}

void NetworkManager::loop() {
  if (isConnected()) return;

  const uint32_t now = millis();
  if (now - connectStartedAt_ >= SystemConfig::WIFI_CONNECT_TIMEOUT_MS) {
    startFallbackAp();
  }

  if (now - lastRetryAt_ >= SystemConfig::WIFI_RETRY_INTERVAL_MS) {
    WiFi.disconnect();
    WiFi.begin(ssid_.c_str(), password_.c_str());
    lastRetryAt_ = now;
  }
}

void NetworkManager::reconnectWith(const String& ssid, const String& password) {
  storage_.setWifiCredentials(ssid, password);
  ssid_ = ssid;
  password_ = password;
  WiFi.disconnect();
  connectStation();
}

bool NetworkManager::isConnected() const {
  return WiFi.status() == WL_CONNECTED;
}

bool NetworkManager::isFallbackApActive() const { return fallbackApActive_; }

String NetworkManager::currentSsid() const {
  return isConnected() ? WiFi.SSID() : ssid_;
}

String NetworkManager::ipAddress() const {
  if (isConnected()) return WiFi.localIP().toString();
  if (fallbackApActive_) return WiFi.softAPIP().toString();
  return "0.0.0.0";
}

int32_t NetworkManager::rssi() const { return isConnected() ? WiFi.RSSI() : 0; }

