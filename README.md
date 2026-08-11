# Booking API — сервис бронирования (запись в салон красоты)

## Статус: Этап 3 оплата через Stripe

Что добавилось на этапе 3 (поверх этапов 1-2):
- `PaymentGateway` — Protocol-порт в `application/interfaces.py`, реализация `StripeGateway`
  в `infrastructure/payments/stripe_gateway.py` (единственное место, знающее про stripe-python).
- `InitiatePaymentUseCase` — создаёт Stripe PaymentIntent для брони. Сетевой вызов к Stripe
  вынесен из транзакции БД (короткая транзакция проверки → HTTP к Stripe → короткая транзакция
  сохранения результата), чтобы не держать открытую транзакцию на время сетевого ожидания.
- **Retry с лимитом попыток**: клиент может повторно дёрнуть `POST /api/bookings/{id}/pay`
  после неуспешной оплаты — пересоздаётся новый PaymentIntent. Лимит — `PAYMENT_RETRY_ATTEMPTS`
  (по умолчанию 3). При исчерпании лимита бронь автоматически переходит в `expired`, слот
  освобождается — это происходит в обработчике webhook `payment_intent.payment_failed`.
- `HandlePaymentWebhookUseCase` — обрабатывает `payment_intent.succeeded` (подтверждает бронь)
  и `payment_intent.payment_failed` (либо разрешает retry, либо аннулирует бронь при исчерпании
  лимита). Подпись webhook-запроса проверяется в роуте через `stripe.Webhook.construct_event`.
- **Возврат при отмене**: `CancelBookingUseCase` теперь принимает `PaymentGateway`. Если бронь
  была оплачена (`status == confirmed`), при отмене оформляется 100%-й возврат через Stripe.
- Роуты: `POST /api/bookings/{id}/pay`, `POST /api/webhooks/stripe`.
- `tests/test_payment_flow.py` — тесты на `FakePaymentGateway` (без реального Stripe и без
  настоящих ключей): успешная оплата → подтверждение, retry-лимит → автоотмена + освобождение
  слота, отмена оплаченной брони → возврат, отмена неоплаченной — без возврата.

## Как это работать с настоящими ключами Stripe
Если у вас появятся свои test-ключи Stripe — просто подставьте их в `.env`:
```
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
```
`STRIPE_WEBHOOK_SECRET` можно получить, слушая события через Stripe CLI:
```bash
stripe listen --forward-to localhost:8000/api/webhooks/stripe
```
Команда выведет `whsec_...` для локальной разработки. Дальше можно реально дёргать
`POST /api/bookings/{id}/pay`, получать `client_secret` и подтверждать оплату тестовой картой
Stripe (`4242 4242 4242 4242`) через Stripe.js на фронтенде (появится на этапе 5) — или
искусственно триггерить событие через `stripe trigger payment_intent.succeeded`.

Без ключей (`sk_test_dummy`) реальные вызовы к Stripe будут падать с ошибкой авторизации —
это ожидаемо, для разработки и тестов используется `FakePaymentGateway` (см. `tests/test_payment_flow.py`).

## Что дальше 
Фоновые задачи (Celery/ARQ): автоотмена неоплаченной брони по `expires_at` таймером (сейчас
   это происходит только реактивно — по факту неуспешного webhook, а не по таймауту), лог + SMS-заглушка.
Docker Compose end-to-end, CI (GitHub Actions), vanilla JS фронтенд, README с диаграммой.

## Запуск локально (без Docker)

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # по умолчанию SQLite, BOOKING_LOCK_STRATEGY=db, Stripe dummy-ключи

alembic upgrade head
uvicorn app.main:app --reload
```

Swagger UI: http://localhost:8000/docs

## Запуск тестов

```bash
# Быстрые тесты (SQLite, секунды, без Docker, без реального Stripe)
pytest tests/test_auth_and_catalog.py tests/test_booking_flow.py tests/test_payment_flow.py -v

# Главный тест на конкурентность (нужен запущенный Docker — поднимет Postgres+Redis сам)
pytest tests/test_concurrency.py -v -s
```

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

## Как пользоваться Swagger UI (`/docs`)

1. Разверните `POST /api/auth/login` → "Try it out" → впишите JSON:
   ```json
   {"email": "admin@example.com", "password": "adminpass123"}
   ```
   → "Execute". В ответе будет `access_token`.
2. Скопируйте **только** значение токена (без слова `Bearer`, без кавычек).
3. Нажмите зелёный замок "Authorize" в правом верхнем углу страницы (или у конкретного
   эндпоинта) → в поле "Value" вставьте скопированный токен → "Authorize" → "Close".
4. Теперь все защищённые эндпоинты (замочек закрылся 🔒) будут автоматически слать
   `Authorization: Bearer <ваш токен>`.

Если раньше видели форму с полями username/password/client_id — это была старая
OAuth2-схема (уже исправлено): наш `/api/auth/login` всегда принимает JSON `{"email", "password"}`,
а не form-data с полем `username`, поэтому та форма и не могла сработать (422).

## Проверка вручную через curl

**Важно:** если вы на Windows и запускаете команды в PowerShell — `curl` там на самом деле алиас
для `Invoke-WebRequest` с другим синтаксисом, и примеры ниже с `-d`/`-X` не сработают как есть.
Варианты:
- используйте **Git Bash** или **WSL** — тогда команды ниже работают как написаны;
- либо в обычном PowerShell используйте `curl.exe` (с явным `.exe`) — это уже настоящий curl;
- либо просто пользуйтесь Swagger UI (`/docs`) — там ничего печатать не нужно вообще.

```bash
# 1. Создать админа (один раз, локально — не через curl, а через сам проект)
python -m scripts.create_admin --email admin@example.com --password adminpass123 --full-name "Admin"

# 2. Логин админа
curl -X POST http://localhost:8000/api/auth/login -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"adminpass123"}'
# Ответ содержит access_token — скопируйте его в переменную для удобства:
ADMIN_TOKEN="<вставьте access_token из ответа>"

# 3. Создать мастера
curl -X POST http://localhost:8000/api/admin/masters -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"email":"master@example.com","full_name":"Мастер","temporary_password":"masterpass123"}'

# 4. Логин мастера
curl -X POST http://localhost:8000/api/auth/login -H "Content-Type: application/json" \
  -d '{"email":"master@example.com","password":"masterpass123"}'
MASTER_TOKEN="<вставьте access_token мастера>"

# 5. Создать услугу и слот (подставьте master_id из шага 3)
curl -X POST http://localhost:8000/api/masters/<master_id>/services -H "Content-Type: application/json" \
  -H "Authorization: Bearer $MASTER_TOKEN" \
  -d '{"name":"Стрижка","duration_minutes":60,"price":"1500.00"}'

curl -X POST http://localhost:8000/api/masters/<master_id>/slots -H "Content-Type: application/json" \
  -H "Authorization: Bearer $MASTER_TOKEN" \
  -d '{"start_time":"2026-09-01T10:00:00","end_time":"2026-09-01T11:00:00"}'

# 6. Клиент регистрируется, бронирует, оплачивает
curl -X POST http://localhost:8000/api/auth/register -H "Content-Type: application/json" \
  -d '{"email":"client@example.com","password":"password123","full_name":"Клиент"}'
CLIENT_TOKEN="<вставьте access_token клиента>"

curl -X POST http://localhost:8000/api/bookings -H "Content-Type: application/json" \
  -H "Authorization: Bearer $CLIENT_TOKEN" \
  -d '{"slot_id":"<slot_id из шага 5>","service_id":"<service_id из шага 5>"}'

curl -X POST http://localhost:8000/api/bookings/<booking_id>/pay \
  -H "Authorization: Bearer $CLIENT_TOKEN"
```

Проще всего все эти шаги проделать через Swagger UI (`/docs`) — каждый эндпоинт там уже
расписан с полями и примерами, ничего вручную собирать не нужно.

## Структура проекта

```
app/
  domain/            # сущности и бизнес-правила (Booking, Slot, Service, Payment) — без фреймворков
  application/
    interfaces.py     # Protocol-ы: репозитории, UnitOfWork, DistributedLock, PaymentGateway
    booking.py         # CreateBookingUseCase, CancelBookingUseCase (+ возврат)
    payment.py          # InitiatePaymentUseCase, HandlePaymentWebhookUseCase
  infrastructure/
    db/               # SQLAlchemy engine, ORM-модели
    repositories/      # SqlAlchemyUnitOfWork + мапперы domain <-> ORM
    locks/             # NullLock (db-стратегия) и RedisLock (redis-стратегия)
    payments/           # StripeGateway — единственное место со stripe-python
  api/
    routes/           # FastAPI-роуты (auth, masters, bookings, webhooks)
    schemas/           # Pydantic-схемы запросов/ответов
    deps.py            # зависимости: текущий юзер, роли, фабрики use case-ов
  core/               # конфиг, security (JWT, хеширование паролей)
  workers/            # фоновые задачи (появятся на этапе 4)
scripts/
  create_admin.py     # CLI для создания первого админа
alembic/              # миграции
tests/
  test_auth_and_catalog.py  # этап 1
  test_booking_flow.py      # этап 2, быстрые
  test_payment_flow.py      # этап 3, быстрые, FakePaymentGateway
  test_concurrency.py       # этап 2, главный тест, нужен Docker
```
