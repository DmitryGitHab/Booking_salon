import asyncio
import functools
import logging

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="notifications.send_sms")
def send_sms_task(phone: str | None, message: str) -> None:
    from app.infrastructure.notifications.sms_gateway import LoggingSmsGateway

    LoggingSmsGateway().send(phone, message)


@celery_app.task(name="bookings.expire_stale")
def expire_stale_bookings_task() -> int:
    """Периодическая задача (см. celery_app.conf.beat_schedule): аннулирует брони
    с истёкшим expires_at, которые так и остались в статусе pending_payment."""
    count = asyncio.run(_expire_stale_bookings_async())
    logger.info("Автоотмена: аннулировано %s просроченных броней", count)
    return count


async def _expire_stale_bookings_async() -> int:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.application.booking_maintenance import ExpireStaleBookingsUseCase
    from app.core.config import get_settings
    from app.infrastructure.notifications.celery_dispatcher import CeleryNotificationDispatcher
    from app.infrastructure.repositories.sqlalchemy_uow import sqlalchemy_uow_factory

    settings = get_settings()

    # Celery-воркер синхронный: каждый вызов таски здесь создаёт свой event loop
    # через asyncio.run(). asyncpg-соединения жёстко привязаны к тому loop'у, в
    # котором были созданы — переиспользовать пул соединений между вызовами с
    # разными event loop'ами нельзя (получим "attached to a different loop").
    # Поэтому — свежий engine с NullPool на каждый вызов таски, а не глобальный
    # async_session_maker из app.infrastructure.db.base.
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    use_case = ExpireStaleBookingsUseCase(
        uow_factory=functools.partial(sqlalchemy_uow_factory, session_maker=session_maker),
        notification_dispatcher=CeleryNotificationDispatcher(),
    )
    try:
        return await use_case.execute()
    finally:
        await engine.dispose()
