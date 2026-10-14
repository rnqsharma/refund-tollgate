"""Business logic for creating and reading returns. No HTTP types in here."""

import hashlib
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Order, OrderItem, ReturnRequest
from app.domain.schemas import ReturnCreate


class OrderItemNotFound(Exception):
    """The item does not exist, or does not belong to this customer."""


class IdempotencyConflict(Exception):
    """The Idempotency-Key was already used with a different request body."""


def hash_request(body: ReturnCreate) -> str:
    canonical = json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _find_by_key(session: AsyncSession, customer_id: UUID, key: str) -> ReturnRequest | None:
    return await session.scalar(
        select(ReturnRequest).where(
            ReturnRequest.customer_id == customer_id,
            ReturnRequest.idempotency_key == key,
        )
    )


def _replay(existing: ReturnRequest, request_hash: str) -> tuple[ReturnRequest, bool]:
    if existing.request_hash != request_hash:
        raise IdempotencyConflict
    return existing, False


async def create_return(
    session: AsyncSession, customer_id: UUID, idempotency_key: str, body: ReturnCreate
) -> tuple[ReturnRequest, bool]:
    """Create a return, or replay the earlier result for the same key.

    Returns (return, created). `created` is False when this was a replay.
    """
    request_hash = hash_request(body)

    # 1. A repeated key replays the original result and never starts a second run.
    existing = await _find_by_key(session, customer_id, idempotency_key)
    if existing is not None:
        return _replay(existing, request_hash)

    # 2. The item must exist and belong to this customer. Both failures look identical
    #    to the caller, so the API does not reveal which item IDs exist.
    item = await session.scalar(
        select(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .where(OrderItem.id == body.order_item_id, Order.customer_id == customer_id)
    )
    if item is None:
        raise OrderItemNotFound

    # 3. Insert. If two requests with the same key race, the unique constraint lets
    #    exactly one win; the loser re-reads the winner's row and replays it.
    row = ReturnRequest(
        customer_id=customer_id,
        order_item_id=item.id,
        reason_text=body.reason_text,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await _find_by_key(session, customer_id, idempotency_key)
        if existing is None:
            raise  # a different integrity error, such as a bad foreign key
        return _replay(existing, request_hash)
    return row, True


async def get_return(session: AsyncSession, customer_id: UUID, return_id: UUID) -> ReturnRequest | None:
    """Fetch a return only if it belongs to the customer."""
    return await session.scalar(
        select(ReturnRequest).where(
            ReturnRequest.id == return_id, ReturnRequest.customer_id == customer_id
        )
    )
