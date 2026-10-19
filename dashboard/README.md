# SmartBox Dashboard

Nuxt SPA tĩnh cho ba vai trò:

- Shipper tạo đơn và mở ngăn gửi hàng.
- Người nhận thanh toán toàn bộ phí lưu trữ; webhook thành công tự mở tủ.
- Admin xem 5 ngăn, mở thủ công và đọc audit log.

## Chạy local

```bash
npm install
cp .env.example .env
npm run dev
```

## Bản production tĩnh

```bash
npm run generate
```

Vercel phục vụ trực tiếp `.output/public`; không chạy Nuxt/Nitro server
trong production. API URL lấy từ `NUXT_PUBLIC_API_BASE_URL` lúc build.
