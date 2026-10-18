from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(UTC)


def uuid_string() -> str:
    return str(uuid4())


class UserRole(StrEnum):
    SHIPPER = "SHIPPER"
    CUSTOMER = "CUSTOMER"
    ADMIN = "ADMIN"


class OrderStatus(StrEnum):
    RESERVED = "RESERVED"
    DEPOSIT_AUTHORIZED = "DEPOSIT_AUTHORIZED"
    DEPOSIT_OPEN = "DEPOSIT_OPEN"
    STORED = "STORED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAID = "PAID"
    PICKUP_AUTHORIZED = "PICKUP_AUTHORIZED"
    PICKUP_OPEN = "PICKUP_OPEN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class CompartmentStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class PaymentStatus(StrEnum):
    PENDING = "PENDING"
    PAID = "PAID"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class CommandStatus(StrEnum):
    CREATED = "CREATED"
    PUBLISHED = "PUBLISHED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class CommandPurpose(StrEnum):
    DEPOSIT = "DEPOSIT"
    PICKUP = "PICKUP"
    ADMIN = "ADMIN"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class LockerStation(Base):
    __tablename__ = "locker_stations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    device_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class Compartment(Base):
    __tablename__ = "compartments"
    __table_args__ = (UniqueConstraint("station_id", "number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    station_id: Mapped[str] = mapped_column(
        ForeignKey("locker_stations.id"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    size: Mapped[str] = mapped_column(String(8), default="S")
    status: Mapped[str] = mapped_column(String(30), default=CompartmentStatus.AVAILABLE)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    order_code: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    shipper_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True
    )
    recipient_phone: Mapped[str] = mapped_column(String(20), index=True)
    recipient_name: Mapped[str] = mapped_column(String(120))
    compartment_id: Mapped[str] = mapped_column(
        ForeignKey("compartments.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), index=True)
    deposit_code_digest: Mapped[str] = mapped_column(
        String(64), unique=True, index=True
    )
    pickup_otp_digest: Mapped[str] = mapped_column(String(64))
    pickup_otp_attempts: Mapped[int] = mapped_column(Integer, default=0)
    demo_pickup_otp: Mapped[str | None] = mapped_column(String(12), nullable=True)
    stored_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    base_fee_vnd: Mapped[int] = mapped_column(Integer)
    grace_minutes: Mapped[int] = mapped_column(Integer)
    billing_unit_minutes: Mapped[int] = mapped_column(Integer)
    unit_fee_vnd: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    provider: Mapped[str] = mapped_column(String(24), default="mock")
    payos_order_code: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    payment_link_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    amount_vnd: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), index=True)
    checkout_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    qr_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DeviceCommand(Base):
    __tablename__ = "device_commands"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    request_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    box: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(20))
    order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=CommandStatus.CREATED)
    error: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DoorEvent(Base):
    __tablename__ = "door_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    event_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    box: Mapped[int] = mapped_column(Integer)
    door_closed: Mapped[bool] = mapped_column(Boolean)
    device_timestamp: Mapped[int] = mapped_column(Integer)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class WebhookEvent(Base):
    __tablename__ = "payment_webhook_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    event_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(24), default="payos")
    payos_order_code: Mapped[int] = mapped_column(Integer, index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(80))
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
