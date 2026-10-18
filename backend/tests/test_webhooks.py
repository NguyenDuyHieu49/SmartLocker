from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.api.webhooks import _process_payment_webhook
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
