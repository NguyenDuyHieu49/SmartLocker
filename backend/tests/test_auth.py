from typing import Any, cast

import pytest
from fastapi import HTTPException

from app.api.auth import login
from app.models import User, UserRole
from app.schemas import LoginRequest
from app.security import hash_password


class UserSession:
    def __init__(self, user: User | None) -> None:
        self.user = user

    async def scalar(self, _statement: object) -> User | None:
        return self.user


@pytest.mark.asyncio
async def test_login_rejects_inactive_user() -> None:
    user = User(
        phone="0912345678",
        name="Inactive user",
        password_hash=hash_password("CorrectPassword123"),
        role=UserRole.CUSTOMER.value,
        is_active=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        await login(
            LoginRequest(phone="0912345678", password="CorrectPassword123"),
            cast(Any, UserSession(user)),
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "invalid_credentials"
