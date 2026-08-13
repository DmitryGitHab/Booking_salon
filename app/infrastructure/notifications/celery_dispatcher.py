import logging
import threading

logger = logging.getLogger(__name__)


class CeleryNotificationDispatcher:
    """
    Реализация NotificationDispatcher для приложения (FastAPI-процесс).
    dispatch_sms() ничего не отправляет сама — просто публикует задачу в Redis
    через Celery. Саму отправку (сейчас — лог + SMS-заглушка) делает воркер,
    см. app/workers/tasks.py:send_sms_task.

    Уведомления — best-effort побочный канал, а не часть основной транзакции.
    Публикация в брокер запускается в отдельном потоке и НЕ дожидается результата:
    если просто ждать try/except в текущем потоке, запрос клиента всё равно виснет
    на время попытки TCP-подключения к недоступному Redis (это и давало ощутимую
    задержку при бронировании). Fire-and-forget в daemon-потоке снимает эту
    зависимость полностью — ответ клиенту уходит мгновенно, независимо от Redis.
    """

    def dispatch_sms(self, *, phone: str | None, message: str) -> None:
        threading.Thread(target=self._publish, args=(phone, message), daemon=True).start()

    @staticmethod
    def _publish(phone: str | None, message: str) -> None:
        try:
            from app.workers.tasks import send_sms_task

            send_sms_task.delay(phone, message)
        except Exception as exc:
            logger.warning("Не удалось поставить уведомление в очередь (Redis недоступен?): %s", exc)
