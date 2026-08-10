from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decode_access_token
from app.domain.enums import UserRole
from app.infrastructure.db.base import get_db_session
from app.infrastructure.db.models import User

# tokenUrl используется только для генерации Swagger-формы логина
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


async def get_current_user(
    db: DbSession,
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось подтвердить учётные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token is None:
        raise credentials_error

    payload = decode_access_token(token)
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

def get_create_booking_use_case():
    from app.application.booking import CreateBookingUseCase
    from app.infrastructure.locks.factory import get_lock
    from app.infrastructure.repositories.sqlalchemy_uow import sqlalchemy_uow_factory

    settings = get_settings()
    return CreateBookingUseCase(
        uow_factory=sqlalchemy_uow_factory,
        lock=get_lock(),
        unpaid_ttl_minutes=settings.unpaid_booking_ttl_minutes,
    )


def get_cancel_booking_use_case():
    from app.application.booking import CancelBookingUseCase
    from app.infrastructure.repositories.sqlalchemy_uow import sqlalchemy_uow_factory

    return CancelBookingUseCase(uow_factory=sqlalchemy_uow_factory)
