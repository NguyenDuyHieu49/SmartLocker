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
from app.services.commands import publish_unlock
from app.services.common import add_audit
from app.services.payment_service import mark_payment_paid

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


async def _process_payment_webhook(
    provider: str, request: Request, session: SessionDep
) -> dict[str, object]:
    payload = await request.body()
    gateway = cast(PaymentGateway, request.app.state.payment_gateway)
    if gateway.name != provider:
        raise HTTPException(status_code=404, detail="payment_provider_not_active")
    try:
        verified = await asyncio.to_thread(gateway.verify_webhook, payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_webhook") from exc

    payment = await session.scalar(
        select(Payment).where(Payment.payos_order_code == verified.order_code)
    )
    if payment is None:
        # payOS sends a correctly signed sample transaction when validating a
        # webhook URL. It deliberately has no matching local payment, but the
        # endpoint must still return 2xx for payOS to finish registration.
        return {
            "success": True,
            "ignored": True,
            "reason": "payment_not_found",
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
        return {"success": True, "duplicate": True}
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
        return {"success": True, "duplicate": True}
    compartment = await session.get(Compartment, order.compartment_id)
    station = (
        await session.get(LockerStation, compartment.station_id)
        if compartment
        else None
    )
    if station is not None and compartment is not None:
        mqtt = cast(MqttService, request.app.state.mqtt)
        purpose = (
            CommandPurpose.DEPOSIT if is_deposit_payment else CommandPurpose.PICKUP
        )
        try:
            if is_deposit_payment:
                mqtt.show_ui(
                    station.device_id,
                    {
                        "screen": "result",
                        "otp": derive_numeric_code(
                            order.order_code, "pickup", length=8
                        ),
                        "box": compartment.number,
                        "auto_open": True,
                    },
                )
            else:
                mqtt.show_ui(
                    station.device_id,
                    {
                        "screen": "opening",
                        "mode": "pickup",
                        "box": compartment.number,
                    },
                )
        except RuntimeError:
            pass
        try:
            await publish_unlock(
                session,
                mqtt,
                device_id=station.device_id,
                box=compartment.number,
                purpose=purpose,
                order_id=order.id,
                actor_id=None,
                reason="payment_confirmed_auto_unlock",
            )
        except RuntimeError as exc:
            await add_audit(
                session,
                action="AUTO_UNLOCK_FAILED",
                entity_type="order",
                entity_id=order.id,
                detail={
                    "device_id": station.device_id,
                    "box": compartment.number,
                    "purpose": purpose.value,
                    "error": str(exc),
                },
            )
            await session.commit()
            try:
                mqtt.show_ui(
                    station.device_id,
                    {
                        "screen": "alert",
                        "title": "DA NHAN THANH TOAN",
                        "message": "Tu mat ket noi - lien he ho tro",
                    },
                )
            except RuntimeError:
                pass
    return {"success": True, "duplicate": False}


@router.post("/payos")
async def payos_webhook(request: Request, session: SessionDep) -> dict[str, object]:
    return await _process_payment_webhook("payos", request, session)


@router.post("/momo")
async def momo_webhook(request: Request, session: SessionDep) -> dict[str, object]:
    result = await _process_payment_webhook("momo_sandbox", request, session)
    return {"resultCode": 0, "message": "Successful.", **result}
