from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import get_notification_dispatcher
from app.infrastructure.db import models  # noqa: F401 — регистрирует модели в metadata
from app.infrastructure.db.base import Base, get_db_session
from app.main import app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


class FakeNotificationDispatcher:
    """
    Подменяет CeleryNotificationDispatcher в тестах: реальный полез бы в Redis
    (которого в тестовом окружении нет) через send_sms_task.delay(). Здесь просто
    копим (phone, message) в списке — при желании тест может проверить отправленные
    уведомления через client.app.dependency_overrides[get_notification_dispatcher].
    """

    def __init__(self):
        self.sent: list[tuple[str | None, str]] = []

    def dispatch_sms(self, *, phone, message):
        self.sent.append((phone, message))


@pytest_asyncio.fixture
async def test_engine() -> AsyncGenerator[AsyncEngine, None]:
    # StaticPool — все сессии с этим engine работают через одно и то же соединение,
    # иначе каждое новое соединение к in-memory SQLite видело бы пустую БД.
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    session_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session


@pytest_asyncio.fixture
async def client(
    test_engine: AsyncEngine, db_session: AsyncSession, monkeypatch
) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    # CreateBookingUseCase/CancelBookingUseCase открывают СВОЮ сессию через
    # sqlalchemy_uow_factory (каждый вызов use case = своя транзакция), а не
    # через get_db_session. Подменяем и её источник на тот же тестовый engine,
    # иначе бронирования ушли бы в боевой sqlite-файл вместо тестовой БД.
    test_session_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(
        "app.infrastructure.repositories.sqlalchemy_uow.async_session_maker",
        test_session_maker,
    )

    # Use case-ы шлют уведомления через NotificationDispatcher.dispatch_sms(), а
    # реальная реализация (CeleryNotificationDispatcher) полезла бы в Redis. Подменяем
    # на fake по умолчанию для всех тестов — Redis в тестовом окружении не поднят.
    app.dependency_overrides[get_notification_dispatcher] = FakeNotificationDispatcher

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
