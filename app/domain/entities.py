"""
Доменный слой. Здесь живут бизнес-правила.
Никаких импортов из FastAPI, SQLAlchemy и т.д. — только чистый Python.
Это позволяет тестировать бизнес-логику без поднятия БД и веб-сервера.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.domain.enums import BookingStatus, PaymentStatus, SlotStatus
from app.domain.exceptions import (
    InvalidStateTransitionError,
    SlotAlreadyTakenError,
    SlotTooShortForServiceError,
    SlotInThePastError,
)


@dataclass
class Service:
    id: UUID
    master_id: UUID
    name: str
    duration_minutes: int
    price: Decimal
    is_active: bool = True


@dataclass
class Slot:
    """Конкретный интервал времени, который мастер открыл для записи."""

    id: UUID
    master_id: UUID
    start_time: datetime
    end_time: datetime
    status: SlotStatus = SlotStatus.FREE

    @property
    def duration_minutes(self) -> int:
        return int((self.end_time - self.start_time).total_seconds() // 60)

    def ensure_can_be_booked_for(self, service: Service, now: datetime) -> None:
        """Бросает доменное исключение, если слот нельзя забронировать под услугу."""
        if self.start_time <= now:
            raise SlotInThePastError(self.id)
        if self.status != SlotStatus.FREE:
            raise SlotAlreadyTakenError(self.id)
        if self.duration_minutes < service.duration_minutes:
            raise SlotTooShortForServiceError(self.id, service.id)

    def mark_pending_payment(self) -> None:
        self.status = SlotStatus.PENDING_PAYMENT

    def mark_booked(self) -> None:
        self.status = SlotStatus.BOOKED

    def release(self) -> None:
        """Слот снова становится свободным (отмена / истёк таймаут оплаты)."""
        self.status = SlotStatus.FREE


@dataclass
class Booking:
    id: UUID
    client_id: UUID
    slot_id: UUID
    service_id: UUID
    price_at_booking: Decimal
    status: BookingStatus = BookingStatus.PENDING_PAYMENT
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime | None = None

    def confirm(self) -> None:
        if self.status != BookingStatus.PENDING_PAYMENT:
            raise InvalidStateTransitionError(f"Нельзя подтвердить бронь в статусе {self.status}")
        self.status = BookingStatus.CONFIRMED

    def expire(self) -> None:
        if self.status != BookingStatus.PENDING_PAYMENT:
            return
        self.status = BookingStatus.EXPIRED

    def cancel(self) -> None:
        if self.status not in (BookingStatus.CONFIRMED, BookingStatus.PENDING_PAYMENT):
            raise InvalidStateTransitionError(f"Нельзя отменить бронь в статусе {self.status}")
        self.status = BookingStatus.CANCELLED


@dataclass
class Payment:
    id: UUID
    booking_id: UUID
    amount: Decimal
    status: PaymentStatus = PaymentStatus.PENDING
    stripe_payment_intent_id: str | None = None
    attempt_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)

    def register_attempt(self, intent_id: str) -> None:
        """Фиксирует новую попытку оплаты (новый PaymentIntent)."""
        self.attempt_count += 1
        self.stripe_payment_intent_id = intent_id
        self.status = PaymentStatus.PENDING

    def mark_succeeded(self) -> None:
        self.status = PaymentStatus.SUCCEEDED

    def mark_failed(self) -> None:
        self.status = PaymentStatus.FAILED

    def mark_refunded(self) -> None:
        self.status = PaymentStatus.REFUNDED

    def has_exceeded_retry_limit(self, max_attempts: int) -> bool:
        return self.attempt_count >= max_attempts
