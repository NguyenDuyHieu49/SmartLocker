import hashlib
import hmac
import json
from dataclasses import dataclass
from time import time
from typing import Any, Protocol

import httpx
from payos import PayOS  # type: ignore[import-untyped]
from payos.types import CreatePaymentLinkRequest  # type: ignore[import-untyped]

from app.core.config import Settings


@dataclass(frozen=True)
class PaymentLink:
    provider: str
    payment_link_id: str
    checkout_url: str
    qr_code: str


@dataclass(frozen=True)
class VerifiedPayment:
    order_code: int
    amount: int
    reference: str
    payment_link_id: str


class PaymentGateway(Protocol):
    name: str

    def create_link(
        self,
        *,
        order_code: int,
        amount: int,
        description: str,
        buyer_phone: str,
    ) -> PaymentLink: ...

    def verify_webhook(self, payload: bytes) -> VerifiedPayment: ...


class PayOSGateway:
    name = "payos"

    def __init__(self, settings: Settings) -> None:
        if not all(
            [
                settings.payos_client_id,
                settings.payos_api_key,
                settings.payos_checksum_key,
            ]
        ):
            raise RuntimeError("payos_credentials_missing")
        self.client = PayOS(
            client_id=settings.payos_client_id,
            api_key=settings.payos_api_key,
            checksum_key=settings.payos_checksum_key,
        )
        self.settings = settings

    def confirm_webhook(self) -> None:
        self.client.webhooks.confirm(
            f"{self.settings.api_url}/api/v1/webhooks/payos"
        )

    def create_link(
        self,
        *,
        order_code: int,
        amount: int,
        description: str,
        buyer_phone: str,
    ) -> PaymentLink:
        request = CreatePaymentLinkRequest(
            orderCode=order_code,
            amount=amount,
            description=description[:9],
            buyerPhone=buyer_phone,
            returnUrl=f"{self.settings.dashboard_url}/payment/success",
            cancelUrl=f"{self.settings.dashboard_url}/payment/cancel",
            expiredAt=int(time()) + 15 * 60,
        )
        response = self.client.payment_requests.create(request)
        return PaymentLink(
            provider=self.name,
            payment_link_id=response.payment_link_id,
            checkout_url=response.checkout_url,
            qr_code=response.qr_code,
        )

    def verify_webhook(self, payload: bytes) -> VerifiedPayment:
        data = self.client.webhooks.verify(payload)
        return VerifiedPayment(
            order_code=data.order_code,
            amount=data.amount,
            reference=data.reference,
            payment_link_id=data.payment_link_id,
        )


class MomoSandboxGateway:
    name = "momo_sandbox"

    def __init__(self, settings: Settings) -> None:
        if not all(
            [
                settings.momo_partner_code,
                settings.momo_access_key,
                settings.momo_secret_key,
            ]
        ):
            raise RuntimeError("momo_credentials_missing")
        self.settings = settings
        self.partner_code = settings.momo_partner_code or ""
        self.access_key = settings.momo_access_key or ""
        self.secret_key = settings.momo_secret_key or ""

    def _sign(self, raw: str) -> str:
        return hmac.new(
            self.secret_key.encode("utf-8"),
            raw.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _value(data: dict[str, Any], key: str) -> str:
        value = data.get(key, "")
        return "" if value is None else str(value)

    def create_link(
        self,
        *,
        order_code: int,
        amount: int,
        description: str,
        buyer_phone: str,
    ) -> PaymentLink:
        del buyer_phone
        order_id = str(order_code)
        request_id = f"SB{order_code}"
        request_type = "captureWallet"
        extra_data = ""
        redirect_url = f"{self.settings.dashboard_url}/payment/success"
        ipn_url = f"{self.settings.api_url}/api/v1/webhooks/momo"
        order_info = description[:255]
        raw_signature = (
            f"accessKey={self.access_key}&amount={amount}&extraData={extra_data}"
            f"&ipnUrl={ipn_url}&orderId={order_id}&orderInfo={order_info}"
            f"&partnerCode={self.partner_code}&redirectUrl={redirect_url}"
            f"&requestId={request_id}&requestType={request_type}"
        )
        body: dict[str, object] = {
            "partnerCode": self.partner_code,
            "partnerName": "SmartBox",
            "storeId": "SmartBox",
            "requestId": request_id,
            "amount": amount,
            "orderId": order_id,
            "orderInfo": order_info,
            "redirectUrl": redirect_url,
            "ipnUrl": ipn_url,
            "requestType": request_type,
            "extraData": extra_data,
            "autoCapture": True,
            "lang": "vi",
            "signature": self._sign(raw_signature),
        }
        response = httpx.post(
            f"{self.settings.momo_base_url.rstrip('/')}/v2/gateway/api/create",
            json=body,
            timeout=self.settings.momo_timeout_seconds,
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or int(result.get("resultCode", -1)) != 0:
            message = (
                result.get("message", "momo_create_failed")
                if isinstance(result, dict)
                else "momo_create_failed"
            )
            raise RuntimeError(str(message))
        if (
            self._value(result, "partnerCode") != self.partner_code
            or self._value(result, "requestId") != request_id
            or self._value(result, "orderId") != order_id
            or int(result.get("amount", 0)) != amount
        ):
            raise RuntimeError("momo_response_mismatch")

        response_signature = self._value(result, "signature")
        if response_signature:
            response_raw = (
                f"accessKey={self.access_key}&amount={self._value(result, 'amount')}"
                f"&message={self._value(result, 'message')}"
                f"&orderId={self._value(result, 'orderId')}"
                f"&partnerCode={self._value(result, 'partnerCode')}"
                f"&payUrl={self._value(result, 'payUrl')}"
                f"&requestId={self._value(result, 'requestId')}"
                f"&responseTime={self._value(result, 'responseTime')}"
                f"&resultCode={self._value(result, 'resultCode')}"
            )
            if not hmac.compare_digest(response_signature, self._sign(response_raw)):
                raise RuntimeError("momo_response_signature_invalid")

        pay_url = self._value(result, "payUrl")
        qr_code = self._value(result, "qrCodeUrl") or pay_url
        if not pay_url:
            raise RuntimeError("momo_checkout_url_missing")
        return PaymentLink(
            provider=self.name,
            payment_link_id=request_id,
            checkout_url=pay_url,
            qr_code=qr_code,
        )

    def verify_webhook(self, payload: bytes) -> VerifiedPayment:
        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("momo_webhook_json_invalid") from exc
        if not isinstance(data, dict):
            raise TypeError("momo_webhook_json_invalid")

        signature = self._value(data, "signature")
        raw_signature = (
            f"accessKey={self.access_key}&amount={self._value(data, 'amount')}"
            f"&extraData={self._value(data, 'extraData')}"
            f"&message={self._value(data, 'message')}"
            f"&orderId={self._value(data, 'orderId')}"
            f"&orderInfo={self._value(data, 'orderInfo')}"
            f"&orderType={self._value(data, 'orderType')}"
            f"&partnerCode={self._value(data, 'partnerCode')}"
            f"&payType={self._value(data, 'payType')}"
            f"&requestId={self._value(data, 'requestId')}"
            f"&responseTime={self._value(data, 'responseTime')}"
            f"&resultCode={self._value(data, 'resultCode')}"
            f"&transId={self._value(data, 'transId')}"
        )
        if (
            self._value(data, "partnerCode") != self.partner_code
            or not signature
            or not hmac.compare_digest(signature, self._sign(raw_signature))
        ):
            raise RuntimeError("momo_webhook_signature_invalid")
        if int(data.get("resultCode", -1)) != 0:
            raise RuntimeError("momo_payment_not_successful")

        try:
            order_code = int(self._value(data, "orderId"))
            amount = int(self._value(data, "amount"))
        except ValueError as exc:
            raise RuntimeError("momo_webhook_values_invalid") from exc
        reference = self._value(data, "transId")
        request_id = self._value(data, "requestId")
        if amount <= 0 or not reference or not request_id:
            raise RuntimeError("momo_webhook_values_invalid")
        return VerifiedPayment(
            order_code=order_code,
            amount=amount,
            reference=reference,
            payment_link_id=request_id,
        )


class MockPaymentGateway:
    name = "mock"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create_link(
        self,
        *,
        order_code: int,
        amount: int,
        description: str,
        buyer_phone: str,
    ) -> PaymentLink:
        del description, buyer_phone
        token = f"MOCK-{order_code}-{amount}"
        return PaymentLink(
            provider=self.name,
            payment_link_id=token,
            checkout_url="",
            qr_code=token,
        )

    def verify_webhook(self, payload: bytes) -> VerifiedPayment:
        raise RuntimeError("mock_gateway_does_not_verify_webhooks")


def create_payment_gateway(settings: Settings) -> PaymentGateway:
    provider = settings.effective_payment_provider
    if provider == "payos":
        return PayOSGateway(settings)
    if provider == "momo_sandbox":
        return MomoSandboxGateway(settings)
    return MockPaymentGateway(settings)
