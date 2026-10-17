# Triển khai `smartbox.id.vn`

## Sơ đồ tên miền

- `smartbox.id.vn`: dashboard tĩnh trên Vercel.
- `app.smartbox.id.vn`: alias tùy chọn của dashboard.
- `api.smartbox.id.vn`: FastAPI trên Render Free trong Phase 1.
- `mqtt.smartbox.id.vn`: broker MQTT có TLS, username/password và ACL.

Các subdomain không phải mua thêm. Chỉ tạo bản ghi DNS trong Mắt Bão.

## Thứ tự triển khai

1. Tạo PostgreSQL Neon và lấy connection string SSL.
2. Tạo EMQX Serverless. Tạo riêng tài khoản cho backend và
   `SB-001`; giới hạn ACL trong `smartbox/SB-001/#`.
3. Deploy thư mục `backend/`, khai báo biến môi trường và gắn
   `api.smartbox.id.vn`.
4. Khai báo IPN MoMo Sandbox:
   `https://api.smartbox.id.vn/api/v1/webhooks/momo`.
5. Deploy thư mục `dashboard/` và gắn `smartbox.id.vn`.
6. Sau khi Vercel/backend/broker cung cấp target, tạo bản ghi DNS tại
   Mắt Bão. Không đoán target trước khi dịch vụ được tạo.
7. Cập nhật `NetworkConfig.h`, nạp ESP32 và kiểm thử một ngăn.

## Biến backend production bắt buộc

Sao chép `backend/.env.example` và đặt các giá trị sau trong kho
secret của nhà cung cấp, không nhập vào mã nguồn:

- `ENVIRONMENT=production`
- `DATABASE_URL`
- `JWT_SECRET` và `OTP_PEPPER`: hai chuỗi ngẫu nhiên khác nhau, tối thiểu 32 ký tự.
- `BOOTSTRAP_ADMIN_PHONE` và mật khẩu admin mạnh.
- `DEMO_MODE=false`
- `PAYMENT_PROVIDER=momo_sandbox` và ba khóa MoMo Sandbox.
- `MQTT_HOST`, `MQTT_PORT=8883`, username/password.
- `MQTT_TLS=true`, `MQTT_TLS_INSECURE=false`.
- `DASHBOARD_URL=https://smartbox.id.vn`
- `API_URL=https://api.smartbox.id.vn`
- `CORS_ORIGINS=https://smartbox.id.vn,https://app.smartbox.id.vn`

Backend từ chối khởi động production nếu demo, secret mặc định,
cổng thanh toán hoặc xác minh TLS chưa được cấu hình.

## DNS

Giá trị chính xác sẽ được điền sau khi tạo dịch vụ:

- `@`: A hoặc CNAME theo chỉ dẫn Vercel.
- `app`: CNAME theo chỉ dẫn Vercel (tùy chọn).
- `api`: CNAME theo chỉ dẫn Render.
- `mqtt`: CNAME theo chỉ dẫn broker nếu nhà cung cấp cho phép custom domain.

Không xóa MX/TXT hiện có nếu tên miền đang dùng email.

## Kiểm thử nghiệm thu

1. `/health` trả `200` qua HTTPS.
2. Đăng ký shipper và customer bằng hai số test.
3. Tạo đơn, gửi hàng, mở/đóng cửa và kiểm tra trạng thái `STORED`.
4. Quét QR bằng MoMo Test và hoàn tất giao dịch sandbox.
5. Kiểm tra webhook không bị ghi nhận hai lần.
6. Nhập sai OTP 5 lần phải bị khóa; OTP đúng chỉ mở đúng ngăn.
7. Ngắt Wi-Fi, khởi động lại và khôi phục kết nối.
8. Mất backend/broker không được tự mở ngăn.
