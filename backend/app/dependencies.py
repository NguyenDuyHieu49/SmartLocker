from collections.abc import Awaitable, Callable
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import User, UserRole
from app.security import decode_access_token

bearer = HTTPBearer(auto_error=False)
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="not_authenticated"
        )
    try:
        user_id = decode_access_token(credentials.credentials)
    except (ValueError, jwt.PyJWTError) as exc:
        raise HTTPException(status_code=401, detail="invalid_token") from exc
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="invalid_user")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[[User], Awaitable[User]]:
    async def dependency(user: CurrentUser) -> User:
        if user.role not in {role.value for role in roles}:
            raise HTTPException(status_code=403, detail="forbidden")
        return user

    return dependency
