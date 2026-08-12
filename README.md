# Booking API — сервис бронирования (запись в салон красоты)

## Статус: Этап 4 из 5 — фоновые задачи (Celery) и уведомления

Что добавилось на этапе 4 (поверх этапов 1-3):
- **Celery + Redis** как брокер задач (`app/workers/celery_app.py`, `app/workers/tasks.py`).
- **Проактивная автоотмена**: периодическая задача `bookings.expire_stale` (Celery beat, раз
  в минуту) находит брони в статусе `pending_payment` с истёкшим `expires_at` и аннулирует их,
  освобождая слот. Это дополняет уже существовавшую *реактивную* отмену (по факту неуспешного
  Stripe-webhook) — теперь бронь гарантированно "протухнет", даже если клиент просто закрыл
  вкладку и Stripe вообще ничего не прислал.
- **Уведомления** (лог + SMS-заглушка) на 4 события: бронь создана, оплата прошла, бронь
  отменена клиентом, бронь автоматически аннулирована. Архитектурно это `NotificationDispatcher`
  — Protocol-порт в `application/interfaces.py`; use case-ы вызывают `dispatch_sms(...)`, которая
  синхронно публикует Celery-задачу в Redis и сразу возвращает управление (сама отправка — уже
  в воркере, `app/workers/tasks.py:send_sms_task` → `LoggingSmsGateway`, которая просто логирует
  и печатает в консоль — реальный провайдер типа Twilio/SMS.ru подключается заменой одного файла).
- Небольшой рефакторинг: добавлен `UserRepository`/`ClientContact` в UoW — понадобился, чтобы
  use case-ы могли получить телефон клиента для SMS, не выходя за пределы своих Protocol-портов.

## Важный нюанс реализации (годится как тема для собеседования)
Celery-воркер — синхронный процесс, а наш стек полностью `async`. Периодическая задача
`expire_stale_bookings_task` оборачивает async-код в `asyncio.run(...)`, и **каждый вызов
таски создаёт новый event loop**. `asyncpg`-соединения жёстко привязаны к тому loop'у, в
котором были созданы, поэтому переиспользовать глобальный пул соединений (как это делает
FastAPI-процесс) между вызовами таски **нельзя** — поймаем `RuntimeError: ... attached to a
different loop`. Решение — в `app/workers/tasks.py`: на каждый вызов таски создаётся свежий
`AsyncEngine` с `NullPool` (без переиспользования соединений) и он же корректно `dispose()`-ится
по завершении.

## Что дальше (этап 5)
Docker Compose end-to-end (уже добавлены сервисы `worker`/`beat`, см. ниже), CI (GitHub Actions),
vanilla JS фронтенд, README с диаграммой архитектуры и метриками нагрузочного теста.

## Запуск локально (без Docker)

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env

alembic upgrade head
```

Нужно поднять локальный Redis (для Celery-брокера и, если используете, для `BOOKING_LOCK_STRATEGY=redis`):
```bash
docker run -d -p 6379:6379 redis:7-alpine
```

Дальше — 3 отдельных процесса в 3 терминалах:
```bash
# Терминал 1: сам API
uvicorn app.main:app --reload

# Терминал 2: воркер, реально выполняющий задачи
celery -A app.workers.celery_app worker --loglevel=info

# Терминал 3: планировщик периодических задач (раз в минуту гоняет автоотмену)
celery -A app.workers.celery_app beat --loglevel=info
```

Swagger UI: http://localhost:8000/docs. Когда придёт время автоотмены — в терминале воркера
увидите лог вида `[SMS-заглушка] -> +7999...: Время на оплату брони истекло — бронь отменена.`

## Запуск тестов

```bash
# Быстрые тесты (SQLite, секунды, без Docker, без реального Redis/Stripe)
pytest tests/test_auth_and_catalog.py tests/test_booking_flow.py tests/test_payment_flow.py tests/test_booking_maintenance.py -v

# Главный тест на конкурентность (нужен запущенный Docker)
pytest tests/test_concurrency.py -v -s
```

Все быстрые тесты подменяют `NotificationDispatcher` на fake (`tests/conftest.py:FakeNotificationDispatcher`)
через `app.dependency_overrides` — реальный `CeleryNotificationDispatcher` полез бы в Redis,
которого в тестовом окружении нет.

## Запуск через Docker (Postgres + Redis + API + worker + beat)

```bash
docker compose up --build
```

Теперь поднимаются 5 сервисов: `db`, `redis`, `app`, `worker`, `beat`.

## Как создать первого админа

Публичная регистрация (`/api/auth/register`) может создать только роль `client` — так и
задумано (мастеров заводит бизнес, а не кто угодно с улицы). Первого админа создаём CLI-скриптом:

```bash
python -m scripts.create_admin --email admin@example.com --password adminpass123 --full-name "Admin"
```

Скрипт пишет прямо в ту БД, что указана в `DATABASE_URL` вашего `.env` — тот же файл/база,
к которой обращается `uvicorn`. Дальше логинитесь под этим email/паролем через `/api/auth/login`
и создаёте мастеров через `POST /api/admin/masters` с полученным токеном.

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

Авторизация сделана через `HTTPBearer` (не `OAuth2PasswordBearer`) специально: наш
`/api/auth/login` принимает JSON `{"email", "password"}`, а не form-data с полем `username`,
поэтому стандартная OAuth2-форма логина в Swagger всё равно не подошла бы под нашу схему.

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
  domain/            # сущности и бизнес-правила — без фреймворков
  application/
    interfaces.py     # Protocol-ы: репозитории, UnitOfWork, DistributedLock, PaymentGateway,
                        # NotificationDispatcher, ClientContact/UserRepository
    booking.py         # CreateBookingUseCase, CancelBookingUseCase (+ уведомления, возврат)
    payment.py          # InitiatePaymentUseCase, HandlePaymentWebhookUseCase (+ уведомления)
    booking_maintenance.py  # ExpireStaleBookingsUseCase — периодическая автоотмена
  infrastructure/
    db/               # SQLAlchemy engine, ORM-модели
    repositories/      # SqlAlchemyUnitOfWork + мапперы domain <-> ORM
    locks/             # NullLock (db-стратегия) и RedisLock (redis-стратегия)
    payments/           # StripeGateway
    notifications/      # LoggingSmsGateway (заглушка) + CeleryNotificationDispatcher
  workers/
    celery_app.py      # конфиг Celery + beat_schedule
    tasks.py            # send_sms_task, expire_stale_bookings_task
  api/
    routes/           # FastAPI-роуты (auth, masters, bookings, webhooks)
    schemas/           # Pydantic-схемы запросов/ответов
    deps.py            # зависимости: текущий юзер, роли, фабрики use case-ов
  core/               # конфиг, security (JWT, хеширование паролей)
scripts/
  create_admin.py     # CLI для создания первого админа
alembic/              # миграции
tests/
  test_auth_and_catalog.py     # этап 1
  test_booking_flow.py         # этап 2, быстрые
  test_payment_flow.py         # этап 3, быстрые, FakePaymentGateway
  test_booking_maintenance.py  # этап 4, быстрые, автоотмена + уведомления
  test_concurrency.py          # этап 2, главный тест, нужен Docker
```
