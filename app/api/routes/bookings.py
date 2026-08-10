from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, get_cancel_booking_use_case, get_create_booking_use_case, require_roles
from app.api.schemas.booking import BookingCreateRequest, BookingResponse
from app.application.booking import CancelBookingUseCase, CreateBookingUseCase
from app.domain.enums import UserRole
from app.infrastructure.db.models import Booking as BookingModel

router = APIRouter(prefix="/api/bookings", tags=["bookings"])


@router.post("", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
async def create_booking(
    payload: BookingCreateRequest,
    current_user: Annotated[CurrentUser, Depends(require_roles(UserRole.CLIENT))],
    use_case: Annotated[CreateBookingUseCase, Depends(get_create_booking_use_case)],
):
    booking = await use_case.execute(
        client_id=current_user.id,
        slot_id=payload.slot_id,
        service_id=payload.service_id,
    )
    return BookingResponse.from_domain(booking)


@router.post("/{booking_id}/cancel", response_model=BookingResponse)
async def cancel_booking(
    booking_id: UUID,
    current_user: CurrentUser,
    use_case: Annotated[CancelBookingUseCase, Depends(get_cancel_booking_use_case)],
):
    booking = await use_case.execute(booking_id=booking_id, requesting_user_id=current_user.id)
    return BookingResponse.from_domain(booking)


@router.get("/me", response_model=list[BookingResponse])
async def list_my_bookings(current_user: CurrentUser, db: DbSession):
    # Простое чтение — без похода через use case/UnitOfWork, читаем напрямую.
    result = await db.execute(
        select(BookingModel)
        .where(BookingModel.client_id == current_user.id)
        .order_by(BookingModel.created_at.desc())
    )
    return result.scalars().all()
