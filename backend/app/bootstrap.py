from sqlalchemy import select

from app.core.config import Settings
from app.db import SessionFactory, engine
from app.models import Base, Compartment, LockerStation, User, UserRole
from app.security import hash_password, normalize_phone, verify_password


async def initialize_database(settings: Settings) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with SessionFactory() as session:
        station = await session.scalar(
            select(LockerStation).where(LockerStation.device_id == "SB-001")
        )
        if station is None:
            station = LockerStation(
                device_id="SB-001", name="SmartBox Demo", address=""
            )
            session.add(station)
            await session.flush()
            sizes = ["S", "S", "M", "S", "TECH"]
            for number, size in enumerate(sizes):
                session.add(
                    Compartment(station_id=station.id, number=number, size=size)
                )
        else:
            sizes = ["S", "S", "M", "S", "TECH"]
            compartments = list(
                (
                    await session.scalars(
                        select(Compartment)
                        .where(Compartment.station_id == station.id)
                        .order_by(Compartment.number)
                    )
                ).all()
            )
            for compartment in compartments:
                if 0 <= compartment.number < len(sizes):
                    compartment.size = sizes[compartment.number]

        phone = normalize_phone(settings.bootstrap_admin_phone)
        admin = await session.scalar(select(User).where(User.phone == phone))
        if admin is None:
            session.add(
                User(
                    phone=phone,
                    name="SmartBox Admin",
                    password_hash=hash_password(settings.bootstrap_admin_password),
                    role=UserRole.ADMIN.value,
                )
            )
        else:
            admin.role = UserRole.ADMIN.value
            admin.is_active = True
            if not verify_password(
                settings.bootstrap_admin_password, admin.password_hash
            ):
                admin.password_hash = hash_password(
                    settings.bootstrap_admin_password
                )
        await session.commit()
