from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, require_roles
from app.api.schemas.catalog import (
    MasterBookingResponse,
    MasterProfileResponse,
    ServiceCreateRequest,
    ServiceResponse,
    SlotCreateRequest,
    SlotResponse,
)
from app.core.security import hash_password
from app.domain.enums import SlotStatus, UserRole
from app.infrastructure.db.models import Booking, MasterProfile, Service, Slot, User

router = APIRouter(tags=["masters"])


async def _get_master_or_404(db: DbSession, master_id: UUID) -> MasterProfile:
    result = await db.execute(
        select(MasterProfile)
        .options(selectinload(MasterProfile.services), selectinload(MasterProfile.user))
        .where(MasterProfile.id == master_id)
    )
    master = result.scalar_one_or_none()
    if master is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Мастер не найден")
    return master


def _ensure_owner_or_admin(current_user: User, master: MasterProfile) -> None:
    if current_user.role == UserRole.ADMIN or current_user.id == master.user_id:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Это не ваш профиль мастера")


def _to_master_response(master: MasterProfile) -> MasterProfileResponse:
    return MasterProfileResponse(
        id=master.id,
        user_id=master.user_id,
        full_name=master.user.full_name,
        bio=master.bio,
        services=[ServiceResponse.model_validate(s) for s in master.services],
    )


# ---------------------------------------------------------------------------
# Admin: создание мастера (заводит учётку User с ролью MASTER + профиль)
# ---------------------------------------------------------------------------

class AdminCreateMasterRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    phone: str | None = None
    bio: str | None = None
    temporary_password: str = Field(min_length=8, max_length=128)


@router.post(
    "/api/admin/masters",
    response_model=MasterProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def admin_create_master(
    payload: AdminCreateMasterRequest,
    db: DbSession,
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email уже зарегистрирован")

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.temporary_password),
        full_name=payload.full_name,
        phone=payload.phone,
        role=UserRole.MASTER,
    )
    db.add(user)
    await db.flush()  # получаем user.id до коммита

    profile = MasterProfile(user_id=user.id, bio=payload.bio)
    db.add(profile)
    await db.commit()
    await db.refresh(profile, attribute_names=["services", "user"])

    return _to_master_response(profile)


# ---------------------------------------------------------------------------
# Публичные эндпоинты: список мастеров, детали, услуги, свободные слоты
# ---------------------------------------------------------------------------

@router.get("/api/masters", response_model=list[MasterProfileResponse])
async def list_masters(db: DbSession):
    result = await db.execute(
        select(MasterProfile).options(selectinload(MasterProfile.services), selectinload(MasterProfile.user))
    )
    masters = result.scalars().all()
    return [_to_master_response(m) for m in masters]


@router.get("/api/masters/me/bookings", response_model=list[MasterBookingResponse])
async def list_my_master_bookings(db: DbSession, current_user: CurrentUser):
    """Записи клиентов к текущему мастеру — имя, телефон, услуга, время, статус."""
    if current_user.role != UserRole.MASTER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступно только мастерам")

    profile_result = await db.execute(select(MasterProfile).where(MasterProfile.user_id == current_user.id))
    profile = profile_result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Профиль мастера не найден")

    query = (
        select(Booking, Slot, Service, User)
        .join(Slot, Booking.slot_id == Slot.id)
        .join(Service, Booking.service_id == Service.id)
        .join(User, Booking.client_id == User.id)
        .where(Slot.master_id == profile.id)
        .order_by(Slot.start_time)
    )
    rows = (await db.execute(query)).all()

    return [
        MasterBookingResponse(
            id=booking.id,
            status=booking.status.value,
            price_at_booking=booking.price_at_booking,
            slot_start=slot.start_time,
            slot_end=slot.end_time,
            service_name=service.name,
            client_full_name=client.full_name,
            client_phone=client.phone,
        )
        for booking, slot, service, client in rows
    ]


@router.get("/api/masters/me", response_model=MasterProfileResponse)
async def get_my_master_profile(db: DbSession, current_user: CurrentUser):
    """Возвращает профиль мастера текущего пользователя — нужно фронтенду,
    чтобы мастер мог добавлять свои услуги/слоты, не зная свой master_id заранее."""
    if current_user.role != UserRole.MASTER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступно только мастерам")

    result = await db.execute(
        select(MasterProfile)
        .options(selectinload(MasterProfile.services), selectinload(MasterProfile.user))
        .where(MasterProfile.user_id == current_user.id)
    )
    master = result.scalar_one_or_none()
    if master is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Профиль мастера не найден")
    return _to_master_response(master)


@router.get("/api/masters/{master_id}", response_model=MasterProfileResponse)
async def get_master(master_id: UUID, db: DbSession):
    master = await _get_master_or_404(db, master_id)
    return _to_master_response(master)


@router.get("/api/masters/{master_id}/slots", response_model=list[SlotResponse])
async def list_master_slots(
    master_id: UUID,
    db: DbSession,
    only_free: bool = Query(default=True, description="Показывать только свободные слоты"),
):
    await _get_master_or_404(db, master_id)
    query = select(Slot).where(Slot.master_id == master_id).order_by(Slot.start_time)
    if only_free:
        query = query.where(Slot.status == SlotStatus.FREE)
    result = await db.execute(query)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Мастер (или админ): управление своими услугами и слотами
# ---------------------------------------------------------------------------

@router.post(
    "/api/masters/{master_id}/services",
    response_model=ServiceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_service(
    master_id: UUID,
    payload: ServiceCreateRequest,
    db: DbSession,
    current_user: CurrentUser,
):
    master = await _get_master_or_404(db, master_id)
    _ensure_owner_or_admin(current_user, master)

    service = Service(
        master_id=master.id,
        name=payload.name,
        duration_minutes=payload.duration_minutes,
        price=payload.price,
    )
    db.add(service)
    await db.commit()
    await db.refresh(service)
    return service


@router.post(
    "/api/masters/{master_id}/slots",
    response_model=SlotResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_slot(
    master_id: UUID,
    payload: SlotCreateRequest,
    db: DbSession,
    current_user: CurrentUser,
):
    master = await _get_master_or_404(db, master_id)
    _ensure_owner_or_admin(current_user, master)

    slot = Slot(
        master_id=master.id,
        start_time=payload.start_time,
        end_time=payload.end_time,
        status=SlotStatus.FREE,
    )
    db.add(slot)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Такой слот уже существует у этого мастера",
        )
    await db.refresh(slot)
    return slot
