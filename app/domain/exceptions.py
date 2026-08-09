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
