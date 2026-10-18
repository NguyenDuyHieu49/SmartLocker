from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.webhooks import _process_payment_webhook
from app.models import (
    Base,
    CommandPurpose,
    Compartment,
    CompartmentStatus,
    DeviceCommand,
    LockerStation,
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
)
from app.payments import VerifiedPayment


class FakeRequest:
    def __init__(self) -> None:
        self.app = SimpleNamespace(
            state=SimpleNamespace(payment_gateway=FakeGateway())
        )

    async def body(self) -> bytes:
        return b'{"signed":"sample"}'


class FakeGateway:
    name = "payos"

    def verify_webhook(self, payload: bytes) -> VerifiedPayment:
        assert payload == b'{"signed":"sample"}'
        return VerifiedPayment(
            order_code=123,
            amount=3_000,
            reference="sample-reference",
            payment_link_id="sample-link",
        )


class FakeSession:
    async def scalar(self, _statement: object) -> None:
        return None


class PaymentGatewayStub:
    name = "payos"

    def __init__(self, order_code: int, amount: int) -> None:
        self.order_code = order_code
        self.amount = amount

    def verify_webhook(self, payload: bytes) -> VerifiedPayment:
        assert payload == b'{"signed":"sample"}'
        return VerifiedPayment(
            order_code=self.order_code,
            amount=self.amount,
            reference="bank-reference",
            payment_link_id="payment-link",
        )


class RecordingMqtt:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, object]] = []

    def show_ui(self, device_id: str, payload: dict[str, object]) -> None:
        self.events.append(("ui", device_id, payload))

    def unlock(self, device_id: str, box: int, *, request_id: str) -> None:
        self.events.append(
            ("unlock", device_id, {"box": box, "request_id": request_id})
        )


class AutoOpenRequest:
    def __init__(self, gateway: PaymentGatewayStub, mqtt: RecordingMqtt) -> None:
        self.app = SimpleNamespace(
            state=SimpleNamespace(payment_gateway=gateway, mqtt=mqtt)
        )

    async def body(self) -> bytes:
        return b'{"signed":"sample"}'


@pytest.mark.asyncio
async def test_payos_validation_sample_is_acknowledged() -> None:
    result = await _process_payment_webhook(
        "payos",
        cast(Any, FakeRequest()),
        cast(Any, FakeSession()),
    )

    assert result == {
        "success": True,
        "ignored": True,
        "reason": "payment_not_found",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored", "expected_purpose", "expected_screen"),
    [
        (False, CommandPurpose.DEPOSIT, "result"),
        (True, CommandPurpose.PICKUP, "opening"),
    ],
)
async def test_paid_webhook_automatically_unlocks_compartment(
    stored: bool,
    expected_purpose: CommandPurpose,
    expected_screen: str,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        station = LockerStation(device_id="SB-001", name="Test station")
        session.add(station)
        await session.flush()
        compartment = Compartment(
            station_id=station.id,
            number=2,
            status=CompartmentStatus.OCCUPIED.value
            if stored
            else CompartmentStatus.RESERVED.value,
        )
        session.add(compartment)
        await session.flush()
        order = Order(
            order_code="SB00000001",
            shipper_id=None,
            recipient_phone="0901234567",
            recipient_name="Test recipient",
            compartment_id=compartment.id,
            status=OrderStatus.PAYMENT_PENDING.value,
            deposit_code_digest="d" * 64,
            pickup_otp_digest="p" * 64,
            stored_at=datetime.now(UTC) if stored else None,
            base_fee_vnd=7_000,
            grace_minutes=1_440,
            billing_unit_minutes=1_440,
            unit_fee_vnd=7_000,
        )
        session.add(order)
        await session.flush()
        payment = Payment(
            order_id=order.id,
            provider="payos",
            payos_order_code=987_654_321,
            amount_vnd=7_000,
            status=PaymentStatus.PENDING.value,
        )
        session.add(payment)
        await session.commit()

        mqtt = RecordingMqtt()
        request = AutoOpenRequest(
            PaymentGatewayStub(payment.payos_order_code, payment.amount_vnd), mqtt
        )
        result = await _process_payment_webhook(
            "payos", cast(Any, request), session
        )

        command = await session.scalar(select(DeviceCommand))
        await session.refresh(payment)
        assert result == {"success": True, "duplicate": False}
        assert payment.status == PaymentStatus.PAID.value
        assert command is not None
        assert command.purpose == expected_purpose.value
        assert command.box == compartment.number
        assert [event[0] for event in mqtt.events] == ["ui", "unlock"]
        ui_payload = cast(dict[str, object], mqtt.events[0][2])
        assert ui_payload["screen"] == expected_screen
        if not stored:
            assert ui_payload["auto_open"] is True

    await engine.dispose()
