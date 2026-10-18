# SmartBox Phase 1

Hệ thống tủ gửi đồ 5 ngăn cho shipper và người nhận, dùng ESP32-S3,
PCA9685, 5 servo SG90, 5 công tắc hành trình, keypad 4x4, TFT
ST7789 240x240, buzzer và RTC DS3231 tùy chọn.

## Thành phần

- `firmware/`: PlatformIO/Arduino cho ESP32-S3, TFT, keypad, servo và MQTT.
- `backend/`: FastAPI, PostgreSQL/SQLite, MQTT, OTP, payOS và nhật ký.
- `dashboard/`: Nuxt SPA cho shipper, người nhận và admin.
- `infrastructure/`: Mosquitto không xác thực chỉ dùng khi phát triển LAN.
- `PHASE1_ARCHITECTURE.md`: kiến trúc và các quyết định kỹ thuật.
- `DEPLOYMENT_SMARTBOX_ID_VN.md`: checklist triển khai tên miền thật.

## Nghiệp vụ đã cài đặt

1. Shipper tạo đơn, hệ thống giữ một ngăn và sinh mã gửi hàng.
2. Shipper nhập mã trên keypad hoặc mở từ dashboard.
3. Công tắc cửa xác nhận kiện hàng đã được cất và bắt đầu tính phí.
4. Người nhận nhập mã đơn; TFT/dashboard hiển thị QR thanh toán payOS.
5. Webhook payOS có chữ ký hợp lệ xác nhận tiền và cho phép nhập OTP.
6. OTP đúng mới mở tủ; đóng cửa kết thúc đơn và trả ngăn về trạng thái trống.

## Chạy local

```bash
cd infrastructure
docker compose up -d

cd ../backend
cp .env.example .env
uv run alembic upgrade head
uv run uvicorn app.main:app --reload

cd ../dashboard
cp .env.example .env
npm install
npm run dev
```

Trước khi nạp firmware, cập nhật GPIO và mạng trong
`firmware/include/config/PinConfig.h` và
`firmware/include/config/NetworkConfig.h`.

```bash
cd firmware
~/.platformio/penv/bin/pio run
```

Không commit `.env`, không public Mosquitto anonymous cổng 1883 và không
dùng `MQTT_TLS_INSECURE` trong production.
