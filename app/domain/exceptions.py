from uuid import UUID


class DomainError(Exception):
    """Базовое исключение доменного слоя."""


class SlotAlreadyTakenError(DomainError):
    def __init__(self, slot_id: UUID):
        self.slot_id = slot_id
        super().__init__(f"Слот {slot_id} уже занят")


class SlotInThePastError(DomainError):
    def __init__(self, slot_id: UUID):
        self.slot_id = slot_id
        super().__init__(f"Слот {slot_id} уже в прошлом")


class SlotTooShortForServiceError(DomainError):
    def __init__(self, slot_id: UUID, service_id: UUID):
        self.slot_id = slot_id
        self.service_id = service_id
        super().__init__(f"Слот {slot_id} короче, чем услуга {service_id}")


class NotFoundError(DomainError):
    def __init__(self, entity: str, entity_id):
        self.entity = entity
        self.entity_id = entity_id
        super().__init__(f"{entity} {entity_id} не найден")


class PermissionDeniedError(DomainError):
    pass


class BookingConflictError(DomainError):
    """Слот забронировали параллельно — сработал constraint/лок на уровне инфраструктуры."""

    def __init__(self, message: str = "Слот только что был забронирован другим клиентом"):
        super().__init__(message)


class InvalidStateTransitionError(DomainError):
    """Попытка недопустимого перехода статуса (например, отменить уже отменённую бронь)."""


class InvalidBookingRequestError(DomainError):
    """Запрос на бронирование логически некорректен (например, услуга не принадлежит мастеру слота)."""
