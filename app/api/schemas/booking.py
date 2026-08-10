from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from app.domain.enums import BookingStatus


class BookingCreateRequest(BaseModel):
    slot_id: UUID
    service_id: UUID


class BookingResponse(BaseModel):
    id: UUID
    client_id: UUID
    slot_id: UUID
    service_id: UUID
    price_at_booking: Decimal
    status: BookingStatus
    created_at: datetime
    expires_at: datetime | None

    class Config:
        from_attributes = True

    @classmethod
    def from_domain(cls, booking) -> "BookingResponse":
        return cls(
            id=booking.id,
            client_id=booking.client_id,
            slot_id=booking.slot_id,
            service_id=booking.service_id,
            price_at_booking=booking.price_at_booking,
            status=booking.status,
            created_at=booking.created_at,
            expires_at=booking.expires_at,
        )
