from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class BoxStatus(BaseModel):
    box: int = Field(ge=0, le=4)
    size: Literal["S", "M", "TECH"]
    door_closed: bool


class BoxesStatus(BaseModel):
    device_id: str
    timestamp: int = Field(ge=0)
    boxes: list[BoxStatus]


class Heartbeat(BaseModel):
    device_id: str
    uptime_s: int = Field(ge=0)
    wifi_rssi: int
    free_heap: int = Field(ge=0)
    timestamp: int = Field(ge=0)


class DoorEvent(BaseModel):
    box: int = Field(ge=0, le=4)
    door_closed: bool
    timestamp: int = Field(ge=0)


class UnlockResult(BaseModel):
    box: int = Field(ge=0, le=4)
    request_id: str
    success: bool
    error: str | None = None


class KeypadEvent(BaseModel):
    action: Literal["check_box", "deposit_phone", "pickup_otp", "open_confirmed"]
    value: str
    extra: str = ""


class ConfirmFinishEvent(BaseModel):
    box: int = Field(ge=0, le=4)
    action: Literal["deposit_confirmed", "pickup_confirmed"]
    timestamp: int = Field(ge=0)


class RebootAck(BaseModel):
    request_id: str
    reboot_in_ms: int = Field(ge=0)


class CommandRecord(BaseModel):
    request_id: str
    device_id: str
    command: str
    payload: dict[str, Any]
    status: Literal["published", "acknowledged", "failed"] = "published"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    response: dict[str, Any] | None = None


class DeviceState(BaseModel):
    device_id: str
    mqtt_available: bool | None = None
    online: bool = False
    last_seen_at: datetime | None = None
    boxes: list[BoxStatus] = Field(default_factory=list)
    heartbeat: Heartbeat | None = None
    recent_events: list[dict[str, Any]] = Field(default_factory=list)


class UnlockCommand(BaseModel):
    box: int = Field(ge=0, le=4)


class CommandAccepted(BaseModel):
    request_id: str
    topic: str
    accepted: bool = True
