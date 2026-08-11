"""
Преобразование ORM-моделей SQLAlchemy <-> доменных dataclass'ов.
Единственное место, где инфраструктурный и доменный слой "встречаются" напрямую.
"""
from app.domain.entities import Booking as DomainBooking
from app.domain.entities import Payment as DomainPayment
from app.domain.entities import Service as DomainService
from app.domain.entities import Slot as DomainSlot
from app.infrastructure.db.models import Booking as BookingModel
from app.infrastructure.db.models import Payment as PaymentModel
from app.infrastructure.db.models import Service as ServiceModel
from app.infrastructure.db.models import Slot as SlotModel


def slot_to_domain(orm: SlotModel) -> DomainSlot:
    return DomainSlot(
        id=orm.id,
        master_id=orm.master_id,
        start_time=orm.start_time,
        end_time=orm.end_time,
        status=orm.status,
    )


def service_to_domain(orm: ServiceModel) -> DomainService:
    return DomainService(
        id=orm.id,
        master_id=orm.master_id,
        name=orm.name,
        duration_minutes=orm.duration_minutes,
        price=orm.price,
        is_active=orm.is_active,
    )


def booking_to_domain(orm: BookingModel) -> DomainBooking:
    return DomainBooking(
        id=orm.id,
        client_id=orm.client_id,
        slot_id=orm.slot_id,
        service_id=orm.service_id,
        price_at_booking=orm.price_at_booking,
        status=orm.status,
        created_at=orm.created_at,
        expires_at=orm.expires_at,
    )


def booking_to_orm(domain: DomainBooking) -> BookingModel:
    return BookingModel(
        id=domain.id,
        client_id=domain.client_id,
        slot_id=domain.slot_id,
        service_id=domain.service_id,
        price_at_booking=domain.price_at_booking,
        status=domain.status,
        created_at=domain.created_at,
        expires_at=domain.expires_at,
    )


def payment_to_domain(orm: PaymentModel) -> DomainPayment:
    return DomainPayment(
        id=orm.id,
        booking_id=orm.booking_id,
        amount=orm.amount,
        status=orm.status,
        stripe_payment_intent_id=orm.stripe_payment_intent_id,
        attempt_count=orm.attempt_count,
        created_at=orm.created_at,
    )


def payment_to_orm(domain: DomainPayment) -> PaymentModel:
    return PaymentModel(
        id=domain.id,
        booking_id=domain.booking_id,
        amount=domain.amount,
        status=domain.status,
        stripe_payment_intent_id=domain.stripe_payment_intent_id,
        attempt_count=domain.attempt_count,
        created_at=domain.created_at,
    )
