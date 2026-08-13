"""
Наполняет БД демо-данными: 3 мастера, у каждого 2 услуги и 10 свободных слотов
на завтра. Нужно для нагрузочного теста (locustfile.py) и быстрой ручной проверки —
не обязательно каждый раз собирать каталог руками через curl/Swagger.

Использование:
    python -m scripts.seed_demo_data
"""
import asyncio
from datetime import datetime, timedelta

from app.core.security import hash_password
from app.domain.enums import UserRole
from app.infrastructure.db.base import async_session_maker
from app.infrastructure.db.models import MasterProfile, Service, Slot, User

MASTERS = [
    {"email": "anna@example.com", "full_name": "Анна Кузнецова", "bio": "Колористика, стрижки"},
    {"email": "irina@example.com", "full_name": "Ирина Соколова", "bio": "Маникюр, педикюр"},
    {"email": "oleg@example.com", "full_name": "Олег Волков", "bio": "Барбер"},
]

SERVICES = [
    {"name": "Стрижка", "duration_minutes": 60, "price": 1500},
    {"name": "Окрашивание", "duration_minutes": 120, "price": 4500},
]


async def seed() -> None:
    async with async_session_maker() as session:
        base_day = datetime.utcnow().replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)

        for master_data in MASTERS:
            user = User(
                email=master_data["email"],
                hashed_password=hash_password("masterpass123"),
                full_name=master_data["full_name"],
                role=UserRole.MASTER,
            )
            session.add(user)
            await session.flush()

            profile = MasterProfile(user_id=user.id, bio=master_data["bio"])
            session.add(profile)
            await session.flush()

            for service_data in SERVICES:
                session.add(Service(master_id=profile.id, **service_data))

            for i in range(10):
                start = base_day + timedelta(hours=i)
                session.add(Slot(master_id=profile.id, start_time=start, end_time=start + timedelta(hours=1)))

        await session.commit()
        print(f"Готово: создано {len(MASTERS)} мастеров, у каждого {len(SERVICES)} услуги и 10 слотов.")
        print("Пароль у всех мастеров: masterpass123")


if __name__ == "__main__":
    asyncio.run(seed())
