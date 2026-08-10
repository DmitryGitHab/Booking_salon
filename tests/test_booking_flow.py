from httpx import AsyncClient

from app.core.security import hash_password
from app.domain.enums import UserRole
from app.infrastructure.db.models import User


async def _make_admin_token(client: AsyncClient, db_session) -> str:
    admin = User(
        email="admin@example.com",
        hashed_password=hash_password("adminpass123"),
        full_name="Admin",
        role=UserRole.ADMIN,
    )
    db_session.add(admin)
    await db_session.commit()
    resp = await client.post("/api/auth/login", json={"email": "admin@example.com", "password": "adminpass123"})
    return resp.json()["access_token"]


async def _make_master(client: AsyncClient, admin_token: str, email: str = "master@example.com") -> dict:
    resp = await client.post(
        "/api/admin/masters",
        json={"email": email, "full_name": "Мастер", "temporary_password": "masterpass123"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    return resp.json()


async def _login(client: AsyncClient, email: str, password: str) -> str:
    resp = await client.post("/api/auth/login", json={"email": email, "password": password})
    return resp.json()["access_token"]


async def _register_client(client: AsyncClient, email: str) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "full_name": "Клиент"},
    )
    return resp.json()["access_token"]


async def test_full_booking_happy_path(client: AsyncClient, db_session):
    admin_token = await _make_admin_token(client, db_session)
    master = await _make_master(client, admin_token)
    master_token = await _login(client, "master@example.com", "masterpass123")

    service_resp = await client.post(
        f"/api/masters/{master['id']}/services",
        json={"name": "Стрижка", "duration_minutes": 60, "price": "1500.00"},
        headers={"Authorization": f"Bearer {master_token}"},
    )
    service_id = service_resp.json()["id"]

    slot_resp = await client.post(
        f"/api/masters/{master['id']}/slots",
        json={"start_time": "2026-09-01T10:00:00", "end_time": "2026-09-01T11:00:00"},
        headers={"Authorization": f"Bearer {master_token}"},
    )
    slot_id = slot_resp.json()["id"]

    client_token = await _register_client(client, "client@example.com")

    booking_resp = await client.post(
        "/api/bookings",
        json={"slot_id": slot_id, "service_id": service_id},
        headers={"Authorization": f"Bearer {client_token}"},
    )
    assert booking_resp.status_code == 201
    booking = booking_resp.json()
    assert booking["status"] == "pending_payment"

    slots_resp = await client.get(f"/api/masters/{master['id']}/slots")
    assert slots_resp.json() == []

    cancel_resp = await client.post(
        f"/api/bookings/{booking['id']}/cancel",
        headers={"Authorization": f"Bearer {client_token}"},
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"

    slots_resp_after = await client.get(f"/api/masters/{master['id']}/slots")
    assert len(slots_resp_after.json()) == 1


async def test_double_booking_same_slot_returns_409(client: AsyncClient, db_session):
    admin_token = await _make_admin_token(client, db_session)
    master = await _make_master(client, admin_token)
    master_token = await _login(client, "master@example.com", "masterpass123")

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

    token_a = await _register_client(client, "a@example.com")
    token_b = await _register_client(client, "b@example.com")

    resp_a = await client.post(
        "/api/bookings", json={"slot_id": slot_id, "service_id": service_id},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp_a.status_code == 201

    resp_b = await client.post(
        "/api/bookings", json={"slot_id": slot_id, "service_id": service_id},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp_b.status_code == 409


async def test_cannot_book_slot_shorter_than_service(client: AsyncClient, db_session):
    admin_token = await _make_admin_token(client, db_session)
    master = await _make_master(client, admin_token)
    master_token = await _login(client, "master@example.com", "masterpass123")

    service_id = (
        await client.post(
            f"/api/masters/{master['id']}/services",
            json={"name": "Долгая процедура", "duration_minutes": 90, "price": "3000.00"},
            headers={"Authorization": f"Bearer {master_token}"},
        )
    ).json()["id"]
    slot_id = (
        await client.post(
            f"/api/masters/{master['id']}/slots",
            json={"start_time": "2026-09-01T10:00:00", "end_time": "2026-09-01T10:30:00"},
            headers={"Authorization": f"Bearer {master_token}"},
        )
    ).json()["id"]

    client_token = await _register_client(client, "client2@example.com")
    resp = await client.post(
        "/api/bookings", json={"slot_id": slot_id, "service_id": service_id},
        headers={"Authorization": f"Bearer {client_token}"},
    )
    assert resp.status_code == 400


async def test_cannot_book_foreign_master_service(client: AsyncClient, db_session):
    """Услуга мастера A не должна применяться к слоту мастера B."""
    admin_token = await _make_admin_token(client, db_session)
    master_a = await _make_master(client, admin_token, email="master-a@example.com")
    master_b = await _make_master(client, admin_token, email="master-b@example.com")
    token_a = await _login(client, "master-a@example.com", "masterpass123")
    token_b = await _login(client, "master-b@example.com", "masterpass123")

    service_a = (
        await client.post(
            f"/api/masters/{master_a['id']}/services",
            json={"name": "Услуга A", "duration_minutes": 30, "price": "500.00"},
            headers={"Authorization": f"Bearer {token_a}"},
        )
    ).json()["id"]
    slot_b = (
        await client.post(
            f"/api/masters/{master_b['id']}/slots",
            json={"start_time": "2026-09-01T10:00:00", "end_time": "2026-09-01T11:00:00"},
            headers={"Authorization": f"Bearer {token_b}"},
        )
    ).json()["id"]

    client_token = await _register_client(client, "client3@example.com")
    resp = await client.post(
        "/api/bookings", json={"slot_id": slot_b, "service_id": service_a},
        headers={"Authorization": f"Bearer {client_token}"},
    )
    assert resp.status_code == 400
