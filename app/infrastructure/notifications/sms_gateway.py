import logging

logger = logging.getLogger("sms")


class LoggingSmsGateway:
    """
    Заглушка SMS-провайдера. Ничего никуда не отправляет — логирует и печатает
    в консоль, чтобы на демонстрации/собеседовании было видно, что уведомление
    "ушло". Подключение реального провайдера (Twilio, SMS.ru, смс-центр и т.д.)
    сводится к замене тела метода send() — вызывающий код (Celery-таска) не меняется.
    """

    def send(self, phone: str | None, message: str) -> None:
        display_phone = phone or "номер не указан"
        logger.info("SMS -> %s: %s", display_phone, message)
        print(f"[SMS-заглушка] -> {display_phone}: {message}")
