import json
from datetime import UTC, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.dependencies import SessionDep, require_roles
from app.models import AuditLog, Order, Payment, PaymentStatus, User, UserRole
from app.schemas import (
    AdminDashboardView,
    DailyRevenue,
    RevenueSummary,
    RevenueTransaction,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
VIETNAM_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


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
