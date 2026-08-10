from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_name: str = "Booking API"
    debug: bool = True

    # Database
    database_url: str = "sqlite+aiosqlite:///./booking.db"

    # Redis (нужен только для booking_lock_strategy=redis)
    redis_url: str = "redis://localhost:6379/0"

    # Защита от двойного бронирования: "db" — только уникальный constraint + FOR UPDATE,
    # "redis" — дополнительно распределённый лок на ключ слота перед транзакцией.
    booking_lock_strategy: str = "db"

    # JWT
    jwt_secret: str = "CHANGE_ME_IN_PRODUCTION"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24  # 24 hours

    # Stripe (test mode)
    stripe_secret_key: str = "sk_test_dummy"
    stripe_webhook_secret: str = "whsec_dummy"

    # Booking rules
    unpaid_booking_ttl_minutes: int = 15  # автоотмена неоплаченной брони
    payment_retry_attempts: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()
