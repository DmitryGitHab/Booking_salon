"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-02

"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("role", sa.Enum("client", "master", "admin", name="userrole"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "master_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("bio", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "services",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("master_id", sa.Uuid(), sa.ForeignKey("master_profiles.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "slots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("master_id", sa.Uuid(), sa.ForeignKey("master_profiles.id"), nullable=False),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("free", "pending_payment", "booked", "cancelled", name="slotstatus"),
            nullable=False,
            server_default="free",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("master_id", "start_time", "end_time", name="uq_master_slot_interval"),
    )
    op.create_index("ix_slots_start_time", "slots", ["start_time"])
    op.create_index("ix_slots_status", "slots", ["status"])

    op.create_table(
        "bookings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("client_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("slot_id", sa.Uuid(), sa.ForeignKey("slots.id"), nullable=False, unique=True),
        sa.Column("service_id", sa.Uuid(), sa.ForeignKey("services.id"), nullable=False),
        sa.Column("price_at_booking", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending_payment", "confirmed", "cancelled", "expired", "refunded", name="bookingstatus"),
            nullable=False,
            server_default="pending_payment",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_bookings_status", "bookings", ["status"])

    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("booking_id", sa.Uuid(), sa.ForeignKey("bookings.id"), nullable=False, unique=True),
        sa.Column("stripe_payment_intent_id", sa.String(255), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "succeeded", "failed", "refunded", name="paymentstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("payments")
    op.drop_table("bookings")
    op.drop_table("slots")
    op.drop_table("services")
    op.drop_table("master_profiles")
    op.drop_table("users")
