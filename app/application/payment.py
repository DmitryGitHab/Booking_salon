from __future__ import annotations

from typing import Callable
from uuid import UUID, uuid4

from app.application.interfaces import NotificationDispatcher, PaymentGateway, PaymentIntentResult, UnitOfWork
from app.domain.entities import Payment
from app.domain.enums import BookingStatus, PaymentStatus
from app.domain.exceptions import (
    InvalidStateTransitionError,
    NotFoundError,
    PaymentAttemptsExceededError,
    PermissionDeniedError,
)


class InitiatePaymentUseCase:
    """
    Создаёт (или пересоздаёт при повторной попытке) Stripe PaymentIntent для брони.

    Сетевой вызов к Stripe намеренно вынесен ИЗ транзакции БД: сначала короткая
    транзакция для проверки прав/статуса и лимита попыток, потом сам HTTP-запрос
    к Stripe, потом вторая короткая транзакция — сохранить результат. Так мы не
    держим открытую транзакцию (и, при db-стратегии, лок на строке) на время,
    пока ждём ответ от внешнего сервиса.
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        payment_gateway: PaymentGateway,
        max_attempts: int,
        currency: str,
    ):
        self._uow_factory = uow_factory
        self._payment_gateway = payment_gateway
        self._max_attempts = max_attempts
        self._currency = currency

    async def execute(self, *, booking_id: UUID, requesting_user_id: UUID) -> PaymentIntentResult:
        async with self._uow_factory() as uow:
            booking = await uow.bookings.get_by_id(booking_id)
            if booking is None:
                raise NotFoundError("Booking", booking_id)
            if booking.client_id != requesting_user_id:
                raise PermissionDeniedError("Нельзя оплатить чужую бронь")
            if booking.status != BookingStatus.PENDING_PAYMENT:
                raise InvalidStateTransitionError(f"Нельзя оплатить бронь в статусе {booking.status}")

            existing_payment = await uow.payments.get_by_booking_id(booking.id)
            if existing_payment is not None and existing_payment.has_exceeded_retry_limit(self._max_attempts):
                raise PaymentAttemptsExceededError()

            amount = booking.price_at_booking

        intent = await self._payment_gateway.create_payment_intent(
            amount=amount,
            currency=self._currency,
            metadata={"booking_id": str(booking_id)},
        )

        async with self._uow_factory() as uow:
            payment = await uow.payments.get_by_booking_id(booking_id)
            if payment is None:
                payment = Payment(
                    id=uuid4(),
                    booking_id=booking_id,
                    amount=amount,
                    status=PaymentStatus.PENDING,
                    stripe_payment_intent_id=intent.intent_id,
                    attempt_count=1,
                )
                await uow.payments.add(payment)
            else:
                payment.register_attempt(intent.intent_id)
                await uow.payments.update(payment)
            await uow.commit()

        return intent


class HandlePaymentWebhookUseCase:
    """
    Обрабатывает webhook-события Stripe (payment_intent.succeeded / .payment_failed).
    Подпись запроса проверяется на уровне API-роута — сюда попадает уже доверенное событие.
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        max_attempts: int,
        notification_dispatcher: NotificationDispatcher,
    ):
        self._uow_factory = uow_factory
        self._max_attempts = max_attempts
        self._notification_dispatcher = notification_dispatcher

    async def handle_succeeded(self, intent_id: str) -> None:
        async with self._uow_factory() as uow:
            payment = await uow.payments.get_by_intent_id(intent_id)
            if payment is None:
                return  # неизвестный intent — не наш платёж или устаревшее событие

            payment.mark_succeeded()
            await uow.payments.update(payment)

            booking = await uow.bookings.get_by_id(payment.booking_id)
            if booking is not None and booking.status == BookingStatus.PENDING_PAYMENT:
                booking.confirm()
                await uow.bookings.update_status(booking.id, booking.status)

                # БАГ, который здесь был: слот оставался в статусе pending_payment
                # навсегда, даже после успешной оплаты — из-за этого в панели
                # мастера нельзя было отличить "ждём оплату" от "оплачено".
                slot = await uow.slots.get_by_id(booking.slot_id)
                if slot is not None:
                    slot.mark_booked()
                    await uow.slots.save(slot)

            await uow.commit()

            contact = await uow.users.get_contact(booking.client_id) if booking is not None else None

        if booking is not None:
            self._notification_dispatcher.dispatch_sms(
                phone=contact.phone if contact else None,
                message="Оплата прошла успешно, бронь подтверждена.",
            )

    async def handle_failed(self, intent_id: str) -> None:
        async with self._uow_factory() as uow:
            payment = await uow.payments.get_by_intent_id(intent_id)
            if payment is None:
                return

            payment.mark_failed()
            await uow.payments.update(payment)

            booking = await uow.bookings.get_by_id(payment.booking_id)
            auto_expired = False
            if (
                booking is not None
                and booking.status == BookingStatus.PENDING_PAYMENT
                and payment.has_exceeded_retry_limit(self._max_attempts)
            ):
                # Лимит попыток исчерпан — бронь автоматически аннулируется, слот освобождается.
                booking.expire()
                auto_expired = True
                await uow.bookings.update_status(booking.id, booking.status)

                slot = await uow.slots.get_by_id(booking.slot_id)
                if slot is not None:
                    slot.release()
                    await uow.slots.save(slot)

            await uow.commit()

            contact = await uow.users.get_contact(booking.client_id) if booking is not None else None

        if auto_expired:
            self._notification_dispatcher.dispatch_sms(
                phone=contact.phone if contact else None,
                message="Превышено число попыток оплаты — бронь автоматически отменена.",
            )
