import asyncio
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Compartment,
    CompartmentStatus,
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
)
from app.payments import PaymentGateway
from app.services.common import add_audit, calculate_fee


async def create_or_get_payment(
    session: AsyncSession,
    gateway: PaymentGateway,
    order: Order,
    *,
    actor_id: str | None,
    amount_vnd: int | None = None,
) -> tuple[Payment, str]:
    amount = amount_vnd if amount_vnd is not None else calculate_fee(order)
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


async def cancel_order_payment(
    session: AsyncSession,
    order: Order,
    *,
    reason: str = "user_cancelled",
    actor_id: str | None = None,
) -> bool:
    payments = list(
        (
            await session.scalars(
                select(Payment).where(
                    Payment.order_id == order.id,
                    Payment.status == PaymentStatus.PENDING.value,
                )
            )
        ).all()
    )
    for p in payments:
        p.status = PaymentStatus.CANCELLED.value

    if order.status in (OrderStatus.RESERVED.value, OrderStatus.PAYMENT_PENDING.value):
        if order.stored_at is None:
            order.status = OrderStatus.CANCELLED.value
            from app.models import Compartment, CompartmentStatus
            compartment = await session.get(Compartment, order.compartment_id)
            if compartment and compartment.status == CompartmentStatus.RESERVED.value:
                compartment.status = CompartmentStatus.AVAILABLE.value
        else:
            order.status = OrderStatus.STORED.value

    await add_audit(
        session,
        action="PAYMENT_CANCELLED",
        entity_type="order",
        entity_id=order.id,
        actor_id=actor_id,
        detail={"reason": reason, "order_code": order.order_code},
    )
    await session.commit()
    return True


async def cancel_expired_pending_payments(
    session: AsyncSession, max_age_minutes: int = 15
) -> int:
    cutoff = datetime.now(UTC) - timedelta(minutes=max_age_minutes)
    expired_payments = list(
        (
            await session.scalars(
                select(Payment).where(
                    Payment.status == PaymentStatus.PENDING.value,
                    Payment.created_at <= cutoff,
                )
            )
        ).all()
    )
    from app.models import Compartment, CompartmentStatus
    processed_orders: set[str] = set()
    count = 0

    for payment in expired_payments:
        payment.status = PaymentStatus.CANCELLED.value
        order = await session.get(Order, payment.order_id)
        if order and order.id not in processed_orders:
            processed_orders.add(order.id)
            if order.status in (OrderStatus.RESERVED.value, OrderStatus.PAYMENT_PENDING.value):
                if order.stored_at is None:
                    order.status = OrderStatus.CANCELLED.value
                    compartment = await session.get(Compartment, order.compartment_id)
                    if compartment and compartment.status == CompartmentStatus.RESERVED.value:
                        compartment.status = CompartmentStatus.AVAILABLE.value
                else:
                    order.status = OrderStatus.STORED.value
            await add_audit(
                session,
                action="PAYMENT_EXPIRED",
                entity_type="order",
                entity_id=order.id,
                detail={"reason": f"{max_age_minutes}m_timeout", "order_code": order.order_code},
            )
            count += 1

    expired_orders = list(
        (
            await session.scalars(
                select(Order).where(
                    Order.status.in_([OrderStatus.RESERVED.value, OrderStatus.PAYMENT_PENDING.value]),
                    Order.stored_at.is_(None),
                    Order.created_at <= cutoff,
                )
            )
        ).all()
    )
    for order in expired_orders:
        if order.id not in processed_orders:
            processed_orders.add(order.id)
            order.status = OrderStatus.CANCELLED.value
            compartment = await session.get(Compartment, order.compartment_id)
            if compartment and compartment.status == CompartmentStatus.RESERVED.value:
                compartment.status = CompartmentStatus.AVAILABLE.value
            await add_audit(
                session,
                action="ORDER_EXPIRED",
                entity_type="order",
                entity_id=order.id,
                detail={"reason": f"{max_age_minutes}m_timeout", "order_code": order.order_code},
            )
            count += 1

    if count > 0 or expired_payments:
        await session.commit()
    return count


async def mark_overdue_orders(session: AsyncSession) -> int:
    """Find STORED orders where stored_at + grace_minutes + max_overdue_days has passed,
    and update their status to OVERDUE."""
    now = datetime.now(UTC)
    stored_orders = list(
        (
            await session.scalars(
                select(Order).where(Order.status == OrderStatus.STORED.value)
            )
        ).all()
    )
    overdue_count = 0
    for order in stored_orders:
        if order.stored_at is None:
            continue
        compartment = await session.get(Compartment, order.compartment_id)
        if compartment is None:
            continue
        stored_at = order.stored_at
        if stored_at.tzinfo is None:
            stored_at = stored_at.replace(tzinfo=UTC)
        total_allowed_minutes = order.grace_minutes + (
            compartment.max_overdue_days * 24 * 60
        )
        deadline = stored_at + timedelta(minutes=total_allowed_minutes)
        if now >= deadline:
            order.status = OrderStatus.OVERDUE.value
            await add_audit(
                session,
                action="ORDER_OVERDUE",
                entity_type="order",
                entity_id=order.id,
                detail={
                    "order_code": order.order_code,
                    "stored_at": stored_at.isoformat(),
                    "grace_minutes": order.grace_minutes,
                    "max_overdue_days": compartment.max_overdue_days,
                },
            )
            overdue_count += 1
    if overdue_count > 0:
        await session.commit()
    return overdue_count


