"""Outbound customer notifications.

Each channel (email today, SMS later) implements `Notifier`. The dispatcher sends a
message on every channel the recipient can be reached on, so adding SMS only needs a
new notifier that reads `Recipient.phone`.
"""

import asyncio
import logging
import smtplib
import ssl
from collections.abc import Sequence
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Recipient:
    name: str
    phone: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class Message:
    subject: str
    body: str


class Notifier(Protocol):
    channel: str

    def address_for(self, recipient: Recipient) -> str | None: ...

    async def send(self, address: str, message: Message) -> None: ...


class EmailNotifier:
    channel = "email"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        sender: str,
        use_ssl: bool = False,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender
        self.use_ssl = use_ssl
        self.timeout_seconds = timeout_seconds

    def address_for(self, recipient: Recipient) -> str | None:
        return recipient.email

    async def send(self, address: str, message: Message) -> None:
        # smtplib is blocking; keep the event loop free for MQTT processing.
        await asyncio.to_thread(self._send_sync, address, message)

    def _send_sync(self, address: str, message: Message) -> None:
        email = EmailMessage()
        email["From"] = self.sender
        email["To"] = address
        email["Subject"] = message.subject
        email.set_content(message.body)
        context = ssl.create_default_context()
        if self.use_ssl:
            with smtplib.SMTP_SSL(
                self.host, self.port, timeout=self.timeout_seconds, context=context
            ) as smtp:
                smtp.login(self.username, self.password)
                smtp.send_message(email)
        else:
            with smtplib.SMTP(
                self.host, self.port, timeout=self.timeout_seconds
            ) as smtp:
                smtp.starttls(context=context)
                smtp.login(self.username, self.password)
                smtp.send_message(email)


class BrevoEmailNotifier:
    channel = "email"
    endpoint = "https://api.brevo.com/v3/smtp/email"

    def __init__(
        self,
        *,
        api_key: str,
        sender_email: str,
        sender_name: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.api_key = api_key
        self.sender_email = sender_email
        self.sender_name = sender_name
        self.timeout_seconds = timeout_seconds

    def address_for(self, recipient: Recipient) -> str | None:
        return recipient.email

    async def send(self, address: str, message: Message) -> None:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                self.endpoint,
                headers={"api-key": self.api_key, "accept": "application/json"},
                json={
                    "sender": {"email": self.sender_email, "name": self.sender_name},
                    "to": [{"email": address}],
                    "subject": message.subject,
                    "textContent": message.body,
                },
            )
            response.raise_for_status()


class NotificationDispatcher:
    def __init__(self, notifiers: Sequence[Notifier] = ()) -> None:
        self.notifiers = list(notifiers)
        self._background: set[asyncio.Task[list[str]]] = set()

    async def notify(self, recipient: Recipient, message: Message) -> list[str]:
        """Send on every reachable channel and return the channels that succeeded."""
        delivered: list[str] = []
        for notifier in self.notifiers:
            address = notifier.address_for(recipient)
            if not address:
                continue
            try:
                await notifier.send(address, message)
            except Exception:
                # A mail/SMS outage must never break locker operations.
                logger.exception("Failed to send %s notification", notifier.channel)
            else:
                delivered.append(notifier.channel)
        return delivered

    def notify_in_background(self, recipient: Recipient, message: Message) -> None:
        task = asyncio.get_running_loop().create_task(
            self.notify(recipient, message)
        )
        # Keep a strong reference until the task finishes so it is not collected.
        self._background.add(task)
        task.add_done_callback(self._background.discard)


def pickup_ready_message(
    *,
    recipient_name: str,
    order_code: str,
    pickup_otp: str,
    box_number: int,
    station_name: str,
    station_address: str,
) -> Message:
    location = f"{station_name} - {station_address}" if station_address else station_name
    return Message(
        subject=f"SmartBox: Mã lấy hàng cho đơn {order_code}",
        body=(
            f"Xin chào {recipient_name},\n\n"
            f"Đơn hàng {order_code} đã được gửi vào ngăn #{box_number + 1} "
            f"tại {location}.\n\n"
            f"Mã lấy hàng (OTP): {pickup_otp}\n\n"
            "Nhập mã này trên bàn phím của tủ để mở ngăn. "
            "Phí lưu trữ được thanh toán khi lấy hàng.\n"
            "Không chia sẻ mã này với bất kỳ ai.\n\n"
            "SmartBox"
        ),
    )


def build_dispatcher(settings: Settings) -> NotificationDispatcher:
    notifiers: list[Notifier] = []
    if settings.brevo_api_key and settings.brevo_sender_email:
        # HTTPS works on hosts that block outbound SMTP (e.g. Render free plan).
        notifiers.append(
            BrevoEmailNotifier(
                api_key=settings.brevo_api_key,
                sender_email=settings.brevo_sender_email,
                sender_name=settings.brevo_sender_name,
                timeout_seconds=settings.smtp_timeout_seconds,
            )
        )
    elif settings.smtp_username and settings.smtp_password:
        notifiers.append(
            EmailNotifier(
                host=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_username,
                # Gmail displays app passwords in groups of four characters.
                password=settings.smtp_password.replace(" ", ""),
                sender=settings.smtp_sender or settings.smtp_username,
                use_ssl=settings.smtp_use_ssl,
                timeout_seconds=settings.smtp_timeout_seconds,
            )
        )
    else:
        logger.info("No email provider is configured; email notifications are disabled")
    return NotificationDispatcher(notifiers)
