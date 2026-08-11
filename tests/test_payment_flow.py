import json
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.api.deps import get_payment_gateway, get_stripe_webhook_verifier
from app.application.interfaces import PaymentIntentResult
from app.main import app


@dataclass
class FakePaymentGateway:
    """Fake вместо реального Stripe — детерминированные id, отслеживаем вызовы refund."""

    created_intents: list[str] = field(default_factory=list)
    refunded_intents: list[str] = field(default_factory=list)

    async def create_payment_intent(self, *, amount: Decimal, currency: str, metadata: dict) -> PaymentIntentResult:
        intent_id = f"pi_fake_{uuid4().hex[:12]}"
        self.created_intents.append(intent_id)
        return PaymentIntentResult(intent_id=intent_id, client_secret=f"{intent_id}_secret")

    async def refund(self, *, payment_intent_id: str) -> None:
        self.refunded_intents.append(payment_intent_id)


def _fake_webhook_verifier(payload: bytes, sig_header: str):
    """Заменяет реальную проверку подписи Stripe — просто парсит JSON тела запроса."""
    return json.loads(payload)


@pytest.fixture
def fake_payment_gateway():
    gateway = FakePaymentGateway()
    app.dependency_overrides[get_payment_gateway] = lambda: gateway
    app.dependency_overrides[get_stripe_webhook_verifier] = lambda: _fake_webhook_verifier
    yield gateway
    del app.dependency_overrides[get_payment_gateway]
    del app.dependency_overrides[get_stripe_webhook_verifier]


async def _make_admin_token(client: AsyncClient, db_session) -> str:
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
    resp = await client.post("/api/auth/login", json={"email": "admin@example.com", "password": "adminpass123"})
    return resp.json()["access_token"]


async def _setup_booking(client: AsyncClient, db_session) -> tuple[str, dict]:
    """Создаёт мастера/услугу/слот/клиента и одну бронь. Возвращает (client_token, booking)."""
    admin_token = await _make_admin_token(client, db_session)

    master = (
        await client.post(
            "/api/admin/masters",
            json={"email": "master@example.com", "full_name": "Мастер", "temporary_password": "masterpass123"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()
    master_login = await client.post(
        "/api/auth/login", json={"email": "master@example.com", "password": "masterpass123"}
    )
    master_token = master_login.json()["access_token"]

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

    client_register = await client.post(
        "/api/auth/register",
        json={"email": "client@example.com", "password": "password123", "full_name": "Клиент"},
    )
    client_token = client_register.json()["access_token"]

    booking = (
        await client.post(
            "/api/bookings",
            json={"slot_id": slot_id, "service_id": service_id},
            headers={"Authorization": f"Bearer {client_token}"},
        )
    ).json()

    return client_token, booking, master["id"]


def _webhook_body(event_type: str, intent_id: str) -> dict:
    return {"type": event_type, "data": {"object": {"id": intent_id}}}


async def test_payment_success_confirms_booking(client: AsyncClient, db_session, fake_payment_gateway):
    client_token, booking, _ = await _setup_booking(client, db_session)

    pay_resp = await client.post(
        f"/api/bookings/{booking['id']}/pay", headers={"Authorization": f"Bearer {client_token}"}
    )
    assert pay_resp.status_code == 200
    intent_id = pay_resp.json()["payment_intent_id"]
    assert intent_id in fake_payment_gateway.created_intents

    webhook_resp = await client.post(
        "/api/webhooks/stripe",
        json=_webhook_body("payment_intent.succeeded", intent_id),
        headers={"stripe-signature": "irrelevant-in-tests"},
    )
    assert webhook_resp.status_code == 200

    bookings = (
        await client.get("/api/bookings/me", headers={"Authorization": f"Bearer {client_token}"})
    ).json()
    assert bookings[0]["status"] == "confirmed"


async def test_payment_retry_limit_expires_booking_and_frees_slot(
    client: AsyncClient, db_session, fake_payment_gateway
):
    client_token, booking, master_id = await _setup_booking(client, db_session)

    # PAYMENT_RETRY_ATTEMPTS по умолчанию = 3: 3 цикла pay -> fail
    for attempt in range(1, 4):
        pay_resp = await client.post(
            f"/api/bookings/{booking['id']}/pay", headers={"Authorization": f"Bearer {client_token}"}
        )
        assert pay_resp.status_code == 200, f"попытка {attempt}"
        intent_id = pay_resp.json()["payment_intent_id"]

        webhook_resp = await client.post(
            "/api/webhooks/stripe",
            json=_webhook_body("payment_intent.payment_failed", intent_id),
            headers={"stripe-signature": "irrelevant-in-tests"},
        )
        assert webhook_resp.status_code == 200

    bookings = (
        await client.get("/api/bookings/me", headers={"Authorization": f"Bearer {client_token}"})
    ).json()
    assert bookings[0]["status"] == "expired"

    # Слот должен вернуться в свободные
    slots = (await client.get(f"/api/masters/{master_id}/slots")).json()
    assert len(slots) == 1

    # Четвёртая попытка оплаты — бронь уже не PENDING_PAYMENT
    retry_resp = await client.post(
        f"/api/bookings/{booking['id']}/pay", headers={"Authorization": f"Bearer {client_token}"}
    )
    assert retry_resp.status_code == 400


async def test_cancel_confirmed_booking_triggers_refund(client: AsyncClient, db_session, fake_payment_gateway):
    client_token, booking, master_id = await _setup_booking(client, db_session)

    pay_resp = await client.post(
        f"/api/bookings/{booking['id']}/pay", headers={"Authorization": f"Bearer {client_token}"}
    )
    intent_id = pay_resp.json()["payment_intent_id"]

    await client.post(
        "/api/webhooks/stripe",
        json=_webhook_body("payment_intent.succeeded", intent_id),
        headers={"stripe-signature": "irrelevant-in-tests"},
    )

    cancel_resp = await client.post(
        f"/api/bookings/{booking['id']}/cancel", headers={"Authorization": f"Bearer {client_token}"}
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"
    assert intent_id in fake_payment_gateway.refunded_intents

    slots = (await client.get(f"/api/masters/{master_id}/slots")).json()
    assert len(slots) == 1


async def test_cancel_unpaid_booking_does_not_trigger_refund(client: AsyncClient, db_session, fake_payment_gateway):
    client_token, booking, _ = await _setup_booking(client, db_session)

    cancel_resp = await client.post(
        f"/api/bookings/{booking['id']}/cancel", headers={"Authorization": f"Bearer {client_token}"}
    )
    assert cancel_resp.status_code == 200
    assert fake_payment_gateway.refunded_intents == []
