import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.models import Order
from app.payments import MockPaymentGateway, MomoSandboxGateway, PayOSGateway
from app.security import code_digest, derive_numeric_code, normalize_phone, verify_code
from app.services.common import calculate_fee


def make_order(stored_at: datetime | None) -> Order:
    return Order(
        order_code="12345678",
        shipper_id="shipper",
        recipient_phone="0901234567",
        recipient_name="Khach hang",
        compartment_id="box",
        status="STORED",
        deposit_code_digest="digest-deposit",
        pickup_otp_digest="digest-otp",
        stored_at=stored_at,
        base_fee_vnd=5_000,
        grace_minutes=60,
        billing_unit_minutes=60,
        unit_fee_vnd=2_000,
    )


def test_fee_uses_base_fee_during_grace_period() -> None:
    now = datetime.now(UTC)
    order = make_order(now - timedelta(minutes=59))
    assert calculate_fee(order, now) == 5_000


def test_fee_rounds_each_started_billing_unit_up() -> None:
    now = datetime.now(UTC)
    order = make_order(now - timedelta(minutes=121))
    assert calculate_fee(order, now) == 9_000


def test_phone_normalization_and_otp_digest() -> None:
    expected = "0912345678"
    assert normalize_phone("0912 345 678") == expected
    assert normalize_phone("+84 912 345 678") == expected
    assert normalize_phone("+84 0912 345 678") == expected
    digest = code_digest("483920")
    assert verify_code("483920", digest)
    assert not verify_code("483921", digest)


def test_pickup_otp_is_stable_but_scoped_to_order() -> None:
    first = derive_numeric_code("12345678", "pickup")
    assert first == derive_numeric_code("12345678", "pickup")
    assert first != derive_numeric_code("87654321", "pickup")
    assert len(first) == 8 and first.isdigit()


def test_invalid_phone_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid_phone"):
        normalize_phone("123")


def test_production_rejects_ephemeral_sqlite_database() -> None:
    with pytest.raises(
        ValidationError,
        match="DATABASE_URL must use a persistent production database",
    ):
        Settings(
            environment="production",
            database_url="sqlite+aiosqlite:///./smartlocker.db",
            jwt_secret="j" * 32,
            otp_pepper="o" * 32,
            bootstrap_admin_password="ProductionAdminPassword",
            demo_mode=False,
            payment_provider="payos",
            payos_client_id="client",
            payos_api_key="api-key",
            payos_checksum_key="checksum-key",
            mqtt_tls=True,
        )


def test_mock_payment_contains_dashboard_return_url() -> None:
    gateway = MockPaymentGateway(Settings(dashboard_url="https://app.smartbox.id.vn"))
    link = gateway.create_link(
        order_code=1_234_567_890,
        amount=7_000,
        description="SB12345678",
        buyer_phone="0901234567",
    )
    assert link.provider == "mock"
    assert link.qr_code == "MOCK-1234567890-7000"
    assert link.checkout_url == ""


def test_railway_postgres_url_is_converted_for_asyncpg() -> None:
    settings = Settings(database_url="postgresql://user:pass@host/db")
    assert settings.async_database_url == "postgresql+asyncpg://user:pass@host/db"


def test_neon_postgres_url_is_converted_for_asyncpg() -> None:
    settings = Settings(
        database_url=(
            "postgresql://user:pass@host/db?sslmode=require&channel_binding=require"
        )
    )
    assert settings.async_database_url == (
        "postgresql+asyncpg://user:pass@host/db?ssl=require"
    )


def test_payos_webhook_uses_public_api_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    class FakeWebhooks:
        def confirm(self, url: str) -> None:
            captured["url"] = url

    class FakePayOS:
        def __init__(self, **_: str) -> None:
            self.webhooks = FakeWebhooks()

    monkeypatch.setattr("app.payments.PayOS", FakePayOS)
    gateway = PayOSGateway(
        Settings(
            payos_client_id="client",
            payos_api_key="api-key",
            payos_checksum_key="checksum",
            api_url="https://api.smartbox.id.vn",
        )
    )
    gateway.confirm_webhook()

    assert captured["url"] == ("https://api.smartbox.id.vn/api/v1/webhooks/payos")


def momo_gateway() -> MomoSandboxGateway:
    return MomoSandboxGateway(
        Settings(
            momo_partner_code="SMARTBOX_TEST",
            momo_access_key="access-key",
            momo_secret_key="secret-key",
            api_url="https://api.smartbox.id.vn",
            dashboard_url="https://smartbox.id.vn",
        )
    )


def test_momo_create_link_signs_request(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "partnerCode": "SMARTBOX_TEST",
                "requestId": "SB1234567890",
                "orderId": "1234567890",
                "amount": 7000,
                "resultCode": 0,
                "message": "Successful.",
                "payUrl": "https://test-payment.momo.vn/pay/demo",
                "qrCodeUrl": "MOMO-QR-PAYLOAD",
            }

    def fake_post(url: str, **kwargs: Any) -> Response:
        captured["url"] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr("app.payments.httpx.post", fake_post)
    link = momo_gateway().create_link(
        order_code=1_234_567_890,
        amount=7000,
        description="SB12345678",
        buyer_phone="0901234567",
    )

    body = captured["json"]
    assert isinstance(body, dict)
    raw = (
        "accessKey=access-key&amount=7000&extraData="
        "&ipnUrl=https://api.smartbox.id.vn/api/v1/webhooks/momo"
        "&orderId=1234567890&orderInfo=SB12345678"
        "&partnerCode=SMARTBOX_TEST"
        "&redirectUrl=https://smartbox.id.vn/payment/success"
        "&requestId=SB1234567890&requestType=captureWallet"
    )
    expected = hmac.new(b"secret-key", raw.encode(), hashlib.sha256).hexdigest()
    assert body["signature"] == expected
    assert link.provider == "momo_sandbox"
    assert link.qr_code == "MOMO-QR-PAYLOAD"


def test_momo_webhook_rejects_tampering() -> None:
    gateway = momo_gateway()
    data: dict[str, object] = {
        "partnerCode": "SMARTBOX_TEST",
        "orderId": "1234567890",
        "requestId": "SB1234567890",
        "amount": 7000,
        "orderInfo": "SB12345678",
        "orderType": "momo_wallet",
        "transId": 99887766,
        "resultCode": 0,
        "message": "Successful.",
        "payType": "qr",
        "responseTime": 1792250000000,
        "extraData": "",
    }
    raw = (
        "accessKey=access-key&amount=7000&extraData="
        "&message=Successful.&orderId=1234567890&orderInfo=SB12345678"
        "&orderType=momo_wallet&partnerCode=SMARTBOX_TEST&payType=qr"
        "&requestId=SB1234567890&responseTime=1792250000000"
        "&resultCode=0&transId=99887766"
    )
    data["signature"] = hmac.new(
        b"secret-key", raw.encode(), hashlib.sha256
    ).hexdigest()
    verified = gateway.verify_webhook(json.dumps(data).encode())
    assert verified.order_code == 1_234_567_890
    assert verified.reference == "99887766"

    data["amount"] = 7001
    with pytest.raises(RuntimeError, match="signature_invalid"):
        gateway.verify_webhook(json.dumps(data).encode())
