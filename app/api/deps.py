from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decode_access_token
from app.domain.enums import UserRole
from app.infrastructure.db.base import get_db_session
from app.infrastructure.db.models import User

# HTTPBearer (не OAuth2PasswordBearer!) — потому что наш /api/auth/login принимает JSON
# {"email": ..., "password": ...}, а не стандартную OAuth2 form-data с полем "username".
# С HTTPBearer кнопка Authorize в Swagger показывает одно простое поле "Value" для вставки
# access_token, без формы логина, которая всё равно не подошла бы под нашу JSON-схему.
bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


async def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось подтвердить учётные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise credentials_error

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise credentials_error

    result = await db.execute(select(User).where(User.id == payload.user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_error
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*allowed_roles: UserRole):
    """Фабрика зависимостей: require_roles(UserRole.ADMIN, UserRole.MASTER)"""

    async def checker(user: CurrentUser) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для этого действия",
            )
        return user

    return checker


# ---------------------------------------------------------------------------
# Фабрики use case-ов (application-слой). Собирают use case из конкретных
# инфраструктурных реализаций — единственное место, где это "склеивается".
# ---------------------------------------------------------------------------

def get_payment_gateway():
    from app.infrastructure.payments.stripe_gateway import StripeGateway

    return StripeGateway()


def get_notification_dispatcher():
    from app.infrastructure.notifications.celery_dispatcher import CeleryNotificationDispatcher

    return CeleryNotificationDispatcher()


def get_create_booking_use_case(notification_dispatcher=Depends(get_notification_dispatcher)):
    from app.application.booking import CreateBookingUseCase
    from app.infrastructure.locks.factory import get_lock
    from app.infrastructure.repositories.sqlalchemy_uow import sqlalchemy_uow_factory

    settings = get_settings()
    return CreateBookingUseCase(
        uow_factory=sqlalchemy_uow_factory,
        lock=get_lock(),
        unpaid_ttl_minutes=settings.unpaid_booking_ttl_minutes,
        notification_dispatcher=notification_dispatcher,
    )


def get_cancel_booking_use_case(
    payment_gateway=Depends(get_payment_gateway),
    notification_dispatcher=Depends(get_notification_dispatcher),
):
    from app.application.booking import CancelBookingUseCase
    from app.infrastructure.repositories.sqlalchemy_uow import sqlalchemy_uow_factory

    return CancelBookingUseCase(
        uow_factory=sqlalchemy_uow_factory,
        payment_gateway=payment_gateway,
        notification_dispatcher=notification_dispatcher,
    )


def get_initiate_payment_use_case(payment_gateway=Depends(get_payment_gateway)):
    from app.application.payment import InitiatePaymentUseCase
    from app.infrastructure.repositories.sqlalchemy_uow import sqlalchemy_uow_factory

    settings = get_settings()
    return InitiatePaymentUseCase(
        uow_factory=sqlalchemy_uow_factory,
        payment_gateway=payment_gateway,
        max_attempts=settings.payment_retry_attempts,
        currency=settings.stripe_currency,
    )


def get_handle_payment_webhook_use_case(notification_dispatcher=Depends(get_notification_dispatcher)):
    from app.application.payment import HandlePaymentWebhookUseCase
    from app.infrastructure.repositories.sqlalchemy_uow import sqlalchemy_uow_factory

    settings = get_settings()
    return HandlePaymentWebhookUseCase(
        uow_factory=sqlalchemy_uow_factory,
        max_attempts=settings.payment_retry_attempts,
        notification_dispatcher=notification_dispatcher,
    )


def get_stripe_webhook_verifier():
    """
    Возвращает функцию проверки подписи Stripe-запроса.
    Вынесено в зависимость специально, чтобы в тестах (где ключи dummy и
    настоящую подпись Stripe не проверить) можно было подменить на заглушку
    через app.dependency_overrides.
    """
    from app.infrastructure.payments.stripe_gateway import StripeGateway

    settings = get_settings()

    def verify(payload: bytes, sig_header: str):
        return StripeGateway.verify_webhook_signature(payload, sig_header, settings.stripe_webhook_secret)

    return verify
