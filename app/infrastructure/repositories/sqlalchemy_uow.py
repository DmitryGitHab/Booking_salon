from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import Booking, Service, Slot
from app.domain.enums import BookingStatus
from app.domain.exceptions import BookingConflictError
from app.infrastructure.db.base import async_session_maker
from app.infrastructure.db.models import Booking as BookingModel
from app.infrastructure.db.models import Service as ServiceModel
from app.infrastructure.db.models import Slot as SlotModel
from app.infrastructure.repositories.mappers import (
    booking_to_domain,
    booking_to_orm,
    service_to_domain,
    slot_to_domain,
)


class SqlAlchemySlotRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, slot_id: UUID) -> Slot | None:
        # with_for_update() — пессимистичная блокировка строки на время транзакции.
        # На SQLite диалект молча игнорирует этот суффикс (там нет построчных локов),
        # но это ожидаемо: конкурентность на SQLite гоняется на уровне "весь файл — один писатель".
        # На Postgres это реальный row-level lock — второй параллельный запрос будет ждать здесь.
        query = select(SlotModel).where(SlotModel.id == slot_id).with_for_update()
        result = await self._session.execute(query)
        orm = result.scalar_one_or_none()
        return slot_to_domain(orm) if orm else None

    async def save(self, slot: Slot) -> None:
        await self._session.execute(
            update(SlotModel).where(SlotModel.id == slot.id).values(status=slot.status)
        )


class SqlAlchemyServiceRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, service_id: UUID) -> Service | None:
        result = await self._session.execute(select(ServiceModel).where(ServiceModel.id == service_id))
        orm = result.scalar_one_or_none()
        return service_to_domain(orm) if orm else None


class SqlAlchemyBookingRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, booking: Booking) -> None:
        self._session.add(booking_to_orm(booking))

    async def get_by_slot_id(self, slot_id: UUID) -> Booking | None:
        result = await self._session.execute(select(BookingModel).where(BookingModel.slot_id == slot_id))
        orm = result.scalar_one_or_none()
        return booking_to_domain(orm) if orm else None

    async def list_by_client(self, client_id: UUID) -> list[Booking]:
        result = await self._session.execute(
            select(BookingModel).where(BookingModel.client_id == client_id).order_by(BookingModel.created_at.desc())
        )
        return [booking_to_domain(orm) for orm in result.scalars().all()]

    async def get_by_id(self, booking_id: UUID) -> Booking | None:
        result = await self._session.execute(select(BookingModel).where(BookingModel.id == booking_id))
        orm = result.scalar_one_or_none()
        return booking_to_domain(orm) if orm else None

    async def update_status(self, booking_id: UUID, status: BookingStatus) -> None:
        await self._session.execute(
            update(BookingModel).where(BookingModel.id == booking_id).values(status=status)
        )


class SqlAlchemyUnitOfWork:
    """
    Одна единица работы = одна транзакция БД = одна AsyncSession.
    Открывает свежую сессию при входе в `async with`, закрывает при выходе.
    IntegrityError (сработавший уникальный constraint на bookings.slot_id)
    переводится в доменное исключение BookingConflictError — это и есть
    перевод "языка инфраструктуры" в "язык домена", который держит use case
    независимым от SQLAlchemy.
    """

    def __init__(self, session_maker=None):
        self._session_maker = session_maker or async_session_maker
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> "SqlAlchemyUnitOfWork":
        self._session = self._session_maker()
        self.slots = SqlAlchemySlotRepository(self._session)
        self.services = SqlAlchemyServiceRepository(self._session)
        self.bookings = SqlAlchemyBookingRepository(self._session)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session is not None:
            await self._session.close()

    async def commit(self) -> None:
        assert self._session is not None
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise BookingConflictError() from exc

    async def rollback(self) -> None:
        assert self._session is not None
        await self._session.rollback()


def sqlalchemy_uow_factory(session_maker=None) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(session_maker=session_maker)
