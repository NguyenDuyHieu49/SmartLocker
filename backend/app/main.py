import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.devices import router as devices_router
from app.api.lockers import router as lockers_router
from app.api.orders import router as orders_router
from app.api.webhooks import router as webhooks_router
from app.bootstrap import initialize_database
from app.core.config import get_settings
from app.mqtt.registry import DeviceRegistry
from app.mqtt.service import MqttService
from app.payments import PayOSGateway, create_payment_gateway
from app.services.device_events import DeviceEventProcessor


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    await initialize_database(settings)
    registry = DeviceRegistry(settings.device_offline_after_seconds)
    mqtt = MqttService(settings, registry)
    payment_gateway = create_payment_gateway(settings)
    if (
        isinstance(payment_gateway, PayOSGateway)
        and settings.payos_confirm_webhook_on_startup
    ):
        await asyncio.to_thread(payment_gateway.confirm_webhook)
    processor = DeviceEventProcessor(mqtt, payment_gateway, asyncio.get_running_loop())
    mqtt.set_event_handler(processor.submit)
    app.state.mqtt = mqtt
    app.state.payment_gateway = payment_gateway
    mqtt.start()
    try:
        yield
    finally:
        mqtt.stop()


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(orders_router)
app.include_router(lockers_router)
app.include_router(admin_router)
app.include_router(webhooks_router)
app.include_router(devices_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
