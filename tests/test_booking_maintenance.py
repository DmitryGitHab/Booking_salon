import functools
from datetime import datetime, timedelta
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.application.booking_maintenance import ExpireStaleBookingsUseCase
from app.core.security import hash_password
from app.domain.enums import UserRole
from app.infrastructure.db.models import Booking as BookingModel
from app.infrastructure.db.models import User
from app.infrastructure.repositories.sqlalchemy_uow import sqlalchemy_uow_factory
from tests.conftest import FakeNotificationDispatcher


async def test_expire_stale_bookings_releases_slot_and_notifies(
    client: AsyncClient, db_session, test_engine: AsyncEngine
):
    admin = User(
        email="admin@example.com",
        hashed_password=hash_password("adminpass123"),
        full_name="Admin",
        role=UserRole.ADMIN,
    )
    db_session.add(admin)
    await db_session.commit()
    admin_token = (
        await client.post("/api/auth/login", json={"email": "admin@example.com", "password": "adminpass123"})
    ).json()["access_token"]

    master = (
        await client.post(
            "/api/admin/masters",
            json={"email": "master@example.com", "full_name": "Мастер", "temporary_password": "masterpass123"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()
    master_token = (
        await client.post("/api/auth/login", json={"email": "master@example.com", "password": "masterpass123"})
    ).json()["access_token"]

    service_id = (
        await client.post(
            f"/api/masters/{master['id']}/services",
            json={"name": "Стрижка", "duration_minutes": 60, "price": "1500.00"},
            headers={"Authorization": f"Bearer {master_token}"},
        )
    ).json()["id"]
    slot_id = (
        await client.post(
            f"/api/masters/{master['id']}/slots",
            json={"start_time": "2026-09-01T10:00:00", "end_time": "2026-09-01T11:00:00"},
            headers={"Authorization": f"Bearer {master_token}"},
        )
    ).json()["id"]

    client_token = (
        await client.post(
            "/api/auth/register",
            json={
                "email": "client@example.com",
                "password": "password123",
                "full_name": "Клиент",
                "phone": "+79990000000",
            },
        )
    ).json()["access_token"]

    booking = (
        await client.post(
            "/api/bookings",
            json={"slot_id": slot_id, "service_id": service_id},
            headers={"Authorization": f"Bearer {client_token}"},
        )
    ).json()

    # Искусственно "состариваем" бронь — как будто клиент так и не оплатил вовремя.
    past = datetime.utcnow() - timedelta(minutes=1)
    await db_session.execute(
        update(BookingModel).where(BookingModel.id == UUID(booking["id"])).values(expires_at=past)
    )
    await db_session.commit()

    # Вызываем use case напрямую — именно это делает периодическая Celery-задача
    # bookings.expire_stale (см. app/workers/tasks.py) каждую минуту.
    session_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    dispatcher = FakeNotificationDispatcher()
    use_case = ExpireStaleBookingsUseCase(
        uow_factory=functools.partial(sqlalchemy_uow_factory, session_maker=session_maker),
        notification_dispatcher=dispatcher,
    )
    expired_count = await use_case.execute()

    assert expired_count == 1
    assert len(dispatcher.sent) == 1
    phone, message = dispatcher.sent[0]
    assert phone == "+79990000000"
    assert "истекло" in message.lower()

    bookings = (
        await client.get("/api/bookings/me", headers={"Authorization": f"Bearer {client_token}"})
    ).json()
    assert bookings[0]["status"] == "expired"

    slots = (await client.get(f"/api/masters/{master['id']}/slots")).json()
    assert len(slots) == 1


async def test_expire_stale_bookings_ignores_fresh_bookings(client: AsyncClient, db_session, test_engine):
    """Бронь с expires_at в будущем не должна затрагиваться."""
    admin = User(
        email="admin2@example.com",
        hashed_password=hash_password("adminpass123"),
        full_name="Admin",
        role=UserRole.ADMIN,
    )
    db_session.add(admin)
    await db_session.commit()
    admin_token = (
        await client.post("/api/auth/login", json={"email": "admin2@example.com", "password": "adminpass123"})
    ).json()["access_token"]

    master = (
        await client.post(
            "/api/admin/masters",
            json={"email": "master2@example.com", "full_name": "Мастер", "temporary_password": "masterpass123"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()
    master_token = (
        await client.post("/api/auth/login", json={"email": "master2@example.com", "password": "masterpass123"})
    ).json()["access_token"]

    service_id = (
        await client.post(
            f"/api/masters/{master['id']}/services",
            json={"name": "Стрижка", "duration_minutes": 60, "price": "1500.00"},
            headers={"Authorization": f"Bearer {master_token}"},
        )
    ).json()["id"]
    slot_id = (
        await client.post(
            f"/api/masters/{master['id']}/slots",
            json={"start_time": "2026-09-01T10:00:00", "end_time": "2026-09-01T11:00:00"},
            headers={"Authorization": f"Bearer {master_token}"},
        )
    ).json()["id"]
    client_token = (
        await client.post(
            "/api/auth/register",
            json={"email": "client2@example.com", "password": "password123", "full_name": "Клиент"},
        )
    ).json()["access_token"]

    await client.post(
        "/api/bookings",
        json={"slot_id": slot_id, "service_id": service_id},
        headers={"Authorization": f"Bearer {client_token}"},
    )

    session_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    dispatcher = FakeNotificationDispatcher()
    use_case = ExpireStaleBookingsUseCase(
        uow_factory=functools.partial(sqlalchemy_uow_factory, session_maker=session_maker),
        notification_dispatcher=dispatcher,
    )
    expired_count = await use_case.execute()

    assert expired_count == 0
    assert dispatcher.sent == []
