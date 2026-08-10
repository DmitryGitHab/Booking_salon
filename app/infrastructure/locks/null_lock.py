class NullLock:
    """
    Реализация DistributedLock для стратегии BOOKING_LOCK_STRATEGY=db.

    Ничего не блокирует сама — защита от гонок обеспечивается на уровне БД:
    SELECT ... FOR UPDATE на строке слота (см. SqlAlchemySlotRepository.get_by_id)
    и уникальный constraint на bookings.slot_id, который ловится и переводится
    в BookingConflictError в SqlAlchemyUnitOfWork.commit().
    """

    def __call__(self, key: str) -> "NullLock":
        return self

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None
