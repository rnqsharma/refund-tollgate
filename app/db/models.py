import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Enum, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, Uuid, Integer, text, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.enums import ReturnStatus, StepStatus

JsonType = JSON().with_variant(JSONB(), "postgresql")

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


class RunStep(Base):
    """One execution of one pipeline stage for one return.

    This table is the pipeline's checkpoint: a stage with a SUCCEEDED row is never re-run, so a
    crashed run resumes at the first stage without one. It is also the audit/replay record, so
    LLM stages will fill in the model, prompt and token columns (they stay NULL for
    deterministic stages).
    """

    __tablename__ = "run_steps"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    return_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("returns.id"), index=True)
    stage: Mapped[str] = mapped_column(String(64))
    status: Mapped[StepStatus] = mapped_column(
        Enum(
            StepStatus,
            native_enum=False,
            length=16,
            values_callable=lambda e: [m.value for m in e],
        )
    )
    # Hash of the stage's input, so a replay can tell whether the input changed.
    input_hash: Mapped[str] = mapped_column(String(64))
    output_json: Mapped[dict | None] = mapped_column(JsonType, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)

    model: Mapped[str | None] = mapped_column(String(100), default=None)
    prompt_version: Mapped[str | None] = mapped_column(String(64), default=None)
    tokens_in: Mapped[int | None] = mapped_column(Integer, default=None)
    tokens_out: Mapped[int | None] = mapped_column(Integer, default=None)

    started_at: Mapped[datetime] = mapped_column(default=_now)
    finished_at: Mapped[datetime] = mapped_column(default=_now)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        # At most one SUCCEEDED row per stage per return, enforced by the database. Failed
        # attempts may repeat. This is what makes a duplicate or racing worker harmless: the
        # second one to finish a stage hits this index instead of writing a second result.
        Index(
            "uq_run_steps_one_success",
            "return_id",
            "stage",
            unique=True,
            postgresql_where=text("status = 'succeeded'"),
            sqlite_where=text("status = 'succeeded'"),
        ),
    )