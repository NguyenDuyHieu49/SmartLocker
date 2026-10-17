# SmartLocker Firmware MVP

Firmware ESP32-S3 theo phần MVP của `API_SPECIFICATION.md`.

## Chức năng hiện có

- MQTT: `cmd/unlock`, `cmd/set_box`, `cmd/reboot`, `cmd/request_status`.
- MQTT: `status/boxes`, `status/heartbeat`, `evt/door`, `evt/unlock_result`,
  `evt/set_box_result`, `evt/reboot_ack`.
- HTTP local: `/`, `/api/status`, `/api/wifi`, `/api/servo/calib`,
  `/api/reboot`.
- Keypad 4x4: `A` gửi hàng, `B` nhận hàng, `*` xóa, `#` xác nhận, `C` hủy.
- TFT ST7789 240x240 hiển thị hướng dẫn, OTP và QR PayOS.
- Extension MQTT: `cmd/ui` và `evt/access_request` cho luồng người dùng tại tủ.
- NVS lưu Wi-Fi, góc servo và trạng thái occupied.
- Debounce 5 công tắc cửa.
- Chống thực thi lại request MQTT bằng cache RAM và request gần nhất trong NVS.
- Wi-Fi SoftAP dự phòng `SmartBox-Setup`.

## Cấu hình trước khi build

1. Chỉnh GPIO trong `include/config/PinConfig.h`.
2. Chỉnh Wi-Fi, IP Mosquitto và `DEVICE_ID` trong
   `include/config/NetworkConfig.h`.
3. Nếu board không phải DevKitM-1, đổi `board` trong `platformio.ini`.

## Build

```bash
~/.platformio/penv/bin/pio run
```

## Lưu ý

- Chỉ dùng broker anonymous cổng 1883 trong LAN phát triển.
- Năm servo phải có đường nguồn 5V riêng đủ dòng và chung GND với ESP32.
- SG90 không có phản hồi vị trí thật. `unlock_result.success=true` xác nhận
  PCA9685 đã nhận thao tác, không chứng minh cửa đã mở; trạng thái thật đến từ
  công tắc hành trình.
- Phase 1 đã có TFT, keypad và luồng QR/OTP. OTA, SMS production và
  camera thuộc các bước tiếp theo.
