# Booking API — сервис бронирования (запись в салон красоты)

 домен, БД, миграции, роли, CRUD мастеров/услуг/слотов

Что уже готово:
- Clean-архитектура: `domain/` (чистая бизнес-логика, без зависимостей от фреймворков) → `infrastructure/` (SQLAlchemy) → `api/` (FastAPI).
- Роли пользователей: `client`, `master`, `admin`. JWT-аутентификация (python-jose + passlib).
  - Регистрация публична только для роли `client`. Мастеров заводит `admin` через `/api/admin/masters`.
- Модели: `User`, `MasterProfile`, `Service`, `Slot`, `Booking`, `Payment` (Booking/Payment пока не используются — это этап 2-3).
- Alembic-миграция `0001_initial` создаёт всю схему.
- Тесты на SQLite in-memory через `pytest-asyncio` + `httpx.ASGITransport` (реальных HTTP-запросов наружу нет).

## Что дальше 
2. Логика бронирования (`CreateBooking` use case) + защита от гонок (constraint в БД / Redis-лок) + тест на 50 параллельных запросов.
3. Интеграция Stripe (webhook подтверждения оплаты, retry при неуспехе).
4. Фоновые задачи (Celery/ARQ): автоотмена неоплаченной брони, лог-уведомления + заглушка SMS.
5. Docker Compose end-to-end, CI (GitHub Actions), vanilla JS фронтенд, README с диаграммой и метриками нагрузочного теста.

## Запуск локально (без Docker)

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # можно ничего не менять — по умолчанию SQLite

alembic upgrade head
uvicorn app.main:app --reload
```

Swagger UI: http://localhost:8000/docs

## Запуск тестов

```bash
pytest -v
```

## Запуск через Docker (Postgres + Redis)

```bash
docker compose up --build
```

Применит миграции и поднимет API на http://localhost:8000, БД — Postgres в контейнере `db`.

## Проверка вручную через curl

```bash
# 1. Регистрация клиента
curl -X POST localhost:8000/api/auth/register -H "Content-Type: application/json" \
  -d '{"email":"client@example.com","password":"password123","full_name":"Иван Клиент"}'

# 2. Логин -> получаем access_token
curl -X POST localhost:8000/api/auth/login -H "Content-Type: application/json" \
  -d '{"email":"client@example.com","password":"password123"}'
```

Чтобы создать мастера, нужен пользователь с ролью `admin` — на этом этапе он заводится напрямую в БД
(сид-скрипт появится на этапе 5) или руками через Python shell:

```python
from app.core.security import hash_password
from app.domain.enums import UserRole
from app.infrastructure.db.models import User
# ... создать сессию и добавить User(role=UserRole.ADMIN, ...)
```

## Структура проекта

```
app/
  domain/            # сущности и бизнес-правила (Booking, Slot, Service) — без фреймворков
  application/        # use cases (появятся на этапе 2: CreateBooking, CancelBooking...)
  infrastructure/
    db/               # SQLAlchemy engine, ORM-модели
    repositories/     # репозитории (появятся на этапе 2)
  api/
    routes/           # FastAPI-роуты
    schemas/          # Pydantic-схемы запросов/ответов
    deps.py           # зависимости: текущий юзер, проверка ролей
  core/               # конфиг, security (JWT, хеширование паролей)
  workers/            # фоновые задачи (появятся на этапе 4)
alembic/              # миграции
tests/                # pytest на SQLite in-memory
```
