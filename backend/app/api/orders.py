import secrets
import time
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.dependencies import CurrentUser, SessionDep, require_roles
from app.models import (
    CommandPurpose,
    CommandStatus,
    Compartment,
    CompartmentStatus,
    DeviceCommand,
    LockerStation,
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
    User,
    UserRole,
)
from app.mqtt.service import MqttService
from app.payments import PaymentGateway
from app.schemas import (
    CreateOrderRequest,
    CreatePaymentResponse,
    OrderView,
    PickupQuote,
    PickupRequest,
)
from app.security import (
    code_digest,
    derive_numeric_code,
    generate_numeric_code,
    normalize_phone,
    verify_code,
)
from app.services.commands import publish_unlock
from app.services.common import add_audit, calculate_fee, order_view
from app.services.device_events import DeviceEventProcessor
from app.services.payment_service import create_or_get_payment, mark_payment_paid

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])
settings = get_settings()
ShipperOrAdmin = Annotated[
    User, Depends(require_roles(UserRole.SHIPPER, UserRole.ADMIN))
]


def _mqtt(request: Request) -> MqttService:
    return cast(MqttService, request.app.state.mqtt)


def _gateway(request: Request) -> PaymentGateway:
    return cast(PaymentGateway, request.app.state.payment_gateway)


async def _load_order(session: AsyncSession, order_code: str) -> Order:
    order = await session.scalar(select(Order).where(Order.order_code == order_code))
    if order is None:
        raise HTTPException(status_code=404, detail="order_not_found")
    return order


def _ensure_access(user: User, order: Order) -> None:
    if user.role == UserRole.ADMIN.value:
        return
    if user.role == UserRole.SHIPPER.value and order.shipper_id == user.id:
        return
    if user.role == UserRole.CUSTOMER.value and order.recipient_phone == user.phone:
        return
    raise HTTPException(status_code=403, detail="forbidden")


@router.post("", response_model=OrderView, status_code=201)
async def create_order(
    body: CreateOrderRequest,
    request: Request,
    session: SessionDep,
    user: ShipperOrAdmin,
) -> OrderView:
    del request
    try:
        recipient_phone = normalize_phone(body.recipient_phone)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid_recipient_phone") from exc
    station = await session.scalar(
        select(LockerStation).where(
            LockerStation.device_id == body.station_device_id,
            LockerStation.is_active.is_(True),
        )
    )
    if station is None:
        raise HTTPException(status_code=404, detail="station_not_found")
    compartment = await session.scalar(
        select(Compartment)
        .where(
            Compartment.station_id == station.id,
            Compartment.status == CompartmentStatus.AVAILABLE.value,
            Compartment.number < 4,
            Compartment.size == "S",
        )
        .order_by(Compartment.number)
        .limit(1)
    )
    if compartment is None:
        raise HTTPException(status_code=409, detail="no_available_compartment")

    order_code = f"{secrets.randbelow(100_000_000):08d}"
    deposit_code = generate_numeric_code(6)
    pickup_otp = derive_numeric_code(order_code, "pickup", length=8)
    order = Order(
        order_code=order_code,
        shipper_id=user.id,
        recipient_phone=recipient_phone,
        recipient_name=body.recipient_name.strip(),
        compartment_id=compartment.id,
        status=OrderStatus.RESERVED.value,
        deposit_code_digest=code_digest(deposit_code),
        pickup_otp_digest=code_digest(pickup_otp),
        demo_pickup_otp=None,
        base_fee_vnd=settings.base_fee_vnd,
        grace_minutes=settings.grace_minutes,
        billing_unit_minutes=settings.billing_unit_minutes,
        unit_fee_vnd=settings.unit_fee_vnd,
    )
    compartment.status = CompartmentStatus.RESERVED.value
    session.add(order)
    # SQLAlchemy applies the UUID default during flush. The audit row requires
    # the generated order id, so persist pending values before building it.
    await session.flush()
    await add_audit(
        session,
        action="ORDER_CREATED",
        entity_type="order",
        entity_id=order.id,
        actor_id=user.id,
        detail={"device_id": station.device_id, "box": compartment.number},
    )
    await session.commit()
    await session.refresh(order)
    return await order_view(
        session,
        order,
        deposit_code=deposit_code,
        reveal_pickup_otp=False,
    )


@router.get("", response_model=list[OrderView])
async def list_orders(session: SessionDep, user: CurrentUser) -> list[OrderView]:
    query = select(Order).order_by(Order.created_at.desc())
    if user.role == UserRole.SHIPPER.value:
        query = query.where(Order.shipper_id == user.id)
    elif user.role == UserRole.CUSTOMER.value:
        query = query.where(Order.recipient_phone == user.phone)
    orders = list((await session.scalars(query)).all())
    return [
        await order_view(
            session,
            order,
            reveal_pickup_otp=user.role
            in {UserRole.CUSTOMER.value, UserRole.ADMIN.value},
        )
        for order in orders
    ]


@router.get("/{order_code}", response_model=OrderView)
async def get_order(
    order_code: str, session: SessionDep, user: CurrentUser
) -> OrderView:
    order = await _load_order(session, order_code)
    _ensure_access(user, order)
    return await order_view(
        session,
        order,
        reveal_pickup_otp=user.role in {UserRole.CUSTOMER.value, UserRole.ADMIN.value},
    )


@router.post("/{order_code}/deposit/authorize", status_code=202)
async def authorize_deposit(
    order_code: str,
    request: Request,
    session: SessionDep,
    user: ShipperOrAdmin,
) -> dict[str, str]:
    order = await _load_order(session, order_code)
    if user.role != UserRole.ADMIN.value and order.shipper_id != user.id:
        raise HTTPException(status_code=403, detail="forbidden")
    if order.status != OrderStatus.RESERVED.value:
        raise HTTPException(status_code=409, detail="invalid_order_state")
    compartment = await session.get(Compartment, order.compartment_id)
    if compartment is None:
        raise HTTPException(status_code=500, detail="compartment_not_found")
    station = await session.get(LockerStation, compartment.station_id)
    if station is None:
        raise HTTPException(status_code=500, detail="station_not_found")
    command = await publish_unlock(
        session,
        _mqtt(request),
        device_id=station.device_id,
        box=compartment.number,
        purpose=CommandPurpose.DEPOSIT,
        order_id=order.id,
        actor_id=user.id,
    )
    return {"request_id": command.request_id, "status": command.status}


@router.post("/{order_code}/deposit/simulate-close")
async def simulate_deposit_close(
    order_code: str,
    request: Request,
    session: SessionDep,
    user: ShipperOrAdmin,
) -> dict[str, bool]:
    if not settings.allow_door_simulation:
        raise HTTPException(status_code=404, detail="door_simulation_disabled")

    order = await _load_order(session, order_code)
    if user.role != UserRole.ADMIN.value and order.shipper_id != user.id:
        raise HTTPException(status_code=403, detail="forbidden")
    if order.status == OrderStatus.STORED.value:
        return {"success": True}
    if order.status not in {
        OrderStatus.RESERVED.value,
        OrderStatus.DEPOSIT_AUTHORIZED.value,
        OrderStatus.DEPOSIT_OPEN.value,
    }:
        raise HTTPException(status_code=409, detail="invalid_order_state")

    compartment = await session.get(Compartment, order.compartment_id)
    station = (
        await session.get(LockerStation, compartment.station_id)
        if compartment
        else None
    )
    if compartment is None or station is None:
        raise HTTPException(status_code=500, detail="locker_mapping_missing")

    command = await session.scalar(
        select(DeviceCommand)
        .where(
            DeviceCommand.order_id == order.id,
            DeviceCommand.purpose == CommandPurpose.DEPOSIT.value,
            DeviceCommand.status.in_(
                [
                    CommandStatus.PUBLISHED.value,
                    CommandStatus.ACKNOWLEDGED.value,
                ]
            ),
        )
        .order_by(DeviceCommand.created_at.desc())
    )
    if command is None:
        raise HTTPException(status_code=409, detail="open_compartment_first")

    processor = cast(
        DeviceEventProcessor, request.app.state.device_event_processor
    )
    if command.status == CommandStatus.PUBLISHED.value:
        await processor.handle(
            station.device_id,
            "unlock_result",
            {
                "box": compartment.number,
                "request_id": command.request_id,
                "success": True,
                "error": None,
            },
        )
    simulated_at = int(time.time())
    await processor.handle(
        station.device_id,
        "door",
        {
            "box": compartment.number,
            "door_closed": False,
            "timestamp": simulated_at,
        },
    )
    await processor.handle(
        station.device_id,
        "door",
        {
            "box": compartment.number,
            "door_closed": True,
            "timestamp": simulated_at + 1,
        },
    )
    await processor.handle(
        station.device_id,
        "confirm_finish",
        {
            "action": "deposit_confirmed",
            "box": compartment.number,
            "timestamp": simulated_at + 2,
        },
    )
    await add_audit(
        session,
        action="DOOR_CLOSE_SIMULATED",
        entity_type="order",
        entity_id=order.id,
        actor_id=user.id,
        detail={"device_id": station.device_id, "box": compartment.number},
    )
    await session.commit()
    return {"success": True}


@router.get("/{order_code}/pickup-quote", response_model=PickupQuote)
async def pickup_quote(
    order_code: str, session: SessionDep, user: CurrentUser
) -> PickupQuote:
    order = await _load_order(session, order_code)
    _ensure_access(user, order)
    if order.status not in {
        OrderStatus.STORED.value,
        OrderStatus.PAYMENT_PENDING.value,
        OrderStatus.PAID.value,
    }:
        raise HTTPException(status_code=409, detail="order_not_ready_for_pickup")
    return PickupQuote(
        order_code=order.order_code,
        fee_vnd=max(0, calculate_fee(order) - order.base_fee_vnd),
        stored_at=order.stored_at,
        status=order.status,
    )


@router.post("/{order_code}/payments", response_model=CreatePaymentResponse)
async def create_payment(
    order_code: str,
    request: Request,
    session: SessionDep,
    user: CurrentUser,
) -> CreatePaymentResponse:
    order = await _load_order(session, order_code)
    _ensure_access(user, order)
    if order.status not in {
        OrderStatus.STORED.value,
        OrderStatus.PAYMENT_PENDING.value,
    }:
        raise HTTPException(status_code=409, detail="payment_not_allowed")
    surcharge = max(0, calculate_fee(order) - order.base_fee_vnd)
    if surcharge == 0:
        raise HTTPException(status_code=409, detail="no_payment_required")
    try:
        payment, provider = await create_or_get_payment(
            session,
            _gateway(request),
            order,
            actor_id=user.id,
            amount_vnd=surcharge,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="payment_provider_error") from exc
    return CreatePaymentResponse(
        provider=provider,
        order_code=order.order_code,
        payos_order_code=payment.payos_order_code,
        amount_vnd=payment.amount_vnd,
        status=payment.status,
        checkout_url=payment.checkout_url or "",
        qr_code=payment.qr_code or "",
    )


@router.post("/{order_code}/pickup", status_code=status.HTTP_202_ACCEPTED)
async def pickup(
    order_code: str,
    body: PickupRequest,
    request: Request,
    session: SessionDep,
    user: CurrentUser,
) -> dict[str, str]:
    order = await _load_order(session, order_code)
    _ensure_access(user, order)
    if order.status not in {OrderStatus.STORED.value, OrderStatus.PAID.value}:
        raise HTTPException(status_code=409, detail="payment_required")
    if (
        order.status == OrderStatus.STORED.value
        and calculate_fee(order) - order.base_fee_vnd > 0
    ):
        raise HTTPException(status_code=409, detail="payment_required")
    if order.pickup_otp_attempts >= 5:
        raise HTTPException(status_code=423, detail="otp_locked")
    if not verify_code(body.otp, order.pickup_otp_digest):
        order.pickup_otp_attempts += 1
        await session.commit()
        raise HTTPException(status_code=401, detail="invalid_otp")
    compartment = await session.get(Compartment, order.compartment_id)
    station = (
        await session.get(LockerStation, compartment.station_id)
        if compartment
        else None
    )
    if compartment is None or station is None:
        raise HTTPException(status_code=500, detail="locker_mapping_missing")
    command = await publish_unlock(
        session,
        _mqtt(request),
        device_id=station.device_id,
        box=compartment.number,
        purpose=CommandPurpose.PICKUP,
        order_id=order.id,
        actor_id=user.id,
    )
    return {"request_id": command.request_id, "status": command.status}


@router.post("/{order_code}/payments/mock-confirm")
async def mock_confirm_payment(
    order_code: str,
    request: Request,
    session: SessionDep,
    user: CurrentUser,
) -> dict[str, bool]:
    if not settings.demo_mode or settings.effective_payment_provider != "mock":
        raise HTTPException(status_code=404, detail="not_found")
    order = await _load_order(session, order_code)
    _ensure_access(user, order)
    payment = await session.scalar(
        select(Payment)
        .where(
            Payment.order_id == order.id,
            Payment.status == PaymentStatus.PENDING.value,
        )
        .order_by(Payment.created_at.desc())
    )
    if payment is None:
        raise HTTPException(status_code=404, detail="payment_not_found")
    is_deposit_payment = order.stored_at is None
    changed = await mark_payment_paid(
        session, payment, order, reference=f"MOCK-{payment.payos_order_code}"
    )
    compartment = await session.get(Compartment, order.compartment_id)
    station = (
        await session.get(LockerStation, compartment.station_id)
        if compartment
        else None
    )
    if station is not None and compartment is not None:
        try:
            payload: dict[str, object]
            if is_deposit_payment:
                payload = {
                    "screen": "result",
                    "otp": derive_numeric_code(order.order_code, "pickup", length=8),
                    "box": compartment.number,
                }
            else:
                payload = {
                    "screen": "door_guide",
                    "mode": "pickup",
                    "box": compartment.number,
                }
            _mqtt(request).show_ui(station.device_id, payload)
        except RuntimeError:
            pass
    return {"success": True, "changed": changed}
