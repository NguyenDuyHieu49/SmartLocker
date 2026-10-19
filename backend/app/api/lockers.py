from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from app.dependencies import CurrentUser, SessionDep, require_roles
from app.models import (
    CommandPurpose,
    Compartment,
    LockerStation,
    Order,
    OrderStatus,
    User,
    UserRole,
)
from app.mqtt.service import MqttService
from app.schemas import (
    CompartmentConfigView,
    LockerBoxView,
    LockerStatusView,
    ManualUnlockRequest,
    UpdateCompartmentConfigRequest,
)
from app.services.commands import publish_unlock

router = APIRouter(prefix="/api/v1/lockers", tags=["lockers"])
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


def _mqtt(request: Request) -> MqttService:
    return cast(MqttService, request.app.state.mqtt)


@router.get("/{device_id}/status", response_model=LockerStatusView)
async def locker_status(
    device_id: str, request: Request, session: SessionDep, user: CurrentUser
) -> LockerStatusView:
    del user
    station = await session.scalar(
        select(LockerStation).where(LockerStation.device_id == device_id)
    )
    if station is None:
        raise HTTPException(status_code=404, detail="station_not_found")
    compartments = list(
        (
            await session.scalars(
                select(Compartment)
                .where(Compartment.station_id == station.id)
                .order_by(Compartment.number)
            )
        ).all()
    )
    physical = _mqtt(request).registry.get_device(device_id)
    physical_by_box = {item.box: item for item in physical.boxes}
    active_statuses = {
        status.value
        for status in OrderStatus
        if status not in {OrderStatus.COMPLETED, OrderStatus.CANCELLED}
    }
    active_orders = list(
        (
            await session.scalars(
                select(Order)
                .where(
                    Order.compartment_id.in_([item.id for item in compartments]),
                    Order.status.in_(active_statuses),
                )
                .order_by(Order.created_at.desc())
            )
        ).all()
    )
    order_by_compartment: dict[str, Order] = {}
    for active_order in active_orders:
        order_by_compartment.setdefault(active_order.compartment_id, active_order)
    boxes: list[LockerBoxView] = []
    for item in compartments:
        physical_box = physical_by_box.get(item.number)
        order = order_by_compartment.get(item.id)
        if item.size == "TECH":
            operational_status = "TECH"
        elif physical_box is None:
            operational_status = "PHYSICAL_UNKNOWN"
        elif not physical_box.door_closed:
            operational_status = (
                order.status
                if order is not None
                and order.status
                in {OrderStatus.DEPOSIT_OPEN.value, OrderStatus.PICKUP_OPEN.value}
                else "DOOR_OPEN"
            )
        elif order is not None:
            operational_status = order.status
        else:
            operational_status = item.status
        boxes.append(
            LockerBoxView(
                box=item.number,
                size=item.size,
                business_status=item.status,
                operational_status=operational_status,
                occupied=item.status == "OCCUPIED",
                door_closed=physical_box.door_closed if physical_box else None,
                order_code=order.order_code if order else None,
                order_status=order.status if order else None,
                stored_at=order.stored_at if order else None,
                daily_rate_vnd=(
                    item.overdue_price_per_day if item.number < 4 else None
                ),
            )
        )
    return LockerStatusView(
        device_id=device_id,
        online=physical.online,
        boxes=boxes,
    )


@router.post("/{device_id}/manual-unlock", status_code=202)
async def manual_unlock(
    device_id: str,
    body: ManualUnlockRequest,
    request: Request,
    session: SessionDep,
    user: AdminUser,
) -> dict[str, str]:
    command = await publish_unlock(
        session,
        _mqtt(request),
        device_id=device_id,
        box=body.box,
        purpose=CommandPurpose.ADMIN,
        order_id=None,
        actor_id=user.id,
        reason=body.reason,
    )
    return {"request_id": command.request_id, "status": command.status}


@router.get(
    "/{device_id}/compartments/config", response_model=list[CompartmentConfigView]
)
async def get_compartment_configs(
    device_id: str,
    session: SessionDep,
    user: CurrentUser,
) -> list[CompartmentConfigView]:
    del user
    station = await session.scalar(
        select(LockerStation).where(LockerStation.device_id == device_id)
    )
    if station is None:
        raise HTTPException(status_code=404, detail="station_not_found")
    compartments = list(
        (
            await session.scalars(
                select(Compartment)
                .where(Compartment.station_id == station.id)
                .order_by(Compartment.number)
            )
        ).all()
    )
    return [CompartmentConfigView.model_validate(c) for c in compartments]


@router.put(
    "/{device_id}/compartments/{box}/config", response_model=CompartmentConfigView
)
async def update_compartment_config(
    device_id: str,
    box: int,
    body: UpdateCompartmentConfigRequest,
    request: Request,
    session: SessionDep,
    user: AdminUser,
) -> CompartmentConfigView:
    del user
    station = await session.scalar(
        select(LockerStation).where(LockerStation.device_id == device_id)
    )
    if station is None:
        raise HTTPException(status_code=404, detail="station_not_found")
    compartment = await session.scalar(
        select(Compartment).where(
            Compartment.station_id == station.id, Compartment.number == box
        )
    )
    if compartment is None:
        raise HTTPException(status_code=404, detail="compartment_not_found")

    if body.size is not None:
        compartment.size = body.size
    if body.dimensions is not None:
        compartment.dimensions = body.dimensions
    if body.base_price is not None:
        compartment.base_price = body.base_price
    if body.overdue_price_per_day is not None:
        compartment.overdue_price_per_day = body.overdue_price_per_day
    if body.max_overdue_days is not None:
        compartment.max_overdue_days = body.max_overdue_days

    await session.commit()
    await session.refresh(compartment)

    # Sync to ESP32 via MQTT cmd/config
    sync_payload = {
        "box": compartment.number,
        "size": compartment.size,
        "dimensions": compartment.dimensions,
        "base_price": compartment.base_price,
        "overdue_price_per_day": compartment.overdue_price_per_day,
        "max_overdue_days": compartment.max_overdue_days,
    }
    try:
        _mqtt(request).sync_config(device_id, sync_payload)
    except RuntimeError:
        pass

    return CompartmentConfigView.model_validate(compartment)

