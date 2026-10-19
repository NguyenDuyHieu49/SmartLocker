import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

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
from app.db import SessionFactory
from app.mqtt.registry import DeviceRegistry
from app.mqtt.service import MqttService
from app.payments import PayOSGateway, create_payment_gateway
from app.services.device_events import DeviceEventProcessor
from app.services.payment_service import (
    cancel_expired_pending_payments,
    mark_overdue_orders,
)

logger = logging.getLogger(__name__)


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
        try:
            await asyncio.to_thread(payment_gateway.confirm_webhook)
        except Exception:
            # Webhook registration depends on an external service and must not make
            # the locker API unavailable during a transient payOS/DNS failure.
            logger.exception("payOS webhook confirmation failed")
    processor = DeviceEventProcessor(mqtt, payment_gateway, asyncio.get_running_loop())

    def on_device_event(device_id: str, event_name: str, payload: dict[str, Any]) -> None:
        print(f"[MQTT EVENT] device='{device_id}' event='{event_name}' payload={payload}", flush=True)
        logger.info("[MQTT EVENT] device='%s' event='%s' payload=%s", device_id, event_name, payload)
        processor.submit(device_id, event_name, payload)

    mqtt.set_event_handler(on_device_event)
    app.state.mqtt = mqtt
    app.state.device_event_processor = processor
    app.state.payment_gateway = payment_gateway
    mqtt.start()

    async def _payment_expiry_loop(interval_seconds: int = 30) -> None:
        while True:
            try:
                await asyncio.sleep(interval_seconds)
                async with SessionFactory() as session:
                    await cancel_expired_pending_payments(session, max_age_minutes=15)
                    await mark_overdue_orders(session)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error during payment expiry background check")

    expiry_task = asyncio.create_task(_payment_expiry_loop())
    try:
        yield
    finally:
        expiry_task.cancel()
        try:
            await expiry_task
        except asyncio.CancelledError:
            pass
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
