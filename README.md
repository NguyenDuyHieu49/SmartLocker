# SmartBox Phase 1

Tủ gửi đồ dùng ESP32-S3 gồm bốn ngăn cho thuê (`0..3`) và một ngăn kỹ thuật
(`4`). Backend là nguồn sự thật cho đơn hàng, thanh toán và trạng thái ngăn;
ESP32 xử lý keypad, TFT, servo và công tắc cửa qua MQTT.

## Thành phần

- `firmware/`: PlatformIO/Arduino, PCA9685, servo, công tắc, keypad và TFT.
- `backend/`: FastAPI, PostgreSQL/SQLite, MQTT, OTP 8 số và payOS.
- `dashboard/`: Nuxt SPA cho khách hàng, shipper và admin.
- `PHASE1_ARCHITECTURE.md`: kiến trúc đã đồng bộ với MQTT specification.
- `DEPLOYMENT_SMARTBOX_ID_VN.md`: checklist triển khai tên miền thật.

## Luồng nghiệp vụ

1. Tại tủ, shipper chọn cỡ S/M và nhập số điện thoại người nhận.
2. Backend cấp một ngăn thuê phù hợp, tạo đơn, OTP 8 số và QR phí gửi.
3. Webhook thanh toán hợp lệ tự động gửi lệnh mở đúng ngăn; người dùng không
   cần nhấn thêm nút mở.
4. Sau khi đặt hàng và đóng cửa, shipper nhấn `A`; backend mới chuyển đơn sang
   `STORED` và ngăn sang `OCCUPIED`.
5. Người nhận nhập OTP. Nếu chưa quá hạn, hệ thống cho xác nhận mở; nếu quá
   hạn, hệ thống yêu cầu thanh toán phụ phí rồi tự động mở sau webhook.
6. Sau khi lấy hàng và đóng cửa, người nhận nhấn `A`; backend chuyển đơn sang
   `COMPLETED` và trả ngăn về `AVAILABLE`.

Ngăn số 4 không được cấp cho đơn hàng. Việc cửa đóng/mở chỉ là trạng thái vật
lý và không tự thay đổi trạng thái nghiệp vụ nếu thiếu `confirm_finish`.

## Bảng giá lưu trữ

- Ngăn 1 và 2: 5.000đ cho mỗi chu kỳ 24 giờ bắt đầu.
- Ngăn 3: 7.000đ cho mỗi chu kỳ 24 giờ bắt đầu.
- Ngăn 4: 10.000đ cho mỗi chu kỳ 24 giờ bắt đầu.
- Ngăn 5 là ngăn kỹ thuật và không được cho thuê.

Ngày đầu được thanh toán khi gửi hàng. Khi vượt quá 24 giờ, hệ thống tính phụ
phí theo từng chu kỳ 24 giờ bắt đầu tiếp theo. Giá được lưu vào đơn lúc tạo nên
việc đổi bảng giá sau này không làm thay đổi các đơn đã tồn tại.

## Chạy local

```bash
cd infrastructure && docker compose up -d
cd ../backend && cp .env.example .env
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
cd ../dashboard && cp .env.example .env
npm install && npm run dev
```

```bash
cd firmware
~/.platformio/penv/bin/pio run
```

Không commit `.env`, không mở broker anonymous ra Internet và không bật
`MQTT_TLS_INSECURE` trong production. Nút giả lập đóng cửa trên dashboard chỉ
hoạt động khi backend đặt `ALLOW_DOOR_SIMULATION=true`.
