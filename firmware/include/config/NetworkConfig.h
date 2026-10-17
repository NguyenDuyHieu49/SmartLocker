#pragma once

#include <Arduino.h>

namespace NetworkConfig {

// Giá trị mặc định chỉ dùng lần nạp đầu. Có thể đổi Wi-Fi qua POST /api/wifi.
constexpr char WIFI_SSID[] = "CHANGE_ME";
constexpr char WIFI_PASSWORD[] = "CHANGE_ME";

constexpr char FALLBACK_AP_SSID[] = "SmartBox-Setup";
constexpr char FALLBACK_AP_PASSWORD[] = "smartbox123";

// Dùng IP LAN của máy đang chạy Mosquitto, không dùng localhost trên ESP32.
constexpr char MQTT_HOST[] = "192.168.1.100";
constexpr uint16_t MQTT_PORT = 1883;
constexpr char MQTT_USERNAME[] = "";
constexpr char MQTT_PASSWORD[] = "";
// Khi dùng broker Internet: đổi host/port, bật TLS và dán CA của
// nhà cung cấp vào MQTT_ROOT_CA. Chỉ bật INSECURE để chạy thử ngắn hạn.
constexpr bool MQTT_USE_TLS = false;
constexpr bool MQTT_TLS_INSECURE = false;
constexpr char MQTT_ROOT_CA[] = "";

constexpr char DEVICE_ID[] = "SB-001";
constexpr char NTP_SERVER_1[] = "pool.ntp.org";
constexpr char NTP_SERVER_2[] = "time.google.com";

}  // namespace NetworkConfig

