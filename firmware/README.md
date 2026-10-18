# SmartBox ESP32-S3 firmware

Firmware PlatformIO/Arduino thực thi giao thức trong
`SMARTBOX_MQTT_SPECIFICATION.md`. Backend giữ toàn bộ trạng thái đơn hàng và
trạng thái chiếm dụng; ESP32 chỉ điều khiển phần cứng và báo trạng thái vật lý.

## Luồng keypad

- `1`: gửi hàng, chọn kích thước `1 = S` hoặc `2 = M`, nhập số điện thoại 10 số.
- `2`: nhận hàng, nhập OTP 8 số.
- `A`: xác nhận dữ liệu, xác nhận mở khi màn hình yêu cầu hoặc xác nhận đã đóng
  cửa. Sau thanh toán, backend tự gửi lệnh mở nên không cần nhấn `A` lần nữa.
- `*`: xóa ký tự cuối; `C`: hủy và trở về menu.

Firmware phát `evt/keypad` cho dữ liệu và xác nhận mở, phát
`evt/confirm_finish` sau khi người dùng đã đóng cửa rồi nhấn `A`. Cửa đóng đơn
thuần túy không làm hoàn tất nghiệp vụ.

## MQTT

- Lệnh nhận: `cmd/ui`, `cmd/unlock`, `cmd/reboot`, `cmd/request_status`.
- Sự kiện phát: `evt/keypad`, `evt/door`, `evt/confirm_finish`,
  `evt/unlock_result`, `evt/reboot_ack`.
- Trạng thái: `status/boxes` mỗi 30 giây hoặc khi cửa đổi trạng thái,
  `status/heartbeat` mỗi 60 giây và LWT `status/availability`.
- `status/boxes` chỉ chứa `box`, `size`, `door_closed`; không chứa `occupied`.
- Bốn ngăn thuê là `0..3` với kích thước `S, S, M, S`; ngăn `4` là `TECH`.

NVS chỉ lưu cấu hình Wi-Fi, hiệu chỉnh servo và dữ liệu chống thực thi lặp. Nó
không lưu trạng thái đơn hàng hoặc trạng thái chiếm dụng ngăn.

## Phần cứng và build

GPIO nằm trong `include/config/PinConfig.h`; thông tin mạng và thiết bị nằm
trong `include/config/NetworkConfig.h`.

```bash
~/.platformio/penv/bin/pio run
```

| Thiết bị | Chân module | GPIO ESP32-S3 |
| --- | --- | ---: |
| PCA9685 + DS3231 | SDA / SCL | 8 / 9 |
| Công tắc ngăn 0..4 | Signal | 4, 5, 6, 7, 47 |
| Keypad | R1..R4 | 17, 18, 21, 38 |
| Keypad | C1..C4 | 39, 40, 41, 42 |
| TFT ST7789 | MOSI / SCLK | 11 / 12 |
| TFT ST7789 | CS / DC / RST / BL | 10 / 2 / 14 / 15 |
| Buzzer chủ động | Signal | 16 |

PCA9685 dùng `0x40`, DS3231 dùng `0x68`. Công tắc dùng `INPUT_PULLUP` và nối
signal xuống GND khi cửa đóng. Năm servo phải dùng nguồn 5 V riêng đủ dòng,
chung GND với ESP32; không cấp dòng servo qua breadboard. Cảnh báo cửa mở kích
hoạt sau 3 phút.
