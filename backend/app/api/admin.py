import json
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.dependencies import SessionDep, require_roles
from app.models import AuditLog, User, UserRole

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


@router.get("/audit-logs")
async def audit_logs(
    session: SessionDep,
    user: AdminUser,
) -> list[dict[str, object]]:
    del user
    logs = list(
        (
            await session.scalars(
                select(AuditLog).order_by(AuditLog.created_at.desc()).limit(200)
            )
        ).all()
    )
    return [
        {
            "id": item.id,
            "actor_id": item.actor_id,
            "action": item.action,
            "entity_type": item.entity_type,
            "entity_id": item.entity_id,
            "detail": json.loads(item.detail_json),
            "created_at": item.created_at,
        }
        for item in logs
    ]
