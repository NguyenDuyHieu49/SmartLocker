# SmartBox Phase 1 — Kiến trúc triển khai

Tài liệu nghiệp vụ chuẩn là `SMARTBOX_MQTT_SPECIFICATION.md`. File này mô tả
cách code hiện tại triển khai specification; khi hai tài liệu xung đột, MQTT
specification được ưu tiên.

## Ranh giới trách nhiệm

- Backend quyết định cấp ngăn, quyền mở, OTP, phí, thanh toán và trạng thái đơn.
- ESP32 điều khiển servo, đọc cửa, nhận keypad, hiển thị TFT và phát telemetry.
- ESP32 không lưu `occupied`, order hoặc quyền mở trong NVS.
- Webhook có chữ ký là nguồn xác nhận thanh toán; trang success không phải bằng
  chứng thanh toán.
- `door_closed` là trạng thái vật lý. Chỉ `evt/confirm_finish` hợp lệ mới hoàn
  tất gửi hoặc nhận hàng.

## Ngăn tủ

| Box | Kích thước | Mục đích |
| ---: | --- | --- |
| 0 | S | Cho thuê |
| 1 | S | Cho thuê |
| 2 | M | Cho thuê |
| 3 | S | Cho thuê |
| 4 | TECH | Kỹ thuật/admin, không cấp tự động |

## Luồng gửi hàng

1. Shipper chọn Gửi hàng, chọn S/M và nhập số điện thoại 10 số trên keypad.
2. ESP phát `evt/keypad` với action `deposit_phone`.
3. Backend cấp box `0..3`, tạo đơn, OTP 8 số và payment QR phí cơ bản.
4. Sau webhook thanh toán, backend gửi `cmd/ui` màn hình `result`, rồi gửi
   `cmd/unlock` với purpose `DEPOSIT` để tự động mở đúng ngăn.
5. ESP phát `evt/unlock_result` và các `evt/door`.
6. Sau khi cửa đã đóng, shipper nhấn `A`; ESP phát `evt/confirm_finish` action
   `deposit_confirmed`.
7. Backend chuyển đơn sang `STORED`, ngăn sang `OCCUPIED` và bắt đầu tính thời
   gian lưu.

Backend chống lặp webhook và chỉ phát lệnh mở một lần cho mỗi khoản thanh toán.
Nếu MQTT đang mất kết nối, khoản thanh toán vẫn được ghi nhận và lỗi mở tự động
được lưu vào audit để admin xử lý.

## Luồng nhận hàng

1. Người nhận nhập OTP 8 số; ESP phát `evt/keypad/pickup_otp`.
2. Nếu chưa quá hạn, backend hiển thị `door_guide`. Nếu quá hạn, backend tạo QR
   phụ phí; webhook thanh toán sẽ tự động gửi lệnh mở đúng ngăn.
3. Với đơn chưa quá hạn, người nhận nhấn `A`; ESP phát `open_confirmed` và
   backend gửi `cmd/unlock` với purpose `PICKUP`. Với đơn vừa thanh toán phụ
   phí, bước này đã được webhook thực hiện tự động.
4. Sau khi lấy hàng, đóng cửa và nhấn `A`, ESP phát `evt/confirm_finish` action
   `pickup_confirmed`.
5. Backend chuyển đơn sang `COMPLETED` và ngăn sang `AVAILABLE`.

## MQTT bắt buộc

Prefix: `smartbox/{device_id}/`.

| Topic | Hướng | QoS | Retain |
| --- | --- | ---: | ---: |
| `cmd/ui` | Backend → ESP | 1 | No |
| `cmd/unlock` | Backend → ESP | 1 | No |
| `cmd/reboot` | Backend → ESP | 1 | No |
| `cmd/request_status` | Backend → ESP | 0 | No |
| `evt/keypad` | ESP → Backend | 1 | No |
| `evt/door` | ESP → Backend | 1 | No |
| `evt/confirm_finish` | ESP → Backend | 1 | No |
| `evt/unlock_result` | ESP → Backend | 1 | No |
| `status/boxes` | ESP → Backend | 0 | Yes |
| `status/heartbeat` | ESP → Backend | 0 | Yes |
| `status/availability` | Hai chiều/LWT | 1 | Yes |

`status/boxes` được phát mỗi 30 giây hoặc khi cửa đổi trạng thái, chỉ gồm
`box`, `size`, `door_closed`. Heartbeat phát mỗi 60 giây. Backend kiểm tra schema
mọi payload trước khi cập nhật registry hoặc xử lý nghiệp vụ.

## Mất mạng và an toàn

- Không có kết nối backend thì không mở cửa nghiệp vụ.
- QoS 1 có thể giao lặp; `request_id` và cache chống lặp ngăn servo chạy lại.
- SG90 không có phản hồi vị trí; `unlock_result.success` chỉ xác nhận đã gửi
  thao tác tới PCA9685. Công tắc hành trình mới cung cấp trạng thái cửa.
- Cửa mở quá 3 phút kích hoạt buzzer.
- Production cần MQTT TLS, credential/ACL riêng từng thiết bị và HTTPS.

## Triển khai

Backend cần chạy migration mới nhất trước khi nhận event:

```bash
cd backend
uv run alembic upgrade head
```

Nút “Giả lập đóng cửa” phục vụ kiểm thử không có phần cứng và bị tắt mặc định.
Chỉ bật `ALLOW_DOOR_SIMULATION=true` ở môi trường demo; không bật production.
