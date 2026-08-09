import pytest
from httpx import AsyncClient


async def register_user(client: AsyncClient, email: str, password: str = "password123", role: str = "client"):
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "full_name": "Test User", "role": role},
    )
    return response


async def test_register_and_login(client: AsyncClient):
    response = await register_user(client, "client@example.com")
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["role"] == "client"
    assert "access_token" in body

    login_response = await client.post(
        "/api/auth/login", json={"email": "client@example.com", "password": "password123"}
    )
    assert login_response.status_code == 200


async def test_cannot_register_as_master_directly(client: AsyncClient):
    """Роль master нельзя получить через публичную регистрацию — только через админа."""
    response = await register_user(client, "sneaky@example.com", role="master")
    assert response.status_code == 201
    assert response.json()["user"]["role"] == "client"


async def test_duplicate_email_rejected(client: AsyncClient):
    await register_user(client, "dup@example.com")
    response = await register_user(client, "dup@example.com")
    assert response.status_code == 409


async def test_admin_can_create_master_and_master_manages_own_services(client: AsyncClient, db_session):
    # Заводим админа напрямую в БД (в реальности — сид/менеджмент-команда)
    from app.core.security import hash_password
    from app.domain.enums import UserRole
    from app.infrastructure.db.models import User

    admin = User(
        email="admin@example.com",
        hashed_password=hash_password("adminpass123"),
        full_name="Admin",
        role=UserRole.ADMIN,
    )
    db_session.add(admin)
    await db_session.commit()

    admin_login = await client.post("/api/auth/login", json={"email": "admin@example.com", "password": "adminpass123"})
    admin_token = admin_login.json()["access_token"]

    create_master_resp = await client.post(
        "/api/admin/masters",
        json={
            "email": "master@example.com",
            "full_name": "Мастер Мастеров",
            "temporary_password": "masterpass123",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_master_resp.status_code == 201
    master_id = create_master_resp.json()["id"]

    master_login = await client.post(
        "/api/auth/login", json={"email": "master@example.com", "password": "masterpass123"}
    )
    master_token = master_login.json()["access_token"]

    service_resp = await client.post(
        f"/api/masters/{master_id}/services",
        json={"name": "Стрижка", "duration_minutes": 60, "price": "1500.00"},
        headers={"Authorization": f"Bearer {master_token}"},
    )
    assert service_resp.status_code == 201

    slot_resp = await client.post(
        f"/api/masters/{master_id}/slots",
        json={"start_time": "2026-09-01T10:00:00", "end_time": "2026-09-01T11:00:00"},
        headers={"Authorization": f"Bearer {master_token}"},
    )
    assert slot_resp.status_code == 201

    slots_resp = await client.get(f"/api/masters/{master_id}/slots")
    assert slots_resp.status_code == 200
    assert len(slots_resp.json()) == 1


async def test_other_master_cannot_edit_foreign_profile(client: AsyncClient, db_session):
    from app.core.security import hash_password
    from app.domain.enums import UserRole
    from app.infrastructure.db.models import MasterProfile, User

    owner = User(email="owner@example.com", hashed_password=hash_password("pass12345"), full_name="Owner", role=UserRole.MASTER)
    intruder = User(email="intruder@example.com", hashed_password=hash_password("pass12345"), full_name="Intruder", role=UserRole.MASTER)
    db_session.add_all([owner, intruder])
    await db_session.flush()
    profile = MasterProfile(user_id=owner.id)
    db_session.add(profile)
    await db_session.commit()

    login = await client.post("/api/auth/login", json={"email": "intruder@example.com", "password": "pass12345"})
    token = login.json()["access_token"]

    resp = await client.post(
        f"/api/masters/{profile.id}/services",
        json={"name": "Хак", "duration_minutes": 30, "price": "1.00"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
