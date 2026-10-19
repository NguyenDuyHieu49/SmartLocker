from collections import deque
from datetime import UTC, datetime
from threading import RLock
from typing import Any

from app.mqtt.models import (
    BoxesStatus,
    CommandRecord,
    DeviceState,
    Heartbeat,
)


class DeviceRegistry:
    """Thread-safe in-memory projection of MQTT device state for the MVP."""

    def __init__(self, offline_after_seconds: int = 20) -> None:
        self._offline_after_seconds = offline_after_seconds
        self._devices: dict[str, DeviceState] = {}
        self._commands: dict[str, CommandRecord] = {}
        self._events: dict[str, deque[dict[str, Any]]] = {}
        self._lock = RLock()

    def _device(self, device_id: str) -> DeviceState:
        if device_id not in self._devices:
            self._devices[device_id] = DeviceState(device_id=device_id)
            self._events[device_id] = deque(maxlen=100)
        return self._devices[device_id]

    def touch(self, device_id: str) -> None:
        with self._lock:
            device = self._device(device_id)
            device.last_seen_at = datetime.now(UTC)
            device.online = True

    def set_availability(self, device_id: str, available: bool) -> None:
        with self._lock:
            device = self._device(device_id)
            device.mqtt_available = available
            device.online = available
            if available:
                device.last_seen_at = datetime.now(UTC)

    def update_boxes(self, device_id: str, payload: dict[str, Any]) -> None:
        status = BoxesStatus.model_validate(payload)
        with self._lock:
            device = self._device(device_id)
            device.boxes = status.boxes
            device.last_seen_at = datetime.now(UTC)
            device.online = True

    def update_heartbeat(self, device_id: str, payload: dict[str, Any]) -> None:
        heartbeat = Heartbeat.model_validate(payload)
        with self._lock:
            device = self._device(device_id)
            device.heartbeat = heartbeat
            device.last_seen_at = datetime.now(UTC)
            device.online = True

    def append_event(
        self, device_id: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        with self._lock:
            self.touch(device_id)
            event = {
                "type": event_type,
                "received_at": datetime.now(UTC).isoformat(),
                "payload": payload,
            }
            self._events[device_id].appendleft(event)
            self._devices[device_id].recent_events = list(self._events[device_id])

    def add_command(self, command: CommandRecord) -> None:
        with self._lock:
            self._commands[command.request_id] = command

    def acknowledge_command(
        self, request_id: str, success: bool, response: dict[str, Any]
    ) -> None:
        with self._lock:
            command = self._commands.get(request_id)
            if command is None:
                return
            command.status = "acknowledged" if success else "failed"
            command.response = response

    def get_command(self, request_id: str) -> CommandRecord | None:
        with self._lock:
            command = self._commands.get(request_id)
            return command.model_copy(deep=True) if command else None

    def get_device(self, device_id: str) -> DeviceState:
        with self._lock:
            device = self._device(device_id).model_copy(deep=True)
            if device.last_seen_at is not None:
                age = (datetime.now(UTC) - device.last_seen_at).total_seconds()
                if age > self._offline_after_seconds:
                    device.online = False
            if device.mqtt_available is False:
                device.online = False
            return device

    def list_devices(self) -> list[DeviceState]:
        with self._lock:
            ids = list(self._devices)
        return [self.get_device(device_id) for device_id in ids]
