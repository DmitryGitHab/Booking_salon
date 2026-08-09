from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.schemas.auth import TokenResponse, UserLoginRequest, UserRegisterRequest, UserResponse
from app.core.security import create_access_token, hash_password, verify_password
from app.domain.enums import UserRole
from app.infrastructure.db.models import MasterProfile, User

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: UserRegisterRequest, db: DbSession):
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email уже зарегистрирован")

    # Регистрировать мастера через публичный /register не разрешаем —
    # мастеров заводит админ через отдельный эндпоинт (см. routes/masters.py).
    role = payload.role if payload.role != UserRole.MASTER else UserRole.CLIENT

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        phone=payload.phone,
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLoginRequest, db: DbSession):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный email или пароль")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Аккаунт деактивирован")

    token = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))
