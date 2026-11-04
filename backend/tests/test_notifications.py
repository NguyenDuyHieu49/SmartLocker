import asyncio
import json
from email.message import EmailMessage
from typing import Any, Self, cast

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.models import (
    Base,
    CommandPurpose,
    CommandStatus,
    Compartment,
    CompartmentStatus,
    DeviceCommand,
    DoorEvent,
    LockerStation,
    Order,
    OrderStatus,
    User,
)
from app.security import derive_numeric_code
from app.services.device_events import DeviceEventProcessor
from app.services.notifications import (
    BrevoEmailNotifier,
    EmailNotifier,
    Message,
    NotificationDispatcher,
    Recipient,
    build_dispatcher,
)


class RecordingNotifier:
    def __init__(self, channel: str, *, fail: bool = False) -> None:
        self.channel = channel
        self.fail = fail
        self.sent: list[tuple[str, Message]] = []

    def address_for(self, recipient: Recipient) -> str | None:
        return recipient.email if self.channel == "email" else recipient.phone

    async def send(self, address: str, message: Message) -> None:
        if self.fail:
            raise ConnectionError("smtp down")
        self.sent.append((address, message))


@pytest.mark.asyncio
async def test_dispatcher_skips_unreachable_channels_and_survives_failures() -> None:
    email = RecordingNotifier("email", fail=True)
    sms = RecordingNotifier("sms")
    dispatcher = NotificationDispatcher([email, sms])

    delivered = await dispatcher.notify(
        Recipient(name="An", phone="0901234567"), Message("s", "b")
    )

    assert delivered == ["sms"]
    assert email.sent == []
    assert sms.sent == [("0901234567", Message("s", "b"))]


def test_email_is_disabled_without_smtp_credentials() -> None:
    settings = Settings(smtp_username=None, smtp_password=None)
    assert build_dispatcher(settings).notifiers == []


def test_gmail_app_password_spaces_are_removed() -> None:
    dispatcher = build_dispatcher(
        Settings(
            smtp_sender=None,
            smtp_username="box@gmail.com",
            smtp_password="abcd efgh ijkl mnop",
        )
    )

    notifier = cast(EmailNotifier, dispatcher.notifiers[0])
    assert notifier.password == "abcdefghijklmnop"
    assert notifier.sender == "box@gmail.com"


@pytest.mark.asyncio
async def test_email_notifier_uses_starttls(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    sent: list[EmailMessage] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            calls.append(f"connect {host}:{port}")

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_: object) -> None:
            calls.append("quit")

        def starttls(self, context: object) -> None:
            calls.append("starttls")

        def login(self, username: str, password: str) -> None:
            calls.append(f"login {username}")

        def send_message(self, message: EmailMessage) -> None:
            sent.append(message)

    monkeypatch.setattr("app.services.notifications.smtplib.SMTP", FakeSMTP)
    notifier = EmailNotifier(
        host="smtp.gmail.com",
        port=587,
        username="box@gmail.com",
        password="secret",
        sender="SmartBox <box@gmail.com>",
    )

    await notifier.send("an@example.com", Message("Mã OTP", "12345678"))

    assert calls == [
        "connect smtp.gmail.com:587",
        "starttls",
        "login box@gmail.com",
        "quit",
    ]
    assert sent[0]["To"] == "an@example.com"
    assert sent[0]["Subject"] == "Mã OTP"
    assert sent[0].get_content().strip() == "12345678"


def test_brevo_takes_precedence_over_smtp() -> None:
    dispatcher = build_dispatcher(
        Settings(
            smtp_username="box@gmail.com",
            smtp_password="secret",
            brevo_api_key="xkeysib-test",
            brevo_sender_email="box@gmail.com",
        )
    )

    [notifier] = dispatcher.notifiers
    assert isinstance(notifier, BrevoEmailNotifier)


@pytest.mark.asyncio
async def test_brevo_notifier_posts_transactional_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json={"messageId": "abc"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "app.services.notifications.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    notifier = BrevoEmailNotifier(
        api_key="xkeysib-test", sender_email="box@gmail.com", sender_name="SmartBox"
    )

    await notifier.send("an@example.com", Message("Mã OTP", "12345678"))

    [request] = requests
    assert str(request.url) == "https://api.brevo.com/v3/smtp/email"
    assert request.headers["api-key"] == "xkeysib-test"
    assert json.loads(request.content) == {
        "sender": {"email": "box@gmail.com", "name": "SmartBox"},
        "to": [{"email": "an@example.com"}],
        "subject": "Mã OTP",
        "textContent": "12345678",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("order_email", "account_email", "expected_to"),
    [
        ("order@example.com", "account@example.com", "order@example.com"),
        (None, "account@example.com", "account@example.com"),
        (None, None, None),
    ],
)
async def test_deposit_confirmation_emails_pickup_otp(
    monkeypatch: pytest.MonkeyPatch,
    order_email: str | None,
    account_email: str | None,
    expected_to: str | None,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(
        "app.services.device_events.SessionFactory", session_factory
    )

    async with session_factory() as session:
        session.add(
            User(
                phone="0901234567",
                name="Account",
                password_hash="x",
                role="CUSTOMER",
                email=account_email,
            )
        )
        station = LockerStation(
            device_id="SB-001", name="SmartBox Demo", address="1 Dai Co Viet"
        )
        session.add(station)
        await session.flush()
        compartment = Compartment(
            station_id=station.id,
            number=1,
            status=CompartmentStatus.RESERVED.value,
        )
        session.add(compartment)
        await session.flush()
        order = Order(
            order_code="12345678",
            shipper_id=None,
            recipient_phone="0901234567",
            recipient_name="Nguyen Van An",
            recipient_email=order_email,
            compartment_id=compartment.id,
            status=OrderStatus.DEPOSIT_OPEN.value,
            deposit_code_digest="d" * 64,
            pickup_otp_digest="p" * 64,
            base_fee_vnd=5_000,
            grace_minutes=1_440,
            billing_unit_minutes=1_440,
            unit_fee_vnd=5_000,
        )
        session.add(order)
        await session.flush()
        session.add_all(
            [
                DeviceCommand(
                    request_id="req-1",
                    device_id="SB-001",
                    box=1,
                    purpose=CommandPurpose.DEPOSIT.value,
                    order_id=order.id,
                    status=CommandStatus.ACKNOWLEDGED.value,
                ),
                DoorEvent(
                    event_key="door-1",
                    device_id="SB-001",
                    box=1,
                    door_closed=True,
                    device_timestamp=1,
                ),
            ]
        )
        await session.commit()

    email = RecordingNotifier("email")
    dispatcher = NotificationDispatcher([email])
    processor = DeviceEventProcessor(
        cast(Any, None),
        cast(Any, None),
        asyncio.get_running_loop(),
        notifier=dispatcher,
    )

    await processor.handle(
        "SB-001", "confirm_finish", {"action": "deposit_confirmed", "box": 1}
    )
    await asyncio.gather(*dispatcher._background)

    async with session_factory() as session:
        stored = await session.get(Order, order.id)
        assert stored is not None
        assert stored.status == OrderStatus.STORED.value

    if expected_to is None:
        assert email.sent == []
    else:
        [(address, message)] = email.sent
        otp = derive_numeric_code("12345678", "pickup", length=8)
        assert address == expected_to
        assert otp in message.body
        assert "ngăn #2" in message.body
        assert "SmartBox Demo - 1 Dai Co Viet" in message.body
    await engine.dispose()
