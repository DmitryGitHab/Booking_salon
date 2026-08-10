# Booking API — сервис бронирования (запись в салон красоты)

## Статус: Этап 2 из 5 — логика бронирования + защита от двойного бронирования

Что добавилось на этапе 2 (поверх этапа 1):
- `app/application/booking.py` — `CreateBookingUseCase` и `CancelBookingUseCase`. Знают только про
  Protocol-интерфейсы из `app/application/interfaces.py`, не про SQLAlchemy/Redis напрямую.
- **Обе стратегии защиты от гонок**, переключаются настройкой `BOOKING_LOCK_STRATEGY=db|redis`:
  - `db` (по умолчанию) — `SELECT ... FOR UPDATE` на строке слота внутри транзакции +
    UNIQUE constraint на `bookings.slot_id` как последняя линия защиты (ловим `IntegrityError`
    в `SqlAlchemyUnitOfWork.commit()` и переводим в доменный `BookingConflictError`).
  - `redis` — вдобавок распределённый лок на ключ `booking-lock:slot:{id}` (`SET NX PX` +
    безопасный релиз через Lua-скрипт с проверкой владельца), чтобы конкурентные запросы не
    тратили транзакцию впустую, а сразу вставали в очередь.
- Доменные исключения (`SlotAlreadyTakenError`, `BookingConflictError`, `SlotTooShortForServiceError`
  и т.д.) больше не HTTP-специфичны — маппятся в HTTP-коды централизованно в `app/main.py`.
- Роуты: `POST /api/bookings`, `POST /api/bookings/{id}/cancel`, `GET /api/bookings/me`.
- Два набора тестов:
  - `tests/test_booking_flow.py` — быстрые (SQLite, без Docker): happy path, 409 при повторной
    брони, 400 при несовпадении мастера/услуги, 400 если слот короче услуги.
  - `tests/test_concurrency.py` — **главный тест проекта**: 50 параллельных запросов на один
    слот, для обеих стратегий, на реальных Postgres+Redis через `testcontainers` (нужен Docker).

## Что дальше (этапы 3-5)
3. Интеграция Stripe (webhook подтверждения оплаты, retry при неуспехе, возврат при отмене).
4. Фоновые задачи (Celery/ARQ): автоотмена неоплаченной брони по `expires_at`, лог + SMS-заглушка.
5. Docker Compose end-to-end, CI (GitHub Actions), vanilla JS фронтенд, README с диаграммой.

## Запуск локально (без Docker)

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # по умолчанию SQLite + BOOKING_LOCK_STRATEGY=db

alembic upgrade head
uvicorn app.main:app --reload
```

Swagger UI: http://localhost:8000/docs

## Запуск тестов

```bash
# Быстрые тесты (SQLite, секунды, без Docker)
pytest tests/test_booking_flow.py tests/test_auth_and_catalog.py -v

# Главный тест на конкурентность (нужен запущенный Docker — поднимет Postgres+Redis сам)
pytest tests/test_concurrency.py -v -s
```

Пример ожидаемого вывода `test_concurrency.py` (флаг `-s`, чтобы видеть print):
```
[db strategy] 50 параллельных запросов -> 1 успех, 49 корректных конфликтов
[redis strategy] 50 параллельных запросов -> 1 успех, 49 корректных конфликтов
```

Если Docker недоступен, `test_concurrency.py` аккуратно скипается (не падает), чтобы не ломать
обычный прогон тестов на машине без Docker.

## Запуск через Docker (Postgres + Redis)

```bash
docker compose up --build
```

Чтобы попробовать стратегию `redis` вместо `db` — добавьте в `docker-compose.yml` в секцию
`app.environment`:
```yaml
BOOKING_LOCK_STRATEGY: redis
REDIS_URL: redis://redis:6379/0
```

## Проверка вручную через curl

```bash
# 1. Регистрация клиента
curl -X POST localhost:8000/api/auth/register -H "Content-Type: application/json" \
  -d '{"email":"client@example.com","password":"password123","full_name":"Иван Клиент"}'

# 2. Логин -> получаем access_token
curl -X POST localhost:8000/api/auth/login -H "Content-Type: application/json" \
  -d '{"email":"client@example.com","password":"password123"}'

# 3. Бронирование слота (нужны slot_id и service_id, см. GET /api/masters/{id}/slots)
curl -X POST localhost:8000/api/bookings -H "Content-Type: application/json" \
  -H "Authorization: Bearer <access_token>" \
  -d '{"slot_id":"<slot-uuid>","service_id":"<service-uuid>"}'
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
  application/
    interfaces.py     # Protocol-ы: SlotRepository, BookingRepository, UnitOfWork, DistributedLock
    booking.py         # CreateBookingUseCase, CancelBookingUseCase
  infrastructure/
    db/               # SQLAlchemy engine, ORM-модели
    repositories/      # SqlAlchemyUnitOfWork + мапперы domain <-> ORM
    locks/             # NullLock (db-стратегия) и RedisLock (redis-стратегия)
  api/
    routes/           # FastAPI-роуты (auth, masters, bookings)
    schemas/           # Pydantic-схемы запросов/ответов
    deps.py            # зависимости: текущий юзер, роли, фабрики use case-ов
  core/               # конфиг, security (JWT, хеширование паролей)
  workers/            # фоновые задачи (появятся на этапе 4)
alembic/              # миграции
tests/
  test_auth_and_catalog.py  # этап 1
  test_booking_flow.py      # этап 2, быстрые
  test_concurrency.py       # этап 2, главный тест, нужен Docker
```
