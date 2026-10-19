import asyncio
import logging
import secrets
from concurrent.futures import Future
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

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
    Payment,
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
from app.services.payment_service import (
    cancel_expired_pending_payments,
    cancel_order_payment,
    create_or_get_payment,
    mark_payment_paid,
)
from app.services.pricing import (
    STORAGE_DAY_MINUTES,
    calculate_deposit_fee,
    pricing_snapshot_for_compartment,
)

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
                try:
                    days = int(payload.get("days", 3))
                except (TypeError, ValueError):
                    days = 3
                await self._deposit_phone(
                    session,
                    device_id,
                    str(payload.get("value", "")),
                    str(payload.get("extra", "")),
                    days,
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
            elif action == "cancel_payment":
                await self._cancel_payment(
                    session,
                    device_id,
                    str(payload.get("value", "")),
                    str(payload.get("extra", "user_cancelled")),
                )
            elif action == "tech_clear_box":
                try:
                    box = int(payload.get("value", -1))
                except (TypeError, ValueError):
                    box = -1
                await self._tech_clear_box(session, device_id, box)
            else:
                self._show_error(device_id, "Yeu cau ban phim khong hop le")

    async def _check_box_availability(
        self, session: AsyncSession, device_id: str, size: str
    ) -> None:
        await cancel_expired_pending_payments(session, max_age_minutes=15)
        size = size.upper()
        if size not in {"S", "M", "L"}:
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
        doors = {box.box: box.door_closed for box in physical.boxes} if physical else {}
        # Ưu tiên chọn ngăn đang đóng cửa; nếu ngăn chưa đóng switch thì vẫn lấy ngăn AVAILABLE trong DB
        available = next(
            (
                compartment
                for compartment in compartments
                if doors.get(compartment.number, False)
            ),
            compartments[0] if compartments else None,
        )
        if available is None:
            self._show_error(device_id, f"Khong con ngan {size}")
            return
        self.mqtt.show_ui(
            device_id,
            {
                "screen": "enter_phone",
                "size": size,
                "available": True,
                "box": available.number,
                "available_box": available.number,
            },
        )

    async def _deposit_phone(
        self,
        session: AsyncSession,
        device_id: str,
        raw_phone: str,
        size: str,
        days: int = 3,
    ) -> None:
        try:
            phone = normalize_phone(raw_phone)
        except ValueError:
            self._show_error(device_id, "So dien thoai khong hop le")
            return
        if len(phone) != 10 or not phone.startswith("0") or size not in {"S", "M", "L"}:
            self._show_error(device_id, "SDT phai bat dau bang 0 va co 10 so")
            return
        if days <= 0:
            days = 3

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

        price_vnd = calculate_deposit_fee(compartment, days)
        recipient = await session.scalar(select(User).where(User.phone == phone))
        order_code = f"{secrets.randbelow(100_000_000):08d}"
        pickup_otp = derive_numeric_code(order_code, "pickup", length=8)
        base_fee, _, billing_unit_minutes, unit_fee = (
            pricing_snapshot_for_compartment(compartment)
        )
        grace_minutes = days * STORAGE_DAY_MINUTES
        order = Order(
            order_code=order_code,
            shipper_id=None,
            recipient_phone=phone,
            recipient_name=recipient.name if recipient else "Khach hang SmartBox",
            compartment_id=compartment.id,
            status=OrderStatus.RESERVED.value,
            deposit_code_digest=code_digest(generate_numeric_code(12)),
            pickup_otp_digest=code_digest(pickup_otp),
            base_fee_vnd=price_vnd,
            grace_minutes=grace_minutes,
            billing_unit_minutes=billing_unit_minutes,
            unit_fee_vnd=unit_fee,
        )
        compartment.status = CompartmentStatus.RESERVED.value
        session.add(order)
        await session.flush()
        await add_audit(
            session,
            action="KIOSK_ORDER_CREATED",
            entity_type="order",
            entity_id=order.id,
            detail={
                "device_id": device_id,
                "box": compartment.number,
                "size": size,
                "days": days,
                "fee": price_vnd,
                "daily_rate_vnd": base_fee,
            },
        )
        await session.commit()
        print(
            f"\n==================== [DEPOSIT CREATED] ====================\n"
            f"Device: {device_id} | Ngăn: #{compartment.number + 1} | Cỡ: {size}\n"
            f"Mã đơn: {order.order_code} | Phí do người nhận thanh toán khi lấy hàng\n"
            f"SĐT nhận: {phone}\n"
            f"==============================================================\n",
            flush=True,
        )

        self.mqtt.show_ui(
            device_id,
            {
                "screen": "result",
                "box": compartment.number,
                "order_code": order.order_code,
                "otp": pickup_otp,
                "payer": "recipient",
            },
        )

    async def _auto_mock_pickup_payment_success(
        self, order_id: str, payment_id: str, device_id: str, box_number: int
    ) -> None:
        await asyncio.sleep(5)
        async with SessionFactory() as session:
            order = await session.get(Order, order_id)
            payment = await session.get(Payment, payment_id)
            if (
                order is None
                or payment is None
                or order.status != OrderStatus.PAYMENT_PENDING.value
            ):
                return
            await mark_payment_paid(session, payment, order, reference="MOCK-AUTO-WEBHOOK")
            self.mqtt.show_ui(
                device_id,
                {
                    "screen": "door_guide",
                    "mode": "pickup",
                    "box": box_number,
                    "auto_open": True,
                },
            )
            try:
                await publish_unlock(
                    session,
                    self.mqtt,
                    device_id=device_id,
                    box=box_number,
                    purpose=CommandPurpose.PICKUP,
                    order_id=order.id,
                    actor_id=None,
                    reason="receiver_mock_payment_confirmed",
                )
            except RuntimeError:
                logger.exception("Mock payment succeeded but pickup unlock failed")

    async def _cancel_payment(
        self, session: AsyncSession, device_id: str, order_code: str, reason: str
    ) -> None:
        order: Order | None = None
        if order_code:
            order = await session.scalar(
                select(Order).where(Order.order_code == order_code)
            )
        if order is None:
            station = await session.scalar(
                select(LockerStation).where(LockerStation.device_id == device_id)
            )
            if station:
                order = await session.scalar(
                    select(Order)
                    .join(Compartment, Order.compartment_id == Compartment.id)
                    .where(
                        Compartment.station_id == station.id,
                        Order.status.in_(
                            [
                                OrderStatus.RESERVED.value,
                                OrderStatus.PAYMENT_PENDING.value,
                            ]
                        ),
                    )
                    .order_by(Order.created_at.desc())
                    .limit(1)
                )
        if order is not None:
            await cancel_order_payment(session, order, reason=reason)
            logger.info("Cancelled payment/order %s (reason=%s)", order.order_code, reason)
            print(
                f"[PAYMENT] -> Giao dịch của đơn {order.order_code} đã hủy ({reason}). "
                "Kiện hàng vẫn được giữ trong tủ.",
                flush=True,
            )

    async def _pickup_otp(
        self, session: AsyncSession, device_id: str, otp: str
    ) -> None:
        if len(otp) != 8 or not otp.isdigit():
            self._show_error(device_id, "OTP phai co 8 chu so")
            return
        overdue_order = await session.scalar(
            select(Order).where(
                Order.pickup_otp_digest == code_digest(otp),
                Order.status == OrderStatus.OVERDUE.value,
            )
        )
        if overdue_order is not None:
            self._show_error(device_id, "Don qua han, vui long lien he CSKH")
            return

        order = await session.scalar(
            select(Order).where(
                Order.pickup_otp_digest == code_digest(otp),
                Order.status.in_(
                    [OrderStatus.STORED.value, OrderStatus.PAYMENT_PENDING.value]
                ),
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
        total_fee = calculate_fee(order)
        try:
            payment, provider = await create_or_get_payment(
                session,
                self.payment_gateway,
                order,
                actor_id=None,
                amount_vnd=total_fee,
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
                "payer": "recipient",
                "purpose": "pickup",
            },
        )
        if provider == "mock":
            asyncio.create_task(
                self._auto_mock_pickup_payment_success(
                    order.id, payment.id, device_id, compartment.number
                )
            )

    async def _open_confirmed(
        self, session: AsyncSession, device_id: str, mode: str, box: int
    ) -> None:
        if mode not in {"deposit", "pickup"} or not 0 <= box < 4:
            self._show_error(device_id, "Xac nhan mo tu khong hop le")
            return
        _, compartment = await find_station_and_box(session, device_id, box)
        allowed_statuses = (
            {
                OrderStatus.RESERVED.value,
                OrderStatus.DEPOSIT_AUTHORIZED.value,
                OrderStatus.DEPOSIT_OPEN.value,
            }
            if mode == "deposit"
            else {
                OrderStatus.PAID.value,
                OrderStatus.PICKUP_AUTHORIZED.value,
                OrderStatus.PICKUP_OPEN.value,
            }
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
        # ESP32 đã tự mở chốt servo vật lý sau khi khách bấm [A] ở hướng dẫn cuối cùng.
        # Backend chỉ cập nhật trạng thái đơn và ghi nhận command history, không gửi cmd/unlock hay reset UI.
        order.status = (
            OrderStatus.DEPOSIT_OPEN.value
            if purpose == CommandPurpose.DEPOSIT
            else OrderStatus.PICKUP_OPEN.value
        )
        command = DeviceCommand(
            request_id=f"local_{uuid4().hex}",
            device_id=device_id,
            box=box,
            purpose=purpose.value,
            status=CommandStatus.ACKNOWLEDGED.value,
            order_id=order.id,
        )
        session.add(command)
        await add_audit(
            session,
            action=f"{purpose.value}_DOOR_OPENED",
            entity_type="order",
            entity_id=order.id,
            detail={"device_id": device_id, "box": box, "mode": mode},
        )
        await session.commit()
        print(
            f"[DOOR OPEN CONFIRMED] Device {device_id} - Ngăn #{box + 1} ({mode}). "
            f"ESP32 đã tự mở chốt servo sau khi nhấn [A] ở hướng dẫn cuối.",
            flush=True,
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
                _, compartment = await find_station_and_box(session, device_id, box)
                allowed = (
                    [
                        OrderStatus.DEPOSIT_OPEN.value,
                        OrderStatus.DEPOSIT_AUTHORIZED.value,
                    ]
                    if expected_purpose == CommandPurpose.DEPOSIT.value
                    else [
                        OrderStatus.PICKUP_OPEN.value,
                        OrderStatus.PICKUP_AUTHORIZED.value,
                        OrderStatus.PAID.value,
                    ]
                )
                order = await session.scalar(
                    select(Order)
                    .where(Order.compartment_id == compartment.id, Order.status.in_(allowed))
                    .order_by(Order.created_at.desc())
                )
                if order is None:
                    self._show_error(device_id, "Khong tim thay lenh mo tu")
                    return
            else:
                order = await session.get(Order, command.order_id)
                _, compartment = await find_station_and_box(session, device_id, box)
            if order is None:
                return
            if expected_purpose == CommandPurpose.DEPOSIT.value:
                order.status = OrderStatus.STORED.value
                order.stored_at = datetime.now(UTC)
                compartment.status = CompartmentStatus.OCCUPIED.value
                action_name = "PACKAGE_STORED"
            else:
                order.status = OrderStatus.COMPLETED.value
                order.completed_at = datetime.now(UTC)
                compartment.status = CompartmentStatus.AVAILABLE.value
                action_name = "PACKAGE_PICKED_UP"
            if command is not None:
                command.status = CommandStatus.COMPLETED.value
            await add_audit(
                session,
                action=action_name,
                entity_type="order",
                entity_id=order.id,
                detail={"device_id": device_id, "box": box},
            )
            await session.commit()
            print(
                f"[{action_name}] Device {device_id} - Ngăn #{box + 1} hoàn tất. Đã lưu trạng thái DB.",
                flush=True,
            )

    async def _tech_clear_box(
        self, session: AsyncSession, device_id: str, box: int
    ) -> None:
        if box < 0 or box >= 4:
            return
        station = await session.scalar(
            select(LockerStation).where(LockerStation.device_id == device_id)
        )
        if station is None:
            return
        compartment = await session.scalar(
            select(Compartment).where(
                Compartment.station_id == station.id, Compartment.number == box
            )
        )
        if compartment is None:
            return
        active_order = await session.scalar(
            select(Order)
            .where(
                Order.compartment_id == compartment.id,
                Order.status.in_(
                    [
                        OrderStatus.STORED.value,
                        OrderStatus.OVERDUE.value,
                        OrderStatus.PICKUP_OPEN.value,
                        OrderStatus.DEPOSIT_OPEN.value,
                        OrderStatus.PAID.value,
                    ]
                ),
            )
            .order_by(Order.created_at.desc())
            .limit(1)
        )
        if active_order is not None:
            active_order.status = OrderStatus.MANUAL_REVIEW.value
            await add_audit(
                session,
                action="TECH_CLEAR_BOX",
                entity_type="order",
                entity_id=active_order.id,
                detail={
                    "device_id": device_id,
                    "box": box,
                    "previous_status": active_order.status,
                    "order_code": active_order.order_code,
                },
            )
        compartment.status = CompartmentStatus.AVAILABLE.value
        await session.commit()
        logger.info(
            "Technician cleared box %s on device %s. Compartment set to AVAILABLE.",
            box,
            device_id,
        )

