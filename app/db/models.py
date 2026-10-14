import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Enum, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.enums import ReturnStatus


def _now() -> datetime:
    return datetime.now(UTC)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    placed_at: Mapped[datetime] = mapped_column(default=_now)


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    sku: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    # Money is NUMERIC, never float.
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    delivered_at: Mapped[datetime | None] = mapped_column(default=None)


class ReturnRequest(Base):
    __tablename__ = "returns"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    order_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("order_items.id"))
    status: Mapped[ReturnStatus] = mapped_column(
        Enum(
            ReturnStatus,
            native_enum=False,
            length=32,
            values_callable=lambda e: [m.value for m in e],
        ),
        default=ReturnStatus.RECEIVED,
    )
    reason_text: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    # Hash of the request body, so a reused key with a different body can be detected.
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)

    __table_args__ = (
        # The database, not application code, is what makes idempotency safe under concurrency.
        UniqueConstraint("customer_id", "idempotency_key", name="uq_returns_customer_idem"),
        Index("ix_returns_status_created", "status", "created_at"),
    )
