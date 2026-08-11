import logging
from typing import Annotated, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import get_handle_payment_webhook_use_case, get_stripe_webhook_verifier
from app.application.payment import HandlePaymentWebhookUseCase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.post("/stripe", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    use_case: Annotated[HandlePaymentWebhookUseCase, Depends(get_handle_payment_webhook_use_case)],
    verify_signature: Annotated[Callable, Depends(get_stripe_webhook_verifier)],
):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = verify_signature(payload, sig_header)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Невалидная подпись webhook: {exc}")

    event_type = event["type"]
    intent_id = event["data"]["object"]["id"]

    if event_type == "payment_intent.succeeded":
        await use_case.handle_succeeded(intent_id)
    elif event_type == "payment_intent.payment_failed":
        await use_case.handle_failed(intent_id)
    else:
        logger.info("Пропускаем необрабатываемый тип события Stripe: %s", event_type)

    return {"received": True}
