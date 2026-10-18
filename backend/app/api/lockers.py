from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from app.dependencies import CurrentUser, SessionDep, require_roles
from app.models import (
    CommandPurpose,
    Compartment,
    LockerStation,
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
    boxes: list[LockerBoxView] = []
    for item in compartments:
        physical_box = physical_by_box.get(item.number)
        boxes.append(
            LockerBoxView(
                box=item.number,
                business_status=item.status,
                occupied=item.status == "OCCUPIED",
                door_closed=physical_box.door_closed if physical_box else None,
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
