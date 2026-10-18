import asyncio
import logging
import secrets
from concurrent.futures import Future
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
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
    User,
)
from app.mqtt.service import MqttService
from app.payments import PaymentGateway
from app.security import (
    code_digest,
    derive_numeric_code,
    generate_numeric_code,
    normalize_phone,
    verify_code,
)
from app.services.commands import mark_command_ack, publish_unlock
from app.services.common import add_audit, calculate_fee, find_station_and_box
from app.services.payment_service import create_or_get_payment

logger = logging.getLogger(__name__)
settings = get_settings()


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
        elif event_name == "keypad":
            await self._keypad_event(device_id, payload)
        elif event_name == "confirm_finish":
            await self._confirm_finish(device_id, payload)

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

    async def _keypad_event(
        self, device_id: str, payload: dict[str, Any]
    ) -> None:
        action = str(payload.get("action", ""))
        async with SessionFactory() as session:
            if action == "check_box":
                await self._check_box_availability(
                    session, device_id, str(payload.get("value", ""))
                )
            elif action == "deposit_phone":
                await self._deposit_phone(
                    session,
                    device_id,
                    str(payload.get("value", "")),
                    str(payload.get("extra", "")),
                )
            elif action == "pickup_otp":
                await self._pickup_otp(
                    session, device_id, str(payload.get("value", ""))
                )
            elif action == "open_confirmed":
                try:
                    box = int(payload.get("value", -1))
                except (TypeError, ValueError):
                    box = -1
                await self._open_confirmed(
                    session, device_id, str(payload.get("extra", "")), box
                )
            else:
                self._show_error(device_id, "Yeu cau ban phim khong hop le")

    async def _check_box_availability(
        self, session: AsyncSession, device_id: str, size: str
    ) -> None:
        size = size.upper()
        if size not in {"S", "M"}:
            self._show_error(device_id, "Kich thuoc ngan khong hop le")
            return
        station = await session.scalar(
            select(LockerStation).where(
                LockerStation.device_id == device_id,
                LockerStation.is_active.is_(True),
            )
        )
        if station is None:
            self._show_error(device_id, "Khong tim thay tram tu")
            return
        compartments = list(
            (
                await session.scalars(
                    select(Compartment)
                    .where(
                        Compartment.station_id == station.id,
                        Compartment.status == CompartmentStatus.AVAILABLE.value,
                        Compartment.size == size,
                        Compartment.number < 4,
                    )
                    .order_by(Compartment.number)
                )
            ).all()
        )
        physical = self.mqtt.registry.get_device(device_id)
        doors = {box.box: box.door_closed for box in physical.boxes}
        available = next(
            (
                compartment
                for compartment in compartments
                if doors.get(compartment.number, True)
            ),
            None,
        )
        if available is None:
            self._show_error(device_id, f"Khong con ngan {size}")
            return
        self.mqtt.show_ui(
            device_id,
            {
                "screen": "enter_phone",
                "size": size,
                "available_box": available.number,
            },
        )

    async def _deposit_phone(
        self,
        session: AsyncSession,
        device_id: str,
        raw_phone: str,
        size: str,
    ) -> None:
        try:
            phone = normalize_phone(raw_phone)
        except ValueError:
            self._show_error(device_id, "So dien thoai khong hop le")
            return
        if len(phone) != 10 or size not in {"S", "M"}:
            self._show_error(device_id, "SDT hoac kich thuoc khong hop le")
            return
        station = await session.scalar(
            select(LockerStation).where(
                LockerStation.device_id == device_id,
                LockerStation.is_active.is_(True),
            )
        )
        if station is None:
            self._show_error(device_id, "Khong tim thay tram tu")
            return
        compartment = await session.scalar(
            select(Compartment)
            .where(
                Compartment.station_id == station.id,
                Compartment.status == CompartmentStatus.AVAILABLE.value,
                Compartment.size == size,
                Compartment.number < 4,
            )
            .order_by(Compartment.number)
            .limit(1)
        )
        if compartment is None:
            self._show_error(device_id, f"Khong con ngan {size}")
            return
        recipient = await session.scalar(select(User).where(User.phone == phone))
        order_code = f"{secrets.randbelow(100_000_000):08d}"
        pickup_otp = derive_numeric_code(order_code, "pickup", length=8)
        order = Order(
            order_code=order_code,
            shipper_id=None,
            recipient_phone=phone,
            recipient_name=recipient.name if recipient else "Khach hang SmartBox",
            compartment_id=compartment.id,
            status=OrderStatus.RESERVED.value,
            deposit_code_digest=code_digest(generate_numeric_code(12)),
            pickup_otp_digest=code_digest(pickup_otp),
            base_fee_vnd=settings.base_fee_vnd,
            grace_minutes=settings.grace_minutes,
            billing_unit_minutes=settings.billing_unit_minutes,
            unit_fee_vnd=settings.unit_fee_vnd,
        )
        compartment.status = CompartmentStatus.RESERVED.value
        session.add(order)
        await session.flush()
        await add_audit(
            session,
            action="KIOSK_ORDER_CREATED",
            entity_type="order",
            entity_id=order.id,
            detail={"device_id": device_id, "box": compartment.number, "size": size},
        )
        await session.commit()
        try:
            payment, provider = await create_or_get_payment(
                session,
                self.payment_gateway,
                order,
                actor_id=None,
                amount_vnd=order.base_fee_vnd,
            )
        except Exception:
            logger.exception("Failed to create deposit payment for %s", order_code)
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
        self, session: AsyncSession, device_id: str, otp: str
    ) -> None:
        if len(otp) != 8 or not otp.isdigit():
            self._show_error(device_id, "OTP phai co 8 chu so")
            return
        order = await session.scalar(
            select(Order).where(
                Order.pickup_otp_digest == code_digest(otp),
                Order.status == OrderStatus.STORED.value,
            )
        )
        mapping = await self._order_mapping(session, order, device_id)
        if order is None or mapping is None:
            self._show_error(device_id, "OTP khong hop le")
            return
        if order.pickup_otp_attempts >= 5 or not verify_code(
            otp, order.pickup_otp_digest
        ):
            self._show_error(device_id, "OTP khong hop le")
            return
        _, compartment = mapping
        surcharge = max(0, calculate_fee(order) - order.base_fee_vnd)
        if surcharge == 0:
            self.mqtt.show_ui(
                device_id,
                {"screen": "door_guide", "mode": "pickup", "box": compartment.number},
            )
            return
        overdue_days = max(1, (surcharge + order.unit_fee_vnd - 1) // order.unit_fee_vnd)
        self.mqtt.show_ui(
            device_id,
            {
                "screen": "overdue",
                "box": compartment.number,
                "overdue_days": overdue_days,
                "daily_rate": order.unit_fee_vnd,
                "amount_vnd": surcharge,
            },
        )
        try:
            payment, provider = await create_or_get_payment(
                session,
                self.payment_gateway,
                order,
                actor_id=None,
                amount_vnd=surcharge,
            )
        except Exception:
            logger.exception("Failed to create overdue payment")
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

    async def _open_confirmed(
        self, session: AsyncSession, device_id: str, mode: str, box: int
    ) -> None:
        if mode not in {"deposit", "pickup"} or not 0 <= box < 4:
            self._show_error(device_id, "Xac nhan mo tu khong hop le")
            return
        _, compartment = await find_station_and_box(session, device_id, box)
        allowed_statuses = (
            {OrderStatus.PAID.value}
            if mode == "deposit"
            else {OrderStatus.STORED.value, OrderStatus.PAID.value}
        )
        order = await session.scalar(
            select(Order)
            .where(
                Order.compartment_id == compartment.id,
                Order.status.in_(allowed_statuses),
            )
            .order_by(Order.created_at.desc())
        )
        if order is None or (mode == "deposit" and order.stored_at is not None):
            self._show_error(device_id, "Khong tim thay giao dich")
            return
        purpose = (
            CommandPurpose.DEPOSIT if mode == "deposit" else CommandPurpose.PICKUP
        )
        await self._publish_access_unlock(
            session, device_id, order, compartment, purpose
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
                "screen": "door_guide",
                "mode": purpose.value.lower(),
                "box": compartment.number,
            },
        )

    @staticmethod
    async def _order_mapping(
        session: AsyncSession, order: Order | None, device_id: str
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
                    "screen": "alert",
                    "title": "Khong the xu ly",
                    "message": message,
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
            command = await session.scalar(
                select(DeviceCommand)
                .where(
                    DeviceCommand.device_id == device_id,
                    DeviceCommand.box == box,
                    DeviceCommand.status.in_(
                        [CommandStatus.PUBLISHED.value, CommandStatus.ACKNOWLEDGED.value]
                    ),
                )
                .order_by(DeviceCommand.created_at.desc())
            )
            if command is not None and command.order_id is not None and not door_closed:
                order = await session.get(Order, command.order_id)
                if order is not None:
                    order.status = (
                        OrderStatus.DEPOSIT_OPEN.value
                        if command.purpose == CommandPurpose.DEPOSIT.value
                        else OrderStatus.PICKUP_OPEN.value
                    )
            await session.commit()

    async def _confirm_finish(
        self, device_id: str, payload: dict[str, Any]
    ) -> None:
        action = str(payload.get("action", ""))
        box = int(payload.get("box", -1))
        if action not in {"deposit_confirmed", "pickup_confirmed"} or not 0 <= box < 4:
            return
        expected_purpose = (
            CommandPurpose.DEPOSIT.value
            if action == "deposit_confirmed"
            else CommandPurpose.PICKUP.value
        )
        async with SessionFactory() as session:
            last_door = await session.scalar(
                select(DoorEvent)
                .where(DoorEvent.device_id == device_id, DoorEvent.box == box)
                .order_by(DoorEvent.received_at.desc())
            )
            if last_door is None or not last_door.door_closed:
                self._show_error(device_id, "Cua chua dong chat")
                return
            command = await session.scalar(
                select(DeviceCommand)
                .where(
                    DeviceCommand.device_id == device_id,
                    DeviceCommand.box == box,
                    DeviceCommand.purpose == expected_purpose,
                    DeviceCommand.status.in_(
                        [CommandStatus.PUBLISHED.value, CommandStatus.ACKNOWLEDGED.value]
                    ),
                )
                .order_by(DeviceCommand.created_at.desc())
            )
            if command is None or command.order_id is None:
                self._show_error(device_id, "Khong tim thay lenh mo tu")
                return
            order = await session.get(Order, command.order_id)
            _, compartment = await find_station_and_box(session, device_id, box)
            if order is None:
                return
            if expected_purpose == CommandPurpose.DEPOSIT.value:
                order.status = OrderStatus.STORED.value
                order.stored_at = datetime.now(UTC)
                compartment.status = CompartmentStatus.OCCUPIED.value
                action_name = "PACKAGE_STORED"
                title = "GUI HANG THANH CONG"
            else:
                order.status = OrderStatus.COMPLETED.value
                order.completed_at = datetime.now(UTC)
                compartment.status = CompartmentStatus.AVAILABLE.value
                action_name = "PACKAGE_PICKED_UP"
                title = "NHAN HANG THANH CONG"
            command.status = CommandStatus.COMPLETED.value
            await add_audit(
                session,
                action=action_name,
                entity_type="order",
                entity_id=order.id,
                detail={"device_id": device_id, "box": box},
            )
            await session.commit()
            self.mqtt.show_ui(
                device_id,
                {"screen": "message", "title": title, "message": "Cam on ban", "success": True},
            )
