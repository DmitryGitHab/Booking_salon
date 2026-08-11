"""
Создаёт пользователя с ролью admin напрямую в БД — нужен для ручного
тестирования (админ создаёт мастеров через /api/admin/masters).

Использование:
    python -m scripts.create_admin --email admin@example.com --password adminpass123 --full-name "Admin"

Работает с той БД, что указана в DATABASE_URL (.env), — тем же самым файлом
booking.db (или Postgres), к которому обращается uvicorn.
"""
import argparse
import asyncio

from sqlalchemy import select

from app.core.security import hash_password
from app.domain.enums import UserRole
from app.infrastructure.db.base import async_session_maker
from app.infrastructure.db.models import User


async def create_admin(email: str, password: str, full_name: str) -> None:
    async with async_session_maker() as session:
        existing = await session.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none() is not None:
            print(f"Пользователь с email {email} уже существует — ничего не делаю.")
            return

        admin = User(
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
            role=UserRole.ADMIN,
        )
        session.add(admin)
        await session.commit()
        print(f"Готово: создан admin {email} (id={admin.id})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Создать пользователя с ролью admin")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True, help="Минимум 8 символов")
    parser.add_argument("--full-name", required=True, dest="full_name")
    args = parser.parse_args()

    asyncio.run(create_admin(args.email, args.password, args.full_name))


if __name__ == "__main__":
    main()
