import asyncio
import logging
from concurrent.futures import Future
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionFactory
from app.models import (
    CommandPurpose,
    CommandStatus,
    Compartment,
    CompartmentStatus,
    DeviceCommand,
    DoorEvent,
    LockerStation,
    Order,
    OrderStatus,
)
from app.mqtt.service import MqttService
from app.payments import PaymentGateway
from app.security import code_digest, verify_code
from app.services.commands import mark_command_ack, publish_unlock
from app.services.common import add_audit, find_station_and_box
from app.services.payment_service import create_or_get_payment

logger = logging.getLogger(__name__)


class DeviceEventProcessor:
    def __init__(
        self,
        mqtt: MqttService,
        payment_gateway: PaymentGateway,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.mqtt = mqtt
        self.payment_gateway = payment_gateway
        self.loop = loop

    def submit(self, device_id: str, event_name: str, payload: dict[str, Any]) -> None:
        future = asyncio.run_coroutine_threadsafe(
            self.handle(device_id, event_name, payload), self.loop
        )
        future.add_done_callback(self._log_failure)

    @staticmethod
    def _log_failure(future: Future[None]) -> None:
        try:
            future.result()
        except Exception:
            logger.exception("Failed to process device event")

    async def handle(
        self, device_id: str, event_name: str, payload: dict[str, Any]
    ) -> None:
        if event_name == "unlock_result":
            await self._unlock_result(device_id, payload)
        elif event_name == "door":
            await self._door_event(device_id, payload)
        elif event_name == "access_request":
            await self._access_request(device_id, payload)

    async def _unlock_result(self, device_id: str, payload: dict[str, Any]) -> None:
        request_id = str(payload.get("request_id", ""))
        if not request_id:
            return
        async with SessionFactory() as session:
            command = await mark_command_ack(
                session,
                request_id,
                bool(payload.get("success")),
                payload.get("error"),
            )
            if command is None:
                return
            if not payload.get("success"):
                self._show_error(device_id, "Khong mo duoc tu")
                return
            if command.order_id is None:
                return
            order = await session.get(Order, command.order_id)
            if order is None:
                return
            order.status = (
                OrderStatus.DEPOSIT_AUTHORIZED.value
                if command.purpose == CommandPurpose.DEPOSIT.value
                else OrderStatus.PICKUP_AUTHORIZED.value
            )
            await session.commit()

    async def _access_request(self, device_id: str, payload: dict[str, Any]) -> None:
        action = str(payload.get("action", ""))
        async with SessionFactory() as session:
            if action == "deposit":
                await self._deposit_request(
                    session, device_id, str(payload.get("code", ""))
                )
            elif action == "pickup_start":
                await self._pickup_start(
                    session, device_id, str(payload.get("order_code", ""))
                )
            elif action == "pickup_otp":
                await self._pickup_otp(
                    session,
                    device_id,
                    str(payload.get("order_code", "")),
                    str(payload.get("otp", "")),
                )
            else:
                self._show_error(device_id, "Yeu cau khong hop le")

    async def _deposit_request(
        self, session: AsyncSession, device_id: str, code: str
    ) -> None:
        if len(code) != 6 or not code.isdigit():
            self._show_error(device_id, "Ma gui hang khong hop le")
            return
        order = await session.scalar(
            select(Order).where(
                Order.deposit_code_digest == code_digest(code),
                Order.status == OrderStatus.RESERVED.value,
            )
        )
        mapping = await self._order_mapping(session, order, device_id)
        if order is None or mapping is None:
            self._show_error(device_id, "Khong tim thay don gui")
            return
        _, compartment = mapping
        await self._publish_access_unlock(
            session, device_id, order, compartment, CommandPurpose.DEPOSIT
        )

    async def _pickup_start(
        self, session: AsyncSession, device_id: str, order_code: str
    ) -> None:
        order = await session.scalar(
            select(Order).where(Order.order_code == order_code)
        )
        mapping = await self._order_mapping(session, order, device_id)
        if order is None or mapping is None:
            self._show_error(device_id, "Khong tim thay don hang")
            return
        if order.status == OrderStatus.PAID.value:
            self.mqtt.show_ui(
                device_id,
                {"screen": "enter_otp", "order_code": order.order_code},
            )
            return
        if order.status not in {
            OrderStatus.STORED.value,
            OrderStatus.PAYMENT_PENDING.value,
        }:
            self._show_error(device_id, "Don hang chua san sang")
            return
        try:
            payment, provider = await create_or_get_payment(
                session, self.payment_gateway, order, actor_id=None
            )
        except Exception:
            logger.exception("Failed to create payment for order %s", order.order_code)
            self._show_error(device_id, "Khong tao duoc thanh toan")
            return
        self.mqtt.show_ui(
            device_id,
            {
                "screen": "payment",
                "order_code": order.order_code,
                "amount_vnd": payment.amount_vnd,
                "qr_code": payment.qr_code or "",
                "checkout_url": payment.checkout_url or "",
                "provider": provider,
            },
        )

    async def _pickup_otp(
        self,
        session: AsyncSession,
        device_id: str,
        order_code: str,
        otp: str,
    ) -> None:
        order = await session.scalar(
            select(Order).where(Order.order_code == order_code)
        )
        mapping = await self._order_mapping(session, order, device_id)
        if order is None or mapping is None:
            self._show_error(device_id, "Khong tim thay don hang")
            return
        if order.status != OrderStatus.PAID.value:
            self._show_error(device_id, "Can thanh toan truoc")
            return
        if order.pickup_otp_attempts >= 5:
            self._show_error(device_id, "OTP da bi khoa")
            return
        if not verify_code(otp, order.pickup_otp_digest):
            order.pickup_otp_attempts += 1
            await session.commit()
            self._show_error(device_id, f"OTP sai ({order.pickup_otp_attempts}/5)")
            return
        _, compartment = mapping
        await self._publish_access_unlock(
            session, device_id, order, compartment, CommandPurpose.PICKUP
        )

    async def _publish_access_unlock(
        self,
        session: AsyncSession,
        device_id: str,
        order: Order,
        compartment: Compartment,
        purpose: CommandPurpose,
    ) -> None:
        try:
            await publish_unlock(
                session,
                self.mqtt,
                device_id=device_id,
                box=compartment.number,
                purpose=purpose,
                order_id=order.id,
                actor_id=None,
            )
        except RuntimeError:
            self._show_error(device_id, "Tu dang mat ket noi")
            return
        self.mqtt.show_ui(
            device_id,
            {
                "screen": "message",
                "title": "Dang mo ngan tu",
                "message": f"Ngan {compartment.number + 1}",
                "timeout_ms": 8000,
            },
        )

    @staticmethod
    async def _order_mapping(
        session: AsyncSession,
        order: Order | None,
        device_id: str,
    ) -> tuple[LockerStation, Compartment] | None:
        if order is None:
            return None
        compartment = await session.get(Compartment, order.compartment_id)
        station = (
            await session.get(LockerStation, compartment.station_id)
            if compartment
            else None
        )
        if compartment is None or station is None or station.device_id != device_id:
            return None
        return station, compartment

    def _show_error(self, device_id: str, message: str) -> None:
        try:
            self.mqtt.show_ui(
                device_id,
                {
                    "screen": "message",
                    "title": "Khong the xu ly",
                    "message": message,
                    "timeout_ms": 7000,
                },
            )
        except RuntimeError:
            logger.warning("Could not display device error for %s", device_id)

    async def _door_event(self, device_id: str, payload: dict[str, Any]) -> None:
        box = int(payload.get("box", -1))
        timestamp = int(payload.get("timestamp", 0))
        door_closed = bool(payload.get("door_closed"))
        if not 0 <= box <= 4:
            return
        event_key = f"{device_id}:{box}:{timestamp}:{int(door_closed)}"

        async with SessionFactory() as session:
            if await session.scalar(
                select(DoorEvent).where(DoorEvent.event_key == event_key)
            ):
                return
            session.add(
                DoorEvent(
                    event_key=event_key,
                    device_id=device_id,
                    box=box,
                    door_closed=door_closed,
                    device_timestamp=timestamp,
                )
            )
            _, compartment = await find_station_and_box(session, device_id, box)
            command = await session.scalar(
                select(DeviceCommand)
                .where(
                    DeviceCommand.device_id == device_id,
                    DeviceCommand.box == box,
                    DeviceCommand.status.in_(
                        [
                            CommandStatus.PUBLISHED.value,
                            CommandStatus.ACKNOWLEDGED.value,
                        ]
                    ),
                )
                .order_by(DeviceCommand.created_at.desc())
            )
            if command is None or command.order_id is None:
                await session.commit()
                return
            order = await session.get(Order, command.order_id)
            if order is None:
                await session.commit()
                return

            if not door_closed:
                order.status = (
                    OrderStatus.DEPOSIT_OPEN.value
                    if command.purpose == CommandPurpose.DEPOSIT.value
                    else OrderStatus.PICKUP_OPEN.value
                )
            elif command.purpose == CommandPurpose.DEPOSIT.value and order.status in {
                OrderStatus.DEPOSIT_OPEN.value,
                OrderStatus.DEPOSIT_AUTHORIZED.value,
            }:
                order.status = OrderStatus.STORED.value
                order.stored_at = datetime.now(UTC)
                compartment.status = CompartmentStatus.OCCUPIED.value
                command.status = CommandStatus.COMPLETED.value
                self.mqtt.set_box(device_id, box, True)
                await add_audit(
                    session,
                    action="PACKAGE_STORED",
                    entity_type="order",
                    entity_id=order.id,
                    detail={"device_id": device_id, "box": box},
                )
                self.mqtt.show_ui(
                    device_id,
                    {
                        "screen": "message",
                        "title": "Gui hang thanh cong",
                        "message": "Hay dong cua tu",
                        "timeout_ms": 6000,
                    },
                )
            elif command.purpose == CommandPurpose.PICKUP.value and order.status in {
                OrderStatus.PICKUP_OPEN.value,
                OrderStatus.PICKUP_AUTHORIZED.value,
            }:
                order.status = OrderStatus.COMPLETED.value
                order.completed_at = datetime.now(UTC)
                compartment.status = CompartmentStatus.AVAILABLE.value
                command.status = CommandStatus.COMPLETED.value
                self.mqtt.set_box(device_id, box, False)
                await add_audit(
                    session,
                    action="PACKAGE_PICKED_UP",
                    entity_type="order",
                    entity_id=order.id,
                    detail={"device_id": device_id, "box": box},
                )
                self.mqtt.show_ui(
                    device_id,
                    {
                        "screen": "message",
                        "title": "Nhan hang thanh cong",
                        "message": "Cam on ban",
                        "timeout_ms": 6000,
                    },
                )
            await session.commit()
