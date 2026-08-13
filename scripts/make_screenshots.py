import json
import uuid
from datetime import datetime, timedelta

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000/static/index.html"

# ---- Стабильные ID для перекрёстных ссылок в моках ----
M1, M2, M3 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
U1, U2, U3 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
S1_1, S1_2 = str(uuid.uuid4()), str(uuid.uuid4())
S2_1, S2_2 = str(uuid.uuid4()), str(uuid.uuid4())
S3_1 = str(uuid.uuid4())

tomorrow = (datetime.utcnow() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


SLOT_A = str(uuid.uuid4())  # free
SLOT_B = str(uuid.uuid4())  # pending_payment
SLOT_C = str(uuid.uuid4())  # booked
SLOT_D = str(uuid.uuid4())  # free
SLOT_M2_A = str(uuid.uuid4())
SLOT_M3_A = str(uuid.uuid4())

MASTERS = [
    {
        "id": M1,
        "user_id": U1,
        "full_name": "Анна Кузнецова",
        "bio": "Колористика, стрижки",
        "services": [
            {"id": S1_1, "master_id": M1, "name": "Стрижка", "duration_minutes": 60, "price": 1500, "is_active": True},
            {"id": S1_2, "master_id": M1, "name": "Окрашивание", "duration_minutes": 120, "price": 4500, "is_active": True},
        ],
    },
    {
        "id": M2,
        "user_id": U2,
        "full_name": "Ирина Соколова",
        "bio": "Маникюр, педикюр",
        "services": [
            {"id": S2_1, "master_id": M2, "name": "Маникюр классический", "duration_minutes": 60, "price": 1200, "is_active": True},
            {"id": S2_2, "master_id": M2, "name": "Педикюр", "duration_minutes": 90, "price": 1800, "is_active": True},
        ],
    },
    {
        "id": M3,
        "user_id": U3,
        "full_name": "Олег Волков",
        "bio": "Барбер",
        "services": [
            {"id": S3_1, "master_id": M3, "name": "Стрижка мужская", "duration_minutes": 45, "price": 1300, "is_active": True},
        ],
    },
]

SLOTS_BY_MASTER = {
    M1: [
        {"id": SLOT_A, "master_id": M1, "start_time": iso(tomorrow), "end_time": iso(tomorrow + timedelta(hours=1)), "status": "free"},
        {"id": SLOT_B, "master_id": M1, "start_time": iso(tomorrow + timedelta(hours=1)), "end_time": iso(tomorrow + timedelta(hours=2)), "status": "pending_payment"},
        {"id": SLOT_C, "master_id": M1, "start_time": iso(tomorrow + timedelta(hours=3)), "end_time": iso(tomorrow + timedelta(hours=4)), "status": "booked"},
        {"id": SLOT_D, "master_id": M1, "start_time": iso(tomorrow + timedelta(days=1)), "end_time": iso(tomorrow + timedelta(days=1, hours=1)), "status": "free"},
    ],
    M2: [
        {"id": SLOT_M2_A, "master_id": M2, "start_time": iso(tomorrow + timedelta(hours=2)), "end_time": iso(tomorrow + timedelta(hours=3)), "status": "free"},
    ],
    M3: [
        {"id": SLOT_M3_A, "master_id": M3, "start_time": iso(tomorrow + timedelta(hours=5)), "end_time": iso(tomorrow + timedelta(hours=5, minutes=45)), "status": "booked"},
    ],
}

CLIENT_BOOKINGS = [
    {
        "id": str(uuid.uuid4()),
        "client_id": "client-1",
        "slot_id": SLOT_B,
        "service_id": S1_1,
        "price_at_booking": 1500,
        "status": "pending_payment",
        "created_at": iso(datetime.utcnow()),
        "expires_at": iso(datetime.utcnow() + timedelta(minutes=15)),
    },
    {
        "id": str(uuid.uuid4()),
        "client_id": "client-1",
        "slot_id": SLOT_C,
        "service_id": S1_2,
        "price_at_booking": 4500,
        "status": "confirmed",
        "created_at": iso(datetime.utcnow() - timedelta(days=1)),
        "expires_at": None,
    },
]

MASTER_ME_BOOKINGS = [
    {
        "id": str(uuid.uuid4()),
        "status": "pending_payment",
        "price_at_booking": 1500,
        "slot_start": iso(tomorrow + timedelta(hours=1)),
        "slot_end": iso(tomorrow + timedelta(hours=2)),
        "service_name": "Стрижка",
        "client_full_name": "Мария Иванова",
        "client_phone": "+7 999 123-45-67",
    },
    {
        "id": str(uuid.uuid4()),
        "status": "confirmed",
        "price_at_booking": 4500,
        "slot_start": iso(tomorrow + timedelta(hours=3)),
        "slot_end": iso(tomorrow + timedelta(hours=4)),
        "service_name": "Окрашивание",
        "client_full_name": "Елена Смирнова",
        "client_phone": "+7 999 765-43-21",
    },
]


def json_route(payload):
    def handler(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))
    return handler


def setup_common_routes(page):
    page.route("**/api/masters", json_route(MASTERS))
    for mid, slots in SLOTS_BY_MASTER.items():
        page.route(f"**/api/masters/{mid}/slots**", json_route(slots))


def set_session(page, role, name="Тестовый пользователь"):
    user = {"id": "client-1", "email": "demo@example.com", "full_name": name, "phone": "+7 999 000-00-00", "role": role}
    page.goto(BASE)
    page.evaluate(
        """([token, user]) => {
            localStorage.setItem('booking_token', token);
            localStorage.setItem('booking_user', JSON.stringify(user));
        }""",
        ["fake-jwt-token", user],
    )
    page.reload()
    page.wait_for_timeout(400)


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 900, "height": 760})
    setup_common_routes(page)

    # 1. Экран авторизации
    page.goto(BASE)
    page.wait_for_timeout(200)
    page.screenshot(path="screenshots/01-auth-login.png")
    page.click("#show-register")
    page.wait_for_timeout(150)
    page.screenshot(path="screenshots/02-auth-register.png")
    browser.close()

    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 900, "height": 1000})
    setup_common_routes(page)

    # 2. Клиент: каталог мастеров и слотов
    page.route("**/api/bookings/me", json_route(CLIENT_BOOKINGS))
    set_session(page, "client", "Мария Иванова")
    page.wait_for_timeout(300)
    page.screenshot(path="screenshots/03-client-browse.png", full_page=True)

    # Раскрываем форму бронирования у первого мастера
    page.click(f'.slot-chip[data-slot="{SLOT_A}"]')
    page.wait_for_timeout(200)
    page.screenshot(path="screenshots/04-client-book-form.png", full_page=True)

    # 3. Клиент: мои брони
    page.click('.tab-btn[data-view="bookings"]')
    page.wait_for_timeout(300)
    page.screenshot(path="screenshots/05-client-bookings.png", full_page=True)

    browser.close()

    # Новый контекст — панель мастера (своя localStorage)
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 900, "height": 1000})
    setup_common_routes(page)
    page.route("**/api/masters/me/bookings", json_route(MASTER_ME_BOOKINGS))
    page.route("**/api/masters/me", json_route(MASTERS[0]))
    set_session(page, "master", "Анна Кузнецова")
    page.wait_for_timeout(300)
    page.screenshot(path="screenshots/06-master-panel.png", full_page=True)
    browser.close()

    # Новый контекст — админ-панель
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 900, "height": 1000})
    setup_common_routes(page)
    set_session(page, "admin", "Админ")
    page.wait_for_timeout(300)
    page.screenshot(path="screenshots/07-admin-panel.png", full_page=True)
    browser.close()

print("Готово")
