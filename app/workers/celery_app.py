from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery("booking_api", broker=settings.redis_url, backend=settings.redis_url)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # Без этого недоступный Redis держит .delay() несколько секунд на ретраях
    # подключения, прежде чем упасть — это и было причиной "долгого ожидания"
    # при бронировании, когда Redis не запущен. Публикация уведомления — best
    # effort (см. CeleryNotificationDispatcher), поэтому ретраить её не нужно.
    broker_connection_retry_on_startup=False,
    broker_connection_retry=False,
    broker_connection_timeout=1,
    broker_transport_options={"socket_connect_timeout": 1, "socket_timeout": 1},
    task_publish_retry=False,
)

# Периодическое расписание (нужен отдельный процесс `celery beat`, см. docker-compose.yml)
celery_app.conf.beat_schedule = {
    "expire-unpaid-bookings-every-minute": {
        "task": "bookings.expire_stale",
        "schedule": 60.0,  # каждую минуту; для реального прод-трафика можно чаще
    },
}

celery_app.autodiscover_tasks(["app.workers"])
