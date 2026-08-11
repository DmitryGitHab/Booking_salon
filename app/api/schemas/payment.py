from pydantic import BaseModel


class PaymentInitiateResponse(BaseModel):
    payment_intent_id: str
    client_secret: str
