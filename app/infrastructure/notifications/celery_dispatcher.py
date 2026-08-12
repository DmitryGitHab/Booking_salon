class CeleryNotificationDispatcher:
    """
    Реализация NotificationDispatcher для приложения (FastAPI-процесс).
    dispatch_sms() ничего не отправляет сама — просто публикует задачу в Redis
    через Celery и сразу возвращает управление. Саму отправку (сейчас — лог +
    SMS-заглушка) делает воркер, см. app/workers/tasks.py:send_sms_task.
    """

    def dispatch_sms(self, *, phone: str | None, message: str) -> None:
        from app.workers.tasks import send_sms_task

        send_sms_task.delay(phone, message)
