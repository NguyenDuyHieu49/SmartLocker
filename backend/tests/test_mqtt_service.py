from unittest.mock import MagicMock

from app.core.config import Settings
from app.mqtt.registry import DeviceRegistry
from app.mqtt.service import MqttService


def make_service() -> MqttService:
    service = MqttService(Settings(), DeviceRegistry())
    result = MagicMock()
    result.rc = 0
    service.client.publish = MagicMock(return_value=result)  # type: ignore[method-assign]
    return service


def test_unlock_publishes_api_spec_payload() -> None:
    service = make_service()
    request_id, topic = service.unlock("SB-001", 2)

    assert topic == "smartbox/SB-001/cmd/unlock"
    assert request_id.startswith("req_")
    args = service.client.publish.call_args.args
    kwargs = service.client.publish.call_args.kwargs
    assert args[0] == topic
    assert f'"request_id":"{request_id}"' in args[1]
    assert '"box":2' in args[1]
    assert kwargs == {"qos": 1, "retain": False}


def test_request_status_uses_empty_payload_and_qos_zero() -> None:
    service = make_service()
    request_id, topic = service.request_status("SB-001")

    assert request_id == ""
    assert topic == "smartbox/SB-001/cmd/request_status"
    args = service.client.publish.call_args.args
    kwargs = service.client.publish.call_args.kwargs
    assert args[1] == "{}"
    assert kwargs == {"qos": 0, "retain": False}
