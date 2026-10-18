from typing import Any, cast

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.orders import create_order
from app.models import (
    AuditLog,
    Base,
    Compartment,
    CompartmentStatus,
    LockerStation,
    User,
    UserRole,
)
from app.schemas import CreateOrderRequest


@pytest.mark.asyncio
async def test_create_order_flushes_id_before_writing_audit() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        shipper = User(
            phone="0912345678",
            name="Test shipper",
            password_hash="unused",
            role=UserRole.SHIPPER.value,
        )
        station = LockerStation(device_id="SB-001", name="Test station")
        session.add_all([shipper, station])
        await session.flush()
        compartment = Compartment(
            station_id=station.id,
            number=0,
            status=CompartmentStatus.AVAILABLE.value,
        )
        session.add(compartment)
        await session.commit()

        created = await create_order(
            CreateOrderRequest(
                recipient_phone="0901234567",
                recipient_name="Test recipient",
                station_device_id="SB-001",
            ),
            cast(Any, object()),
            session,
            shipper,
        )

        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "ORDER_CREATED")
        )
        assert audit is not None
        assert audit.entity_id == created.id
        assert created.status == "RESERVED"

    await engine.dispose()
