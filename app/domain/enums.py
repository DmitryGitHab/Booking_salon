import enum


class UserRole(str, enum.Enum):
    CLIENT = "client"
    MASTER = "master"
    ADMIN = "admin"


class SlotStatus(str, enum.Enum):
    FREE = "free"              # мастер открыл, никто не забронировал
    PENDING_PAYMENT = "pending_payment"  # забронирован, ждём оплату
    BOOKED = "booked"          # оплачен и подтверждён
    CANCELLED = "cancelled"    # бронь отменили -> слот снова свободен (создаётся новый FREE слот, старый архивируется)


class BookingStatus(str, enum.Enum):
    PENDING_PAYMENT = "pending_payment"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"        # не оплатили вовремя
    REFUNDED = "refunded"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"
