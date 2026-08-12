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
)

# Периодическое расписание (нужен отдельный процесс `celery beat`, см. docker-compose.yml)
celery_app.conf.beat_schedule = {
    "expire-unpaid-bookings-every-minute": {
        "task": "bookings.expire_stale",
        "schedule": 60.0,  # каждую минуту; для реального прод-трафика можно чаще
    },
}

celery_app.autodiscover_tasks(["app.workers"])
