from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable
from uuid import UUID, uuid4

from app.application.interfaces import DistributedLock, PaymentGateway, UnitOfWork
from app.domain.entities import Booking
from app.domain.enums import BookingStatus, PaymentStatus
from app.domain.exceptions import (
    InvalidBookingRequestError,
    NotFoundError,
    PermissionDeniedError,
)


class CreateBookingUseCase:
    """
    Основной сценарий проекта: бронирование слота под услугу.

    Порядок защиты от двойного бронирования (может быть 1 или оба уровня,
    в зависимости от BOOKING_LOCK_STRATEGY):
      1. DistributedLock на ключ слота — сериализует конкурентные запросы
         на уровне приложения ДО похода в БД (актуально для strategy=redis).
      2. SELECT ... FOR UPDATE на строке слота внутри транзакции — пессимистичный
         row-level lock на уровне Postgres (актуально всегда, но по-настоящему
         блокирует только на Postgres, не на SQLite).
      3. UNIQUE constraint на bookings.slot_id — последняя линия защиты:
         даже если 1 и 2 почему-то не сработали, второй INSERT упадёт
         с IntegrityError -> BookingConflictError.
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        lock: DistributedLock,
        unpaid_ttl_minutes: int,
    ):
        self._uow_factory = uow_factory
        self._lock = lock
        self._unpaid_ttl_minutes = unpaid_ttl_minutes

    async def execute(self, *, client_id: UUID, slot_id: UUID, service_id: UUID) -> Booking:
        lock_key = f"booking-lock:slot:{slot_id}"

        async with self._lock(lock_key):
            async with self._uow_factory() as uow:
                slot = await uow.slots.get_by_id(slot_id)
                if slot is None:
                    raise NotFoundError("Slot", slot_id)

                service = await uow.services.get_by_id(service_id)
                if service is None:
                    raise NotFoundError("Service", service_id)

                if service.master_id != slot.master_id:
                    raise InvalidBookingRequestError("Услуга не принадлежит мастеру этого слота")

                now = datetime.utcnow()
                slot.ensure_can_be_booked_for(service, now)  # SlotAlreadyTakenError / SlotInThePastError / ...

                booking = Booking(
                    id=uuid4(),
                    client_id=client_id,
                    slot_id=slot.id,
                    service_id=service.id,
                    price_at_booking=service.price,
                    status=BookingStatus.PENDING_PAYMENT,
                    created_at=now,
                    expires_at=now + timedelta(minutes=self._unpaid_ttl_minutes),
                )
                slot.mark_pending_payment()

                await uow.slots.save(slot)
                await uow.bookings.add(booking)
                await uow.commit()  # может бросить BookingConflictError при гонке

                return booking


class CancelBookingUseCase:
    """
    Отмена брони клиентом. Если бронь была оплачена (status == CONFIRMED),
    оформляет 100%-й возврат через Stripe. Сетевой вызов возврата, как и в
    InitiatePaymentUseCase, вынесен из транзакции БД.
    """

    def __init__(self, uow_factory: Callable[[], UnitOfWork], payment_gateway: PaymentGateway):
        self._uow_factory = uow_factory
        self._payment_gateway = payment_gateway

    async def execute(self, *, booking_id: UUID, requesting_user_id: UUID) -> Booking:
        async with self._uow_factory() as uow:
            booking = await uow.bookings.get_by_id(booking_id)
            if booking is None:
                raise NotFoundError("Booking", booking_id)
            if booking.client_id != requesting_user_id:
                raise PermissionDeniedError("Нельзя отменить чужую бронь")

            was_paid = booking.status == BookingStatus.CONFIRMED
            booking.cancel()  # бросает InvalidStateTransitionError на неверный статус

            slot = await uow.slots.get_by_id(booking.slot_id)
            if slot is not None:
                slot.release()
                await uow.slots.save(slot)

            payment = await uow.payments.get_by_booking_id(booking.id) if was_paid else None

            await uow.bookings.update_status(booking.id, booking.status)
            await uow.commit()

        if was_paid and payment is not None and payment.status == PaymentStatus.SUCCEEDED:
            await self._payment_gateway.refund(payment_intent_id=payment.stripe_payment_intent_id)
            async with self._uow_factory() as uow:
                payment.mark_refunded()
                await uow.payments.update(payment)
                await uow.commit()

        return booking
