from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import SlotStatus


class ServiceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    duration_minutes: int = Field(gt=0, le=24 * 60)
    price: Decimal = Field(gt=0)


class ServiceResponse(BaseModel):
    id: UUID
    master_id: UUID
    name: str
    duration_minutes: int
    price: Decimal
    is_active: bool

    class Config:
        from_attributes = True


class MasterProfileResponse(BaseModel):
    id: UUID
    user_id: UUID
    full_name: str
    bio: str | None
    services: list[ServiceResponse] = []

    class Config:
        from_attributes = True


class SlotCreateRequest(BaseModel):
    start_time: datetime
    end_time: datetime

    @field_validator("end_time")
    @classmethod
    def end_after_start(cls, end_time: datetime, info):
        start_time = info.data.get("start_time")
        if start_time and end_time <= start_time:
            raise ValueError("end_time должен быть позже start_time")
        return end_time


class SlotResponse(BaseModel):
    id: UUID
    master_id: UUID
    start_time: datetime
    end_time: datetime
    status: SlotStatus

    class Config:
        from_attributes = True


class MasterBookingResponse(BaseModel):
    """Запись клиента к мастеру — то, что видит сам мастер в своей панели."""

    id: UUID
    status: str
    price_at_booking: Decimal
    slot_start: datetime
    slot_end: datetime
    service_name: str
    client_full_name: str
    client_phone: str | None
