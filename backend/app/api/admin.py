import json
import secrets
from datetime import UTC, datetime, time, timedelta, timezone, tzinfo
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select

from app.dependencies import SessionDep, require_roles
from app.models import (
    AuditLog,
    CommandPurpose,
    Compartment,
    CompartmentStatus,
    LockerStation,
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
    User,
    UserRole,
    utc_now,
)
from app.schemas import (
    AdminDashboardView,
    DailyRevenue,
    RevenueSummary,
    RevenueTransaction,
)
from app.services.commands import publish_unlock
from app.services.common import add_audit, calculate_fee

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
VIETNAM_TZ: tzinfo
try:
    VIETNAM_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
except ZoneInfoNotFoundError:
    VIETNAM_TZ = timezone(timedelta(hours=7))


@router.get("/dashboard", response_model=AdminDashboardView)
async def dashboard(
    session: SessionDep,
    user: AdminUser,
) -> AdminDashboardView:
    del user
    now_local = datetime.now(VIETNAM_TZ)
    today_local = now_local.date()
    today_start = datetime.combine(today_local, time.min, VIETNAM_TZ).astimezone(UTC)
    month_start = datetime(
        now_local.year, now_local.month, 1, tzinfo=VIETNAM_TZ
    ).astimezone(UTC)
    seven_day_start = (today_start - timedelta(days=6)).astimezone(UTC)
    paid_filter = (
        Payment.status == PaymentStatus.PAID.value,
        Payment.paid_at.is_not(None),
    )

    async def revenue_since(start: datetime | None = None) -> int:
        query = select(func.coalesce(func.sum(Payment.amount_vnd), 0)).where(
            *paid_filter
        )
        if start is not None:
            query = query.where(Payment.paid_at >= start)
        return int(await session.scalar(query) or 0)

    paid_transactions = int(
        await session.scalar(select(func.count(Payment.id)).where(*paid_filter)) or 0
    )
    recent_rows = list(
        (
            await session.execute(
                select(Payment, Order.order_code)
                .join(Order, Order.id == Payment.order_id)
                .where(*paid_filter)
                .order_by(Payment.paid_at.desc())
                .limit(20)
            )
        ).all()
    )
    seven_day_payments = list(
        (
            await session.scalars(
                select(Payment).where(
                    *paid_filter,
                    Payment.paid_at >= seven_day_start,
                )
            )
        ).all()
    )
    daily_totals: dict[str, tuple[int, int]] = {}
    for payment in seven_day_payments:
        if payment.paid_at is None:
            continue
        paid_at = payment.paid_at
        if paid_at.tzinfo is None:
            paid_at = paid_at.replace(tzinfo=UTC)
        day_key = paid_at.astimezone(VIETNAM_TZ).date().isoformat()
        amount, count = daily_totals.get(day_key, (0, 0))
        daily_totals[day_key] = (amount + payment.amount_vnd, count + 1)

    daily_revenue: list[DailyRevenue] = []
    for offset in range(6, -1, -1):
        day = today_local - timedelta(days=offset)
        amount, count = daily_totals.get(day.isoformat(), (0, 0))
        daily_revenue.append(
            DailyRevenue(
                date=day.isoformat(),
                amount_vnd=amount,
                transaction_count=count,
            )
        )

    return AdminDashboardView(
        revenue=RevenueSummary(
            today_vnd=await revenue_since(today_start),
            month_vnd=await revenue_since(month_start),
            total_vnd=await revenue_since(),
            paid_transactions=paid_transactions,
        ),
        daily_revenue=daily_revenue,
        recent_transactions=[
            RevenueTransaction(
                id=payment.id,
                order_code=order_code,
                provider=payment.provider,
                amount_vnd=payment.amount_vnd,
                paid_at=payment.paid_at,
            )
            for payment, order_code in recent_rows
            if payment.paid_at is not None
        ],
    )


@router.get("/audit-logs")
async def audit_logs(
    session: SessionDep,
    user: AdminUser,
) -> list[dict[str, object]]:
    del user
    logs = list(
        (
            await session.scalars(
                select(AuditLog).order_by(AuditLog.created_at.desc()).limit(200)
            )
        ).all()
    )
    return [
        {
            "id": item.id,
            "actor_id": item.actor_id,
            "action": item.action,
            "entity_type": item.entity_type,
            "entity_id": item.entity_id,
            "detail": json.loads(item.detail_json),
            "created_at": item.created_at,
        }
        for item in logs
    ]


@router.post("/orders/{order_id}/resolve-overdue")
async def resolve_overdue(
    order_id: str,
    request: Request,
    session: SessionDep,
    user: AdminUser,
) -> dict[str, object]:
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order_not_found")
    if order.status not in (OrderStatus.OVERDUE.value, OrderStatus.STORED.value):
        raise HTTPException(status_code=400, detail="order_not_overdue_or_stored")

    compartment = await session.get(Compartment, order.compartment_id)
    if compartment is None:
        raise HTTPException(status_code=404, detail="compartment_not_found")
    station = await session.get(LockerStation, compartment.station_id)
    if station is None:
        raise HTTPException(status_code=404, detail="station_not_found")

    surcharge = max(0, calculate_fee(order) - order.base_fee_vnd) if order.stored_at is not None else 0
    if surcharge == 0 and order.status == OrderStatus.OVERDUE.value:
        surcharge = order.unit_fee_vnd or 2000
    fee = surcharge

    now = utc_now()
    if fee > 0:
        payment = Payment(
            order_id=order.id,
            payos_order_code=1_000_000_000 + secrets.randbelow(1_000_000_000),
            amount_vnd=fee,
            status=PaymentStatus.PAID.value,
            provider="admin_cash",
            reference=f"OVERDUE-{order.order_code}",
            paid_at=now,
        )
        session.add(payment)

    order.status = OrderStatus.COMPLETED.value
    order.completed_at = now
    compartment.status = CompartmentStatus.AVAILABLE.value

    await add_audit(
        session,
        action="ADMIN_RESOLVE_OVERDUE",
        entity_type="order",
        entity_id=order.id,
        detail={
            "admin_id": user.id,
            "order_code": order.order_code,
            "box": compartment.number,
            "surcharge_vnd": fee,
        },
    )
    await session.commit()

    try:
        await publish_unlock(
            session,
            request.app.state.mqtt,
            device_id=station.device_id,
            box=compartment.number,
            purpose=CommandPurpose.ADMIN,
            order_id=order.id,
            actor_id=user.id,
            reason="admin_resolve_overdue",
        )
    except RuntimeError:
        # The cash settlement is still recorded if the physical locker is offline.
        pass

    return {
        "success": True,
        "fee_vnd": fee,
        "message": f"Đã thanh toán phụ phí {fee:,}đ, mở chốt ngăn {compartment.number + 1} và giải phóng ngăn tủ thành công.",
    }
