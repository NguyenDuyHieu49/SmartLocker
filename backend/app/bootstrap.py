from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Connection

from app.core.config import Settings
from app.db import SessionFactory, engine
from app.models import Base, Compartment, LockerStation, User, UserRole
from app.security import hash_password, normalize_phone, verify_password


def _get_table_column_names(connection: Connection, table_name: str) -> set[str]:
    return {
        str(column["name"])
        for column in inspect(connection).get_columns(table_name)
    }


async def initialize_database(settings: Settings) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

        # Tự động migrate thêm cột nếu DB SQLite đã tồn tại từ phiên bản cũ
        columns_to_add = [
            ("dimensions", "VARCHAR(32) DEFAULT '10x10x10'"),
            ("base_price", "INTEGER DEFAULT 5000"),
            ("overdue_price_per_day", "INTEGER DEFAULT 2000"),
            ("max_overdue_days", "INTEGER DEFAULT 3"),
        ]
        existing_cols = await connection.run_sync(
            _get_table_column_names, "compartments"
        )
        for col_name, col_def in columns_to_add:
            if col_name not in existing_cols:
                await connection.execute(
                    text(f"ALTER TABLE compartments ADD COLUMN {col_name} {col_def}")
                )
        if "tier1_price" in existing_cols:
            await connection.execute(
                text(
                    "UPDATE compartments SET base_price = tier1_price WHERE base_price IS NULL OR base_price = 5000"
                )
            )
        if "tier3_price_per_day" in existing_cols:
            await connection.execute(
                text(
                    "UPDATE compartments SET overdue_price_per_day = tier3_price_per_day WHERE overdue_price_per_day IS NULL OR overdue_price_per_day = 2000"
                )
            )


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
            box_defaults = [
                ("S", "10x10x10"),
                ("S", "10x10x10"),
                ("M", "20x10x10"),
                ("L", "30x10x10"),
                ("TECH", "40x40x40"),
            ]
            for number, (size, dims) in enumerate(box_defaults):
                session.add(
                    Compartment(
                        station_id=station.id,
                        number=number,
                        size=size,
                        dimensions=dims,
                    )
                )
        else:
            box_defaults = [
                ("S", "10x10x10"),
                ("S", "10x10x10"),
                ("M", "20x10x10"),
                ("L", "30x10x10"),
                ("TECH", "40x40x40"),
            ]
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
                if 0 <= compartment.number < len(box_defaults):
                    compartment.size = box_defaults[compartment.number][0]
                    if not compartment.dimensions:
                        compartment.dimensions = box_defaults[compartment.number][1]

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
