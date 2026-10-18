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
from app.schemas import LockerBoxView, LockerStatusView, ManualUnlockRequest
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
