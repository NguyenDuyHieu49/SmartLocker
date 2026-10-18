from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SmartLocker Device API"
    environment: str = "development"

    database_url: str = "sqlite+aiosqlite:///./smartlocker.db"
    jwt_secret: str = "change-this-before-production"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 720
    otp_pepper: str = "change-this-before-production"
    demo_mode: bool = True
    allow_door_simulation: bool = False
    bootstrap_admin_phone: str = "0900000000"
    bootstrap_admin_password: str = "Admin@12345"

    dashboard_url: str = "https://smartbox.id.vn"
    api_url: str = "https://api.smartbox.id.vn"
    cors_origins: str = (
        "http://localhost:3000,https://app.smartbox.id.vn,https://smartbox.id.vn"
    )

    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_tls: bool = False
    mqtt_tls_insecure: bool = False
    mqtt_client_id: str = "smartlocker-backend"
    mqtt_keepalive: int = 60

    device_offline_after_seconds: int = 20
    command_timeout_seconds: int = 15

    payment_provider: Literal["mock", "momo_sandbox", "payos"] = "mock"
    payos_enabled: bool = False
    payos_client_id: str | None = None
    payos_api_key: str | None = None
    payos_checksum_key: str | None = None
    payos_confirm_webhook_on_startup: bool = False
    momo_base_url: str = "https://test-payment.momo.vn"
    momo_partner_code: str | None = None
    momo_access_key: str | None = None
    momo_secret_key: str | None = None
    momo_timeout_seconds: float = 30.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_production(self) -> "Settings":
        if self.environment != "production":
            return self
        errors: list[str] = []
        if len(self.jwt_secret) < 32 or self.jwt_secret.startswith("change-"):
            errors.append("JWT_SECRET must contain at least 32 random characters")
        if len(self.otp_pepper) < 32 or self.otp_pepper.startswith("change-"):
            errors.append("OTP_PEPPER must contain at least 32 random characters")
        if self.bootstrap_admin_password == "Admin@12345":
            errors.append("BOOTSTRAP_ADMIN_PASSWORD must be changed")
        if self.demo_mode:
            errors.append("DEMO_MODE must be false")
        database_url = self.database_url.strip().lower()
        if not database_url or database_url.startswith("sqlite"):
            errors.append("DATABASE_URL must use a persistent production database")
        provider = self.effective_payment_provider
        if provider == "mock":
            errors.append("PAYMENT_PROVIDER must not be mock in production")
        if provider == "payos" and not all(
            [self.payos_client_id, self.payos_api_key, self.payos_checksum_key]
        ):
            errors.append("payOS credentials are required")
        if provider == "momo_sandbox" and not all(
            [self.momo_partner_code, self.momo_access_key, self.momo_secret_key]
        ):
            errors.append("MoMo sandbox credentials are required")
        if not self.mqtt_tls or self.mqtt_tls_insecure:
            errors.append("MQTT TLS verification must be enabled")
        if errors:
            raise ValueError("; ".join(errors))
        return self

    @property
    def effective_payment_provider(self) -> str:
        # Keep compatibility with deployments that still set PAYOS_ENABLED=true.
        if self.payos_enabled:
            return "payos"
        return self.payment_provider

    @property
    def allowed_origins(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value]

    @property
    def async_database_url(self) -> str:
        url = self.database_url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        else:
            return url

        # Neon emits libpq parameters. SQLAlchemy forwards query parameters to
        # asyncpg, which expects `ssl` and does not accept `sslmode` or
        # `channel_binding`.
        parsed = urlsplit(url)
        query: list[tuple[str, str]] = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            if key == "sslmode":
                query.append(("ssl", value))
            elif key != "channel_binding":
                query.append((key, value))
        return urlunsplit(parsed._replace(query=urlencode(query)))


@lru_cache
def get_settings() -> Settings:
    return Settings()
