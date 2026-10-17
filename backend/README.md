# SmartBox Backend Phase 1

FastAPI API cho tài khoản, đơn hàng, tính phí, MoMo Sandbox/payOS, OTP, vận hành
tủ và cầu nối MQTT với ESP32-S3.

## Chạy local

Từ thư mục `SmartLocker/backend`:

```bash
cp .env.example .env
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Swagger UI: `http://127.0.0.1:8000/docs`.

## Nhóm API

```text
GET  /health
POST /api/v1/auth/register
POST /api/v1/auth/login
GET  /api/v1/orders
POST /api/v1/orders
POST /api/v1/orders/{order_code}/payments
POST /api/v1/orders/{order_code}/pickup
POST /api/v1/webhooks/momo
POST /api/v1/webhooks/payos
GET  /api/v1/lockers/{device_id}/status
POST /api/v1/lockers/{device_id}/manual-unlock
GET  /api/v1/admin/audit-logs
```

Swagger tại `/docs` liệt kê cả endpoint thiết bị mức thấp dùng khi
chạy thử. Các endpoint nghiệp vụ kiểm tra JWT và vai trò.

## Kiểm thử

```bash
uv run pytest
uv run ruff check .
uv run mypy app
```

Container production tự chạy migration trước khi khởi động API. Xem
`../DEPLOYMENT_SMARTBOX_ID_VN.md` trước khi khai báo secret.

Chọn cổng thanh toán bằng `PAYMENT_PROVIDER=mock|momo_sandbox|payos`.
Phase 1 cloud dùng `momo_sandbox`; trạng thái `PAID` chỉ được ghi sau khi
IPN có HMAC-SHA256 hợp lệ.

