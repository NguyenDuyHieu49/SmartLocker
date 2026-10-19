import json
import math
from datetime import UTC, datetime
from typing import overload

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Compartment, LockerStation, Order
from app.schemas import OrderView
from app.security import derive_numeric_code


@overload
def as_utc(value: datetime) -> datetime: ...


@overload
def as_utc(value: None) -> None: ...


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def calculate_fee(order: Order, now: datetime | None = None) -> int:
    if order.stored_at is None:
        return order.base_fee_vnd
    now = now or datetime.now(UTC)
    stored_at = as_utc(order.stored_at)
    assert stored_at is not None
    stored_minutes = max(0, int((now - stored_at).total_seconds() // 60))
    billable = max(0, stored_minutes - order.grace_minutes)
    units = math.ceil(billable / order.billing_unit_minutes) if billable else 0
    return order.base_fee_vnd + units * order.unit_fee_vnd


async def order_view(
    session: AsyncSession,
    order: Order,
    *,
    deposit_code: str | None = None,
    reveal_pickup_otp: bool = False,
) -> OrderView:
    compartment = await session.get(Compartment, order.compartment_id)
    if compartment is None:
        raise RuntimeError("compartment_not_found")
    station = await session.get(LockerStation, compartment.station_id)
    if station is None:
        raise RuntimeError("station_not_found")
    return OrderView(
        id=order.id,
        order_code=order.order_code,
        status=order.status,
        recipient_phone=order.recipient_phone,
        recipient_name=order.recipient_name,
        box=compartment.number,
        station_device_id=station.device_id,
        stored_at=as_utc(order.stored_at),
        paid_at=as_utc(order.paid_at),
        completed_at=as_utc(order.completed_at),
        # The receiver pays the complete storage fee at pickup.  This is the
        # base fee plus any extra started billing periods, not only a surcharge.
        fee_vnd=calculate_fee(order),
        daily_rate_vnd=order.unit_fee_vnd,
        deposit_code=deposit_code,
        pickup_otp=(
            derive_numeric_code(order.order_code, "pickup", length=8)
            if reveal_pickup_otp
            and order.status
            in {"STORED", "PAYMENT_PENDING", "PAID", "PICKUP_AUTHORIZED", "PICKUP_OPEN"}
            else None
        ),
    )


async def add_audit(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    actor_id: str | None = None,
    detail: dict[str, object] | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
        )
    )


async def find_station_and_box(
    session: AsyncSession, device_id: str, box: int
) -> tuple[LockerStation, Compartment]:
    station = await session.scalar(
        select(LockerStation).where(LockerStation.device_id == device_id)
    )
    if station is None:
        raise ValueError("station_not_found")
    compartment = await session.scalar(
        select(Compartment).where(
            Compartment.station_id == station.id, Compartment.number == box
        )
    )
    if compartment is None:
        raise ValueError("compartment_not_found")
    return station, compartment
