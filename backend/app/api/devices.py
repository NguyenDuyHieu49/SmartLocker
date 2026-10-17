from collections.abc import Callable
from typing import TypeVar, cast

from fastapi import APIRouter, HTTPException, Request, status

from app.mqtt.models import (
    CommandAccepted,
    CommandRecord,
    DeviceState,
    SetBoxCommand,
    UnlockCommand,
)
from app.mqtt.service import MqttService

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])
T = TypeVar("T")


def mqtt_service(request: Request) -> MqttService:
    return cast(MqttService, request.app.state.mqtt)


def publish_or_503(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.get("", response_model=list[DeviceState])
def list_devices(request: Request) -> list[DeviceState]:
    return mqtt_service(request).registry.list_devices()


@router.get("/{device_id}", response_model=DeviceState)
def get_device(device_id: str, request: Request) -> DeviceState:
    return mqtt_service(request).registry.get_device(device_id)


@router.get("/commands/{request_id}", response_model=CommandRecord)
def get_command(request_id: str, request: Request) -> CommandRecord:
    command = mqtt_service(request).registry.get_command(request_id)
    if command is None:
        raise HTTPException(status_code=404, detail="command_not_found")
    return command


@router.post(
    "/{device_id}/unlock",
    response_model=CommandAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def unlock(device_id: str, command: UnlockCommand, request: Request) -> CommandAccepted:
    request_id, topic = publish_or_503(
        lambda: mqtt_service(request).unlock(device_id, command.box)
    )
    return CommandAccepted(request_id=request_id, topic=topic)


@router.post(
    "/{device_id}/set-box",
    response_model=CommandAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def set_box(
    device_id: str, command: SetBoxCommand, request: Request
) -> CommandAccepted:
    request_id, topic = publish_or_503(
        lambda: mqtt_service(request).set_box(device_id, command.box, command.occupied)
    )
    return CommandAccepted(request_id=request_id, topic=topic)


@router.post(
    "/{device_id}/reboot",
    response_model=CommandAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def reboot(device_id: str, request: Request) -> CommandAccepted:
    request_id, topic = publish_or_503(lambda: mqtt_service(request).reboot(device_id))
    return CommandAccepted(request_id=request_id, topic=topic)


@router.post(
    "/{device_id}/request-status",
    response_model=CommandAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_status(device_id: str, request: Request) -> CommandAccepted:
    request_id, topic = publish_or_503(
        lambda: mqtt_service(request).request_status(device_id)
    )
    return CommandAccepted(request_id=request_id, topic=topic)
