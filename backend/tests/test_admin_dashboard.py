from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.admin import dashboard as admin_dashboard
from app.models import (
    Base,
    Compartment,
    LockerStation,
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
    User,
    UserRole,
)


@pytest.mark.asyncio
async def test_admin_revenue_counts_only_paid_payments() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        admin = User(
            phone="0900000000",
            name="Admin",
            password_hash="unused",
            role=UserRole.ADMIN.value,
        )
        station = LockerStation(device_id="SB-001", name="Test station")
        session.add_all([admin, station])
        await session.flush()
        compartment = Compartment(station_id=station.id, number=0, size="S")
        session.add(compartment)
        await session.flush()
        order = Order(
            order_code="12345678",
            shipper_id=None,
            recipient_phone="0912345678",
            recipient_name="Recipient",
            compartment_id=compartment.id,
            status=OrderStatus.PAID.value,
            deposit_code_digest="deposit-digest",
            pickup_otp_digest="pickup-digest",
            base_fee_vnd=5_000,
            grace_minutes=60,
            billing_unit_minutes=60,
            unit_fee_vnd=2_000,
        )
        session.add(order)
        await session.flush()
        now = datetime.now(UTC)
        session.add_all(
            [
                Payment(
                    order_id=order.id,
                    provider="payos",
                    payos_order_code=1_000_000_001,
                    amount_vnd=5_000,
                    status=PaymentStatus.PAID.value,
                    paid_at=now,
                ),
                Payment(
                    order_id=order.id,
                    provider="payos",
                    payos_order_code=1_000_000_002,
                    amount_vnd=2_000,
                    status=PaymentStatus.PENDING.value,
                ),
            ]
        )
        await session.commit()

        result = await admin_dashboard(session, admin)

        assert result.revenue.today_vnd == 5_000
        assert result.revenue.month_vnd == 5_000
        assert result.revenue.total_vnd == 5_000
        assert result.revenue.paid_transactions == 1
        assert len(result.recent_transactions) == 1
        assert result.recent_transactions[0].paid_at.tzinfo is not None
        assert result.recent_transactions[0].paid_at.utcoffset() is not None
        assert sum(day.amount_vnd for day in result.daily_revenue) == 5_000

    await engine.dispose()
