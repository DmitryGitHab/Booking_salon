import asyncio
import uuid

from redis.asyncio import Redis

# Снимаем лок только если он всё ещё наш (сверяем токен) — иначе можно случайно
# снять чужой лок, если наш успел истечь по TTL, пока мы были заняты транзакцией.
_RELEASE_IF_OWNER_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class RedisLock:
    """
    Реализация DistributedLock для стратегии BOOKING_LOCK_STRATEGY=redis.

    Блокирует ключ booking-lock:slot:{id} на время критической секции
    (чтение слота -> проверка бизнес-правил -> запись брони), чтобы второй
    параллельный запрос не тратил транзакцию впустую, а сразу подождал своей
    очереди. DB constraint при этом остаётся последней линией защиты.
    """

    def __init__(
        self,
        redis_client: Redis,
        key: str | None = None,
        lock_ttl_seconds: float = 10.0,
        retry_delay_seconds: float = 0.05,
        max_wait_seconds: float = 5.0,
    ):
        self._redis = redis_client
        self._key = key
        self._lock_ttl_seconds = lock_ttl_seconds
        self._retry_delay_seconds = retry_delay_seconds
        self._max_wait_seconds = max_wait_seconds
        self._token: str | None = None

    def __call__(self, key: str) -> "RedisLock":
        return RedisLock(
            self._redis,
            key=key,
            lock_ttl_seconds=self._lock_ttl_seconds,
            retry_delay_seconds=self._retry_delay_seconds,
            max_wait_seconds=self._max_wait_seconds,
        )

    async def __aenter__(self) -> None:
        assert self._key is not None, "RedisLock должен быть вызван как lock(key), а не lock напрямую"
        self._token = str(uuid.uuid4())
        loop = asyncio.get_event_loop()
        deadline = loop.time() + self._max_wait_seconds

        while True:
            acquired = await self._redis.set(
                self._key, self._token, nx=True, px=int(self._lock_ttl_seconds * 1000)
            )
            if acquired:
                return None
            if loop.time() > deadline:
                raise TimeoutError(f"Не удалось получить лок {self._key} за {self._max_wait_seconds}s")
            await asyncio.sleep(self._retry_delay_seconds)

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._token is None or self._key is None:
            return
        await self._redis.eval(_RELEASE_IF_OWNER_LUA, 1, self._key, self._token)
