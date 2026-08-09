import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import BookingStatus, PaymentStatus, SlotStatus, UserRole
from app.infrastructure.db.base import Base


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    role: Mapped[UserRole] = mapped_column(default=UserRole.CLIENT, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    master_profile: Mapped["MasterProfile | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    bookings: Mapped[list["Booking"]] = relationship(back_populates="client")


class MasterProfile(Base):
    """Профиль мастера. Создаётся для User с ролью MASTER."""

    __tablename__ = "master_profiles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    bio: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="master_profile")
    services: Mapped[list["Service"]] = relationship(back_populates="master", cascade="all, delete-orphan")
    slots: Mapped[list["Slot"]] = relationship(back_populates="master", cascade="all, delete-orphan")


class Service(Base):
    __tablename__ = "services"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    master_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("master_profiles.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True)

    master: Mapped["MasterProfile"] = relationship(back_populates="services")


class Slot(Base):
    """
    Конкретный временной интервал, открытый мастером для записи.
    Защита от двойного бронирования реализуется на уровне application-слоя
    (SELECT ... FOR UPDATE / Redis-лок) — см. app/application/booking.py на этапе 2.
    """

    __tablename__ = "slots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    master_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("master_profiles.id"), nullable=False)
    start_time: Mapped[datetime] = mapped_column(nullable=False, index=True)
    end_time: Mapped[datetime] = mapped_column(nullable=False)
    status: Mapped[SlotStatus] = mapped_column(default=SlotStatus.FREE, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    master: Mapped["MasterProfile"] = relationship(back_populates="slots")
    booking: Mapped["Booking | None"] = relationship(back_populates="slot", uselist=False)

    __table_args__ = (
        # Один и тот же временной интервал у одного мастера не должен дублироваться как отдельный слот.
        UniqueConstraint("master_id", "start_time", "end_time", name="uq_master_slot_interval"),
    )


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    slot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("slots.id"), unique=True, nullable=False)
    service_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("services.id"), nullable=False)
    price_at_booking: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[BookingStatus] = mapped_column(default=BookingStatus.PENDING_PAYMENT, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)

    client: Mapped["User"] = relationship(back_populates="bookings")
    slot: Mapped["Slot"] = relationship(back_populates="booking")
    service: Mapped["Service"] = relationship()
    payment: Mapped["Payment | None"] = relationship(back_populates="booking", uselist=False, cascade="all, delete-orphan")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id"), unique=True, nullable=False)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[PaymentStatus] = mapped_column(default=PaymentStatus.PENDING, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    attempt_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

    booking: Mapped["Booking"] = relationship(back_populates="payment")
