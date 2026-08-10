"""
Ключевой тест проекта: имитирует 50 пользователей, одновременно жмущих
"забронировать" на один и тот же слот. Ожидаемый результат в обоих режимах
защиты — ровно 1 успешная бронь и 49 корректных BookingConflictError.

Требует установленный и запущенный Docker (testcontainers сам поднимет
контейнеры Postgres/Redis и погасит их после теста). Если Docker недоступен —
тест аккуратно скипается, а не падает, чтобы не ломать обычный `pytest -v`
на машинах без Docker.

Запуск отдельно:
    pytest tests/test_concurrency.py -v -s
"""
import asyncio
import functools
from datetime import datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.application.booking import CreateBookingUseCase
from app.core.security import hash_password
from app.domain.enums import UserRole
from app.domain.exceptions import BookingConflictError, SlotAlreadyTakenError
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import MasterProfile, Service, Slot, User
from app.infrastructure.locks.null_lock import NullLock
from app.infrastructure.repositories.sqlalchemy_uow import sqlalchemy_uow_factory

CONCURRENT_REQUESTS = 50


def _docker_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _docker_available(), reason="Docker недоступен в этом окружении — тест на конкурентность пропущен"
)


@pytest_asyncio.fixture(scope="module")
async def postgres_session_maker():
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as postgres:
        async_url = postgres.get_connection_url().replace("psycopg2", "asyncpg")
        engine = create_async_engine(async_url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield session_maker
        await engine.dispose()


@pytest_asyncio.fixture
async def redis_client():
    from redis.asyncio import Redis
    from testcontainers.redis import RedisContainer

    with RedisContainer("redis:7-alpine") as redis_container:
        client = Redis(
            host=redis_container.get_container_host_ip(),
            port=int(redis_container.get_exposed_port(6379)),
            decode_responses=True,
        )
        yield client
        await client.aclose()


async def _seed_master_service_slot(session_maker):
    """Создаёт одного мастера, одну услугу и один слот. Возвращает их id."""
    async with session_maker() as session:
        master_user = User(
            email=f"master-{uuid4()}@example.com",
            hashed_password=hash_password("password123"),
            full_name="Мастер",
            role=UserRole.MASTER,
        )
        session.add(master_user)
        await session.flush()

        profile = MasterProfile(user_id=master_user.id)
        session.add(profile)
        await session.flush()

        service = Service(master_id=profile.id, name="Стрижка", duration_minutes=60, price=1500)
        slot = Slot(
            master_id=profile.id,
            start_time=datetime(2026, 9, 1, 10, 0, 0),
            end_time=datetime(2026, 9, 1, 11, 0, 0),
        )
        session.add_all([service, slot])
        await session.commit()

        return profile.id, service.id, slot.id


async def _seed_clients(session_maker, count: int) -> list:
    async with session_maker() as session:
        clients = [
            User(
                email=f"client-{i}-{uuid4()}@example.com",
                hashed_password=hash_password("password123"),
                full_name=f"Клиент {i}",
                role=UserRole.CLIENT,
            )
            for i in range(count)
        ]
        session.add_all(clients)
        await session.commit()
        return [c.id for c in clients]


async def _run_concurrent_bookings(session_maker, lock, slot_id, service_id, client_ids):
    """Запускает N параллельных попыток забронировать один и тот же слот."""
    use_case = CreateBookingUseCase(
        uow_factory=functools.partial(sqlalchemy_uow_factory, session_maker=session_maker),
        lock=lock,
        unpaid_ttl_minutes=15,
    )

    async def attempt(client_id):
        try:
            await use_case.execute(client_id=client_id, slot_id=slot_id, service_id=service_id)
            return "success"
        except (BookingConflictError, SlotAlreadyTakenError):
            return "conflict"

    results = await asyncio.gather(*(attempt(cid) for cid in client_ids))
    return results


async def test_concurrent_booking_db_strategy(postgres_session_maker):
    """Стратегия 'db': FOR UPDATE + unique constraint, без Redis-лока."""
    _, service_id, slot_id = await _seed_master_service_slot(postgres_session_maker)
    client_ids = await _seed_clients(postgres_session_maker, CONCURRENT_REQUESTS)

    results = await _run_concurrent_bookings(
        postgres_session_maker, NullLock(), slot_id, service_id, client_ids
    )

    successes = results.count("success")
    conflicts = results.count("conflict")
    print(f"\n[db strategy] {CONCURRENT_REQUESTS} параллельных запросов -> "
          f"{successes} успех, {conflicts} корректных конфликтов")

    assert successes == 1
    assert conflicts == CONCURRENT_REQUESTS - 1


async def test_concurrent_booking_redis_strategy(postgres_session_maker, redis_client):
    """Стратегия 'redis': распределённый лок на ключ слота перед транзакцией."""
    from app.infrastructure.locks.redis_lock import RedisLock

    _, service_id, slot_id = await _seed_master_service_slot(postgres_session_maker)
    client_ids = await _seed_clients(postgres_session_maker, CONCURRENT_REQUESTS)

    results = await _run_concurrent_bookings(
        postgres_session_maker, RedisLock(redis_client), slot_id, service_id, client_ids
    )

    successes = results.count("success")
    conflicts = results.count("conflict")
    print(f"\n[redis strategy] {CONCURRENT_REQUESTS} параллельных запросов -> "
          f"{successes} успех, {conflicts} корректных конфликтов")

    assert successes == 1
    assert conflicts == CONCURRENT_REQUESTS - 1
