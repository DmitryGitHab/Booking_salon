from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import auth, bookings, masters, webhooks
from app.core.config import get_settings
from app.domain.exceptions import (
    BookingConflictError,
    DomainError,
    InvalidBookingRequestError,
    InvalidStateTransitionError,
    NotFoundError,
    PaymentAttemptsExceededError,
    PermissionDeniedError,
    SlotAlreadyTakenError,
    SlotInThePastError,
    SlotTooShortForServiceError,
)

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # для учебного проекта; в проде — конкретные домены
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(masters.router)
app.include_router(bookings.router)
app.include_router(webhooks.router)

# Отдаём простой vanilla-JS фронтенд из /static (появится на следующем этапе)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ---------------------------------------------------------------------------
# Доменные исключения -> HTTP-коды. Это единственное место, где "язык домена"
# (DomainError и наследники, объявленные в app/domain/exceptions.py и ничего
# не знающие про HTTP) переводится в конкретные HTTP-ответы.
# ---------------------------------------------------------------------------

async def _not_found_handler(request, exc: NotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


async def _forbidden_handler(request, exc: PermissionDeniedError):
    return JSONResponse(status_code=403, content={"detail": str(exc)})


async def _conflict_handler(request, exc: DomainError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


async def _bad_request_handler(request, exc: DomainError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


app.add_exception_handler(NotFoundError, _not_found_handler)
app.add_exception_handler(PermissionDeniedError, _forbidden_handler)
app.add_exception_handler(SlotAlreadyTakenError, _conflict_handler)
app.add_exception_handler(BookingConflictError, _conflict_handler)
app.add_exception_handler(SlotInThePastError, _bad_request_handler)
app.add_exception_handler(SlotTooShortForServiceError, _bad_request_handler)
app.add_exception_handler(InvalidBookingRequestError, _bad_request_handler)
app.add_exception_handler(InvalidStateTransitionError, _bad_request_handler)
app.add_exception_handler(PaymentAttemptsExceededError, _bad_request_handler)
app.add_exception_handler(DomainError, _bad_request_handler)  # catch-all на случай новых DomainError


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
