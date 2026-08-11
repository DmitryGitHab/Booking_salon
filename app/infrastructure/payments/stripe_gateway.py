import asyncio
from decimal import Decimal

import stripe

from app.application.interfaces import PaymentIntentResult
from app.core.config import get_settings

settings = get_settings()
stripe.api_key = settings.stripe_secret_key


class StripeGateway:
    """
    Реализация PaymentGateway поверх stripe-python.

    stripe-python — синхронный SDK (у Stripe нет официального async-клиента),
    поэтому блокирующие HTTP-вызовы уводим в отдельный поток через
    asyncio.to_thread, чтобы не блокировать event loop FastAPI.
    """

    async def create_payment_intent(self, *, amount: Decimal, currency: str, metadata: dict) -> PaymentIntentResult:
        amount_minor_units = int(amount * 100)  # Stripe ждёт сумму в минимальных единицах (центы/копейки)
        intent = await asyncio.to_thread(
            stripe.PaymentIntent.create,
            amount=amount_minor_units,
            currency=currency,
            metadata=metadata,
            automatic_payment_methods={"enabled": True},
        )
        return PaymentIntentResult(intent_id=intent.id, client_secret=intent.client_secret)

    async def refund(self, *, payment_intent_id: str) -> None:
        await asyncio.to_thread(stripe.Refund.create, payment_intent=payment_intent_id)

    @staticmethod
    def verify_webhook_signature(payload: bytes, sig_header: str, webhook_secret: str) -> stripe.Event:
        return stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
