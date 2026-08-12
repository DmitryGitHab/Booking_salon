"""
Порты (интерфейсы) application-слоя.

Use case-ы зависят только от этих Protocol-ов, а не от SQLAlchemy/Stripe/Celery напрямую.
Конкретные реализации — в infrastructure/. Это позволяет тестировать use case-ы
с in-memory/fake реализациями, вообще без БД, внешних API и брокера очередей.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from app.domain.entities import Booking, Payment, Service, Slot
from app.domain.enums import BookingStatus


class SlotRepository(Protocol):
    async def get_by_id(self, slot_id: UUID) -> Slot | None: ...
    async def save(self, slot: Slot) -> None:
        """Сохраняет изменения статуса слота (UPDATE)."""
        ...


class ServiceRepository(Protocol):
    async def get_by_id(self, service_id: UUID) -> Service | None: ...


class BookingRepository(Protocol):
    async def add(self, booking: Booking) -> None: ...
    async def get_by_slot_id(self, slot_id: UUID) -> Booking | None: ...
    async def list_by_client(self, client_id: UUID) -> list[Booking]: ...
    async def get_by_id(self, booking_id: UUID) -> Booking | None: ...
    async def update_status(self, booking_id: UUID, status: BookingStatus) -> None: ...
    async def list_stale_pending(self, now: datetime) -> list[Booking]:
        """Брони в статусе PENDING_PAYMENT с истёкшим expires_at — кандидаты на автоотмену."""
        ...


class PaymentRepository(Protocol):
    async def add(self, payment: Payment) -> None: ...
    async def update(self, payment: Payment) -> None: ...
    async def get_by_booking_id(self, booking_id: UUID) -> Payment | None: ...
    async def get_by_intent_id(self, intent_id: str) -> Payment | None: ...


@dataclass
class ClientContact:
    """DTO с минимумом данных клиента, нужным для отправки уведомления."""

    id: UUID
    email: str
    phone: str | None
    full_name: str


class UserRepository(Protocol):
    async def get_contact(self, user_id: UUID) -> ClientContact | None: ...


class UnitOfWork(Protocol):
    """
    Группирует репозитории в рамках одной транзакции БД.
    Используется как async context manager:

        async with uow_factory() as uow:
            slot = await uow.slots.get_by_id(slot_id)
            ...
            await uow.commit()
    """

    slots: SlotRepository
    services: ServiceRepository
    bookings: BookingRepository
    payments: PaymentRepository
    users: UserRepository

    async def __aenter__(self) -> "UnitOfWork": ...
    async def __aexit__(self, exc_type, exc, tb) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


class DistributedLock(Protocol):
    """Блокировка по строковому ключу на время выполнения критической секции."""

    def __call__(self, key: str) -> "DistributedLock": ...
    async def __aenter__(self) -> None: ...
    async def __aexit__(self, exc_type, exc, tb) -> None: ...


@dataclass
class PaymentIntentResult:
    """DTO, пересекающий границу порта PaymentGateway — не доменная сущность,
    а данные, специфичные для платёжного провайдера (id намерения, client_secret)."""

    intent_id: str
    client_secret: str


class PaymentGateway(Protocol):
    """Абстракция над платёжным провайдером (в нашем случае — Stripe)."""

    async def create_payment_intent(
        self, *, amount: Decimal, currency: str, metadata: dict
    ) -> PaymentIntentResult: ...

    async def refund(self, *, payment_intent_id: str) -> None: ...


class NotificationDispatcher(Protocol):
    """
    Ставит уведомление в очередь фоновых задач (Celery) — не отправляет само,
    только публикует сообщение в брокер и сразу возвращает управление. Поэтому
    метод синхронный: сетевого ожидания здесь нет, только паблиш в Redis.
    Реальная отправка (сейчас — лог + SMS-заглушка) происходит в Celery-воркере.
    """

    def dispatch_sms(self, *, phone: str | None, message: str) -> None: ...
