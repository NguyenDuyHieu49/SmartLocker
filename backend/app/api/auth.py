from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.dependencies import CurrentUser, SessionDep
from app.models import User, UserRole
from app.schemas import AuthResponse, LoginRequest, RegisterRequest, UserView
from app.security import (
    create_access_token,
    hash_password,
    normalize_phone,
    verify_password,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(body: RegisterRequest, session: SessionDep) -> AuthResponse:
    try:
        phone = normalize_phone(body.phone)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid_phone") from exc
    role = body.role.upper()
    if role not in {UserRole.SHIPPER.value, UserRole.CUSTOMER.value}:
        raise HTTPException(status_code=422, detail="invalid_role")
    if await session.scalar(select(User).where(User.phone == phone)):
        raise HTTPException(status_code=409, detail="phone_already_registered")
    user = User(
        phone=phone,
        name=body.name.strip(),
        password_hash=hash_password(body.password),
        role=role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return AuthResponse(
        access_token=create_access_token(user.id), user=UserView.model_validate(user)
    )


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, session: SessionDep) -> AuthResponse:
    try:
        phone = normalize_phone(body.phone)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid_credentials") from exc
    user = await session.scalar(select(User).where(User.phone == phone))
    if (
        user is None
        or not user.is_active
        or not verify_password(body.password, user.password_hash)
    ):
        raise HTTPException(status_code=401, detail="invalid_credentials")
    return AuthResponse(
        access_token=create_access_token(user.id), user=UserView.model_validate(user)
    )


@router.get("/me", response_model=UserView)
async def me(user: CurrentUser) -> UserView:
    return UserView.model_validate(user)
