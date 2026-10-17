import asyncio
import secrets
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order, OrderStatus, Payment, PaymentStatus
from app.payments import PaymentGateway
from app.services.common import add_audit, calculate_fee


async def create_or_get_payment(
    session: AsyncSession,
    gateway: PaymentGateway,
    order: Order,
    *,
    actor_id: str | None,
) -> tuple[Payment, str]:
    amount = calculate_fee(order)
    existing = await session.scalar(
        select(Payment)
        .where(
            Payment.order_id == order.id,
            Payment.amount_vnd == amount,
            Payment.status == PaymentStatus.PENDING.value,
        )
        .order_by(Payment.created_at.desc())
    )
    if existing and existing.checkout_url and existing.qr_code:
        return existing, existing.provider

    payos_order_code = 1_000_000_000 + secrets.randbelow(1_000_000_000)
    payment = Payment(
        order_id=order.id,
        provider=gateway.name,
        payos_order_code=payos_order_code,
        amount_vnd=amount,
        status=PaymentStatus.PENDING.value,
    )
    session.add(payment)
    order.status = OrderStatus.PAYMENT_PENDING.value
    await session.commit()

    try:
        link = await asyncio.to_thread(
            gateway.create_link,
            order_code=payos_order_code,
            amount=amount,
            description=f"SB{order.order_code}"[:9],
            buyer_phone=order.recipient_phone,
        )
    except Exception:
        payment.status = PaymentStatus.FAILED.value
        await session.commit()
        raise

    payment.payment_link_id = link.payment_link_id
    payment.checkout_url = link.checkout_url
    payment.qr_code = link.qr_code
    await add_audit(
        session,
        action="PAYMENT_LINK_CREATED",
        entity_type="payment",
        entity_id=payment.id,
        actor_id=actor_id,
        detail={"provider": link.provider, "amount_vnd": amount},
    )
    await session.commit()
    return payment, link.provider


async def mark_payment_paid(
    session: AsyncSession,
    payment: Payment,
    order: Order,
    *,
    reference: str,
) -> bool:
    if payment.status == PaymentStatus.PAID.value:
        return False
    now = datetime.now(UTC)
    payment.status = PaymentStatus.PAID.value
    payment.reference = reference
    payment.paid_at = now
    order.status = OrderStatus.PAID.value
    order.paid_at = now
    await add_audit(
        session,
        action="PAYMENT_CONFIRMED",
        entity_type="order",
        entity_id=order.id,
        detail={"payment_id": payment.id, "amount_vnd": payment.amount_vnd},
    )
    await session.commit()
    return True
