from app.mqtt.models import CommandRecord
from app.mqtt.registry import DeviceRegistry


def test_registry_tracks_box_status_and_heartbeat() -> None:
    registry = DeviceRegistry()
    registry.update_boxes(
        "SB-001",
        {
            "device_id": "SB-001",
            "timestamp": 1_729_148_400,
            "boxes": [
                {"box": 0, "occupied": False, "door_closed": True},
                {"box": 1, "occupied": True, "door_closed": False},
            ],
        },
    )
    registry.update_heartbeat(
        "SB-001",
        {
            "device_id": "SB-001",
            "uptime_s": 100,
            "wifi_rssi": -45,
            "free_heap": 120_000,
            "timestamp": 1_729_148_400,
        },
    )

    state = registry.get_device("SB-001")
    assert state.online is True
    assert state.boxes[1].occupied is True
    assert state.boxes[1].door_closed is False
    assert state.heartbeat is not None
    assert state.heartbeat.wifi_rssi == -45


def test_registry_correlates_command_result() -> None:
    registry = DeviceRegistry()
    registry.add_command(
        CommandRecord(
            request_id="req_123",
            device_id="SB-001",
            command="unlock",
            payload={"box": 2, "request_id": "req_123"},
        )
    )
    registry.acknowledge_command(
        "req_123",
        True,
        {"box": 2, "request_id": "req_123", "success": True},
    )

    command = registry.get_command("req_123")
    assert command is not None
    assert command.status == "acknowledged"
    assert command.response is not None
    assert command.response["box"] == 2


def test_last_will_marks_device_offline() -> None:
    registry = DeviceRegistry()
    registry.set_availability("SB-001", True)
    assert registry.get_device("SB-001").online is True

    registry.set_availability("SB-001", False)
    assert registry.get_device("SB-001").online is False
