from functools import lru_cache

from redis.asyncio import Redis

from app.application.interfaces import DistributedLock
from app.core.config import get_settings
from app.infrastructure.locks.null_lock import NullLock
from app.infrastructure.locks.redis_lock import RedisLock


@lru_cache
def _get_redis_client() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)


def get_lock() -> DistributedLock:
    settings = get_settings()
    if settings.booking_lock_strategy == "redis":
        return RedisLock(_get_redis_client())
    return NullLock()
