import asyncio
import json
from typing import cast

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.dependencies import SessionDep
from app.models import (
    CommandPurpose,
    Compartment,
    LockerStation,
    Order,
    Payment,
    WebhookEvent,
)
from app.mqtt.service import MqttService
from app.payments import PaymentGateway
from app.security import derive_numeric_code
from app.services.common import add_audit
from app.services.payment_service import mark_payment_paid

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


async def _process_payment_webhook(
    provider: str, request: Request, session: SessionDep
) -> dict[str, object]:
    payload = await request.body()
    body_str = payload.decode("utf-8", errors="replace")
    print(
        f"\n==================== [PAYOS WEBHOOK RECEIVED] ====================\n"
        f"Provider: {provider} | Length: {len(payload)} bytes\n"
        f"Payload: {body_str}\n"
        f"==================================================================\n",
        flush=True,
    )

    # Kiểm tra nếu PayOS gửi request probe xác thực Webhook URL
    try:
        raw_json = json.loads(payload)
        if isinstance(raw_json, dict) and "webhookUrl" in raw_json and "signature" not in raw_json:
            print("[PAYOS WEBHOOK] -> Nhận probe xác thực Webhook URL từ PayOS, phản hồi 200 OK", flush=True)
            return {"error": 0, "message": "Ok", "success": True, "data": None}
    except Exception:
        pass

    gateway = cast(PaymentGateway, request.app.state.payment_gateway)
    if gateway.name != provider:
        raise HTTPException(status_code=404, detail="payment_provider_not_active")

    try:
        verified = await asyncio.to_thread(gateway.verify_webhook, payload)
    except Exception as exc:
        print(f"[PAYOS WEBHOOK ERROR] -> Xác thực chữ ký thất bại: {exc}", flush=True)
        # Nếu PayOS gửi giao dịch mẫu (orderCode 123) để test kết nối webhook
        try:
            raw_json = json.loads(payload)
            if isinstance(raw_json, dict) and raw_json.get("data", {}).get("orderCode") == 123:
                print("[PAYOS WEBHOOK] -> Dữ liệu mẫu test webhook (orderCode 123), trả về 200 OK cho PayOS", flush=True)
                return {"error": 0, "message": "Ok", "success": True, "data": None}
        except Exception:
            pass
        raise HTTPException(status_code=400, detail="invalid_webhook") from exc

    print(
        f"[PAYOS WEBHOOK] -> Xác thực thành công: OrderCode={verified.order_code}, Amount={verified.amount:,}đ, Ref={verified.reference}",
        flush=True,
    )

    payment = await session.scalar(
        select(Payment).where(Payment.payos_order_code == verified.order_code)
    )
    if payment is None:
        # payOS sends a correctly signed sample transaction when validating a
        # webhook URL. It deliberately has no matching local payment, but the
        # endpoint must still return 2xx for payOS to finish registration.
        print(f"[PAYOS WEBHOOK] -> Không tìm thấy đơn {verified.order_code} trong DB (giao dịch mẫu PayOS), trả về 200 OK")
        return {
            "error": 0,
            "message": "Ok",
            "success": True,
            "ignored": True,
            "reason": "payment_not_found",
            "data": None,
        }
    if payment.amount_vnd != verified.amount:
        raise HTTPException(status_code=409, detail="payment_amount_mismatch")
    order = await session.get(Order, payment.order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order_not_found")

    event_key = f"{verified.order_code}:{verified.reference}"
    existing = await session.scalar(
        select(WebhookEvent).where(WebhookEvent.event_key == event_key)
    )
    if existing:
        return {"error": 0, "message": "Ok", "success": True, "duplicate": True, "data": None}
    session.add(
        WebhookEvent(
            event_key=event_key,
            provider=provider,
            payos_order_code=verified.order_code,
            payload_json=json.dumps(json.loads(payload), ensure_ascii=False),
        )
    )
    await session.flush()
    is_deposit_payment = order.stored_at is None
    newly_paid = await mark_payment_paid(
        session, payment, order, reference=verified.reference
    )
    if not newly_paid:
        # A provider can retry a successful payment with a different reference.
        # Persist the event for traceability, but never open the same door twice.
        await session.commit()
        return {"error": 0, "message": "Ok", "success": True, "duplicate": True, "data": None}
    compartment = await session.get(Compartment, order.compartment_id)
    station = (
        await session.get(LockerStation, compartment.station_id)
        if compartment
        else None
    )
    if station is not None and compartment is not None:
        mqtt = cast(MqttService, request.app.state.mqtt)
        if is_deposit_payment:
            try:
                mqtt.show_ui(
                    station.device_id,
                    {
                        "screen": "result",
                        "otp": derive_numeric_code(
                            order.order_code, "pickup", length=8
                        ),
                        "box": compartment.number,
                    },
                )
            except RuntimeError:
                pass
            print(
                f"[PAYOS WEBHOOK] -> Đã gửi kết quả OTP về ESP32 (Ngăn #{compartment.number + 1}). "
                f"Khách đọc xong hướng dẫn nhấn [A] thì ESP32 mới tự mở tủ vật lý.",
                flush=True,
            )
        else:
            try:
                mqtt.show_ui(
                    station.device_id,
                    {
                        "screen": "door_guide",
                        "mode": "pickup",
                        "box": compartment.number,
                    },
                )
            except RuntimeError:
                pass
            print(
                f"[PAYOS WEBHOOK] -> Đã chuyển sang màn hình hướng dẫn nhận đồ cho ESP32 (Ngăn #{compartment.number + 1}). "
                f"Khách bấm [A] ở hướng dẫn cuối thì ESP32 mới mở tủ.",
                flush=True,
            )
    return {"error": 0, "message": "Ok", "success": True, "duplicate": False, "data": None}


@router.get("/payos")
async def payos_webhook_health() -> dict[str, str]:
    return {"status": "ok", "message": "PayOS webhook endpoint is active"}


@router.post("/payos")
async def payos_webhook(request: Request, session: SessionDep) -> dict[str, object]:
    return await _process_payment_webhook("payos", request, session)


@router.post("/momo")
async def momo_webhook(request: Request, session: SessionDep) -> dict[str, object]:
    result = await _process_payment_webhook("momo_sandbox", request, session)
    return {"resultCode": 0, "message": "Successful.", **result}
