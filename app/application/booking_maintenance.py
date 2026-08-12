from __future__ import annotations

from datetime import datetime
from typing import Callable

from app.application.interfaces import NotificationDispatcher, UnitOfWork


class ExpireStaleBookingsUseCase:
    """
    Проактивная автоотмена: находит все брони в статусе PENDING_PAYMENT с истёкшим
    expires_at и аннулирует их, освобождая слоты.

    Это дополняет реактивную отмену в HandlePaymentWebhookUseCase.handle_failed —
    та срабатывает только если Stripe вообще прислал webhook о неудачной оплате.
    Если клиент просто закрыл вкладку и не платил вовсе, webhook не придёт никогда,
    и только эта периодическая задача (запускается Celery beat) освободит слот.
    """

    def __init__(self, uow_factory: Callable[[], UnitOfWork], notification_dispatcher: NotificationDispatcher):
        self._uow_factory = uow_factory
        self._notification_dispatcher = notification_dispatcher

    async def execute(self) -> int:
        now = datetime.utcnow()

        async with self._uow_factory() as uow:
            stale_bookings = await uow.bookings.list_stale_pending(now)

            notifications: list[tuple[str | None, str]] = []
            for booking in stale_bookings:
                booking.expire()
                await uow.bookings.update_status(booking.id, booking.status)

                slot = await uow.slots.get_by_id(booking.slot_id)
                if slot is not None:
                    slot.release()
                    await uow.slots.save(slot)

                contact = await uow.users.get_contact(booking.client_id)
                notifications.append(
                    (contact.phone if contact else None, "Время на оплату брони истекло — бронь отменена.")
                )

            await uow.commit()

        for phone, message in notifications:
            self._notification_dispatcher.dispatch_sms(phone=phone, message=message)

        return len(stale_bookings)
