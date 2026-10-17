import secrets
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.dependencies import CurrentUser, SessionDep, require_roles
from app.models import (
    CommandPurpose,
    Compartment,
    CompartmentStatus,
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
        )
        .order_by(Compartment.number)
        .limit(1)
    )
    if compartment is None:
        raise HTTPException(status_code=409, detail="no_available_compartment")

    order_code = f"{secrets.randbelow(100_000_000):08d}"
    deposit_code = generate_numeric_code(6)
    pickup_otp = derive_numeric_code(order_code, "pickup")
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
        fee_vnd=calculate_fee(order),
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
    try:
        payment, provider = await create_or_get_payment(
            session, _gateway(request), order, actor_id=user.id
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
    if order.status != OrderStatus.PAID.value:
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
    changed = await mark_payment_paid(
        session, payment, order, reference=f"MOCK-{payment.payos_order_code}"
    )
    compartment = await session.get(Compartment, order.compartment_id)
    station = (
        await session.get(LockerStation, compartment.station_id)
        if compartment
        else None
    )
    if station is not None:
        try:
            _mqtt(request).show_ui(
                station.device_id,
                {"screen": "enter_otp", "order_code": order.order_code},
            )
        except RuntimeError:
            pass
    return {"success": True, "changed": changed}
