import json
import logging
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from paho.mqtt.client import (
    MQTT_ERR_SUCCESS,
    Client,
    ConnectFlags,
    DisconnectFlags,
    MQTTMessage,
    MQTTv311,
)
from paho.mqtt.enums import CallbackAPIVersion
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode

from app.core.config import Settings
from app.mqtt.models import CommandRecord
from app.mqtt.registry import DeviceRegistry

logger = logging.getLogger(__name__)


class MqttService:
    def __init__(self, settings: Settings, registry: DeviceRegistry) -> None:
        self.settings = settings
        self.registry = registry
        self.client = Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=settings.mqtt_client_id,
            protocol=MQTTv311,
        )
        if settings.mqtt_username:
            self.client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        if settings.mqtt_tls:
            self.client.tls_set()
            self.client.tls_insecure_set(settings.mqtt_tls_insecure)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self._started = False
        self._event_handler: Callable[[str, str, dict[str, Any]], None] | None = None

    def set_event_handler(
        self, handler: Callable[[str, str, dict[str, Any]], None]
    ) -> None:
        self._event_handler = handler

    def start(self) -> None:
        if self._started:
            return
        self.client.connect_async(
            self.settings.mqtt_host,
            self.settings.mqtt_port,
            self.settings.mqtt_keepalive,
        )
        self.client.loop_start()
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self.client.disconnect()
        self.client.loop_stop()
        self._started = False

    def _on_connect(
        self,
        client: Client,
        userdata: Any,
        flags: ConnectFlags,
        reason_code: ReasonCode,
        properties: Properties | None,
    ) -> None:
        del userdata, flags, properties
        if reason_code.is_failure:
            logger.error("MQTT connection failed: %s", reason_code)
            return
        logger.info("Connected to MQTT broker")
        client.subscribe("smartbox/+/status/boxes", qos=0)
        client.subscribe("smartbox/+/status/heartbeat", qos=0)
        client.subscribe("smartbox/+/status/availability", qos=1)
        client.subscribe("smartbox/+/evt/+", qos=1)

    def _on_disconnect(
        self,
        client: Client,
        userdata: Any,
        disconnect_flags: DisconnectFlags,
        reason_code: ReasonCode,
        properties: Properties | None,
    ) -> None:
        del client, userdata, disconnect_flags, properties
        if reason_code.is_failure:
            logger.warning("Unexpected MQTT disconnect: %s", reason_code)

    def _on_message(self, client: Client, userdata: Any, message: MQTTMessage) -> None:
        del client, userdata
        parts = message.topic.split("/")
        if len(parts) != 4 or parts[0] != "smartbox":
            logger.warning("Ignoring unknown topic: %s", message.topic)
            return

        device_id, category, event_name = parts[1], parts[2], parts[3]
        try:
            raw = message.payload.decode("utf-8")
            if category == "status" and event_name == "availability":
                self.registry.set_availability(device_id, raw == "online")
                return
            payload = json.loads(raw)
            self._ingest(device_id, category, event_name, payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("Invalid MQTT payload on %s: %s", message.topic, exc)

    def _ingest(
        self,
        device_id: str,
        category: str,
        event_name: str,
        payload: dict[str, Any],
    ) -> None:
        if category == "status" and event_name == "boxes":
            self.registry.update_boxes(device_id, payload)
            self._notify(device_id, "boxes", payload)
            return
        if category == "status" and event_name == "heartbeat":
            self.registry.update_heartbeat(device_id, payload)
            self._notify(device_id, "heartbeat", payload)
            return

        if category != "evt":
            return
        self.registry.append_event(device_id, event_name, payload)
        request_id = payload.get("request_id")
        if request_id and event_name.endswith("result"):
            self.registry.acknowledge_command(
                request_id, bool(payload.get("success")), payload
            )
        elif request_id and event_name == "reboot_ack":
            self.registry.acknowledge_command(request_id, True, payload)
        self._notify(device_id, event_name, payload)

    def _notify(self, device_id: str, event_name: str, payload: dict[str, Any]) -> None:
        if self._event_handler is not None:
            self._event_handler(device_id, event_name, payload)

    def _publish_command(
        self, device_id: str, command: str, payload: dict[str, Any], qos: int
    ) -> tuple[str, str]:
        topic = f"smartbox/{device_id}/cmd/{command}"
        request_id = payload.get("request_id", "")
        info = self.client.publish(
            topic,
            json.dumps(payload, separators=(",", ":")),
            qos=qos,
            retain=False,
        )
        if info.rc != MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT publish failed with code {info.rc}")
        if request_id:
            self.registry.add_command(
                CommandRecord(
                    request_id=request_id,
                    device_id=device_id,
                    command=command,
                    payload=payload,
                )
            )
        return request_id, topic

    def unlock(
        self, device_id: str, box: int, request_id: str | None = None
    ) -> tuple[str, str]:
        request_id = request_id or f"req_{uuid4().hex}"
        return self._publish_command(
            device_id,
            "unlock",
            {"box": box, "request_id": request_id},
            qos=1,
        )

    def set_box(
        self,
        device_id: str,
        box: int,
        occupied: bool,
        request_id: str | None = None,
    ) -> tuple[str, str]:
        request_id = request_id or f"req_{uuid4().hex}"
        return self._publish_command(
            device_id,
            "set_box",
            {"box": box, "occupied": occupied, "request_id": request_id},
            qos=1,
        )

    def reboot(self, device_id: str) -> tuple[str, str]:
        request_id = f"req_{uuid4().hex}"
        return self._publish_command(
            device_id,
            "reboot",
            {"request_id": request_id},
            qos=1,
        )

    def request_status(self, device_id: str) -> tuple[str, str]:
        return self._publish_command(device_id, "request_status", {}, qos=0)

    def show_ui(self, device_id: str, payload: dict[str, Any]) -> tuple[str, str]:
        return self._publish_command(device_id, "ui", payload, qos=1)
