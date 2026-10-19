from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CommandPurpose,
    CommandStatus,
    DeviceCommand,
)
from app.mqtt.service import MqttService
from app.services.common import add_audit


async def publish_unlock(
    session: AsyncSession,
    mqtt: MqttService,
    *,
    device_id: str,
    box: int,
    purpose: CommandPurpose,
    order_id: str | None,
    actor_id: str | None,
    reason: str | None = None,
) -> DeviceCommand:
    request_id = f"req_{uuid4().hex}"
    command = DeviceCommand(
        request_id=request_id,
        device_id=device_id,
        box=box,
        purpose=purpose.value,
        order_id=order_id,
        status=CommandStatus.CREATED.value,
    )
    session.add(command)
    await add_audit(
        session,
        action="UNLOCK_REQUESTED",
        entity_type="device_command",
        entity_id=request_id,
        actor_id=actor_id,
        detail={
            "device_id": device_id,
            "box": box,
            "purpose": purpose.value,
            "reason": reason,
        },
    )
    await session.commit()

    try:
        mqtt.unlock(device_id, box, request_id=request_id)
    except RuntimeError as exc:
        command.status = CommandStatus.FAILED.value
        command.error = str(exc)
        await session.commit()
        raise

    command.status = CommandStatus.PUBLISHED.value
    await session.commit()
    return command


async def mark_command_ack(
    session: AsyncSession, request_id: str, success: bool, error: str | None
) -> DeviceCommand | None:
    from sqlalchemy import select

    command = await session.scalar(
        select(DeviceCommand).where(DeviceCommand.request_id == request_id)
    )
    if command is None:
        return None
    command.status = (
        CommandStatus.ACKNOWLEDGED.value if success else CommandStatus.FAILED.value
    )
    command.error = error
    command.acknowledged_at = datetime.now(UTC)
    await session.commit()
    return command
