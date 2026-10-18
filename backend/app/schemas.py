from datetime import datetime

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    phone: str
    name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    role: str = "CUSTOMER"


class LoginRequest(BaseModel):
    phone: str
    password: str


class UserView(BaseModel):
    id: str
    phone: str
    name: str
    role: str

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserView


class CreateOrderRequest(BaseModel):
    recipient_phone: str
    recipient_name: str = Field(min_length=2, max_length=120)
    station_device_id: str = "SB-001"


class OrderView(BaseModel):
    id: str
    order_code: str
    status: str
    recipient_phone: str
    recipient_name: str
    box: int
    station_device_id: str
    stored_at: datetime | None
    paid_at: datetime | None
    completed_at: datetime | None
    fee_vnd: int
    deposit_code: str | None = None
    pickup_otp: str | None = None


class PickupQuote(BaseModel):
    order_code: str
    fee_vnd: int
    stored_at: datetime | None
    status: str


class CreatePaymentResponse(BaseModel):
    provider: str
    order_code: str
    payos_order_code: int
    amount_vnd: int
    status: str
    checkout_url: str
    qr_code: str


class PickupRequest(BaseModel):
    otp: str = Field(min_length=8, max_length=8, pattern=r"^\d{8}$")


class ManualUnlockRequest(BaseModel):
    box: int = Field(ge=0, le=4)
    reason: str = Field(min_length=5, max_length=240)


class LockerBoxView(BaseModel):
    box: int
    business_status: str
    occupied: bool | None = None
    door_closed: bool | None = None


class LockerStatusView(BaseModel):
    device_id: str
    online: bool
    boxes: list[LockerBoxView]
