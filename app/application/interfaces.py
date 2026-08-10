"""
Порты (интерфейсы) application-слоя.

Use case-ы зависят только от этих Protocol-ов, а не от SQLAlchemy напрямую.
Конкретные реализации — в infrastructure/repositories/sqlalchemy_uow.py.
Это позволяет тестировать use case-ы с in-memory фейками, вообще без БД.
"""
from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.domain.entities import Booking, Service, Slot
from app.domain.enums import BookingStatus, SlotStatus


class SlotRepository(Protocol):
    async def get_by_id(self, slot_id: UUID) -> Slot | None: ...
    async def save(self, slot: Slot) -> None: ...
    """Сохраняет изменения статуса слота (UPDATE)."""


class ServiceRepository(Protocol):
    async def get_by_id(self, service_id: UUID) -> Service | None: ...


class BookingRepository(Protocol):
    async def add(self, booking: Booking) -> None: ...
    async def get_by_slot_id(self, slot_id: UUID) -> Booking | None: ...
    async def list_by_client(self, client_id: UUID) -> list[Booking]: ...
    async def get_by_id(self, booking_id: UUID) -> Booking | None: ...
    async def update_status(self, booking_id: UUID, status: BookingStatus) -> None: ...


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

    async def __aenter__(self) -> "UnitOfWork": ...
    async def __aexit__(self, exc_type, exc, tb) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


class DistributedLock(Protocol):
    """Блокировка по строковому ключу на время выполнения критической секции."""

    def __call__(self, key: str) -> "DistributedLock": ...
    async def __aenter__(self) -> None: ...
    async def __aexit__(self, exc_type, exc, tb) -> None: ...
