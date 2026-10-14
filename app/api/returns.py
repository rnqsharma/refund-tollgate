import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Response, status

from app.api.deps import CustomerIdDep, QueueDep, SessionDep
from app.domain.schemas import ReturnCreate, ReturnRead
from app.services import returns as service

log = logging.getLogger(__name__)
router = APIRouter(prefix="/returns", tags=["returns"])


@router.post(
    "",
    response_model=ReturnRead,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        200: {"description": "Replay of an earlier request with the same Idempotency-Key"},
        404: {"description": "Order item not found"},
        409: {"description": "Idempotency-Key reused with a different body"},
    },
)
async def create_return(
    body: ReturnCreate,
    response: Response,
    # Declared as idempotency_key, FastAPI reads the "Idempotency-Key" header.
    idempotency_key: Annotated[str, Header(min_length=8, max_length=128)],
    customer_id: CustomerIdDep,
    session: SessionDep,
    queue: QueueDep,
):
    """Accept a return. It is decided asynchronously, so this answers 202, not 201."""
    try:
        row, created = await service.create_return(session, customer_id, idempotency_key, body)
    except service.OrderItemNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order item not found")
    except service.IdempotencyConflict:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Idempotency-Key was already used with a different request"
        )

    if not created:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replay"] = "true"
        return row

    try:
        await queue.enqueue_return(row.id)
    except Exception:
        # The return is already saved as `received`. A sweeper (a later step) re-enqueues
        # stuck returns, so the customer still gets a successful answer.
        log.exception("enqueue failed for return %s; it stays 'received' for the sweeper", row.id)
    return row


@router.get("/{return_id}", response_model=ReturnRead)
async def read_return(return_id: UUID, customer_id: CustomerIdDep, session: SessionDep):
    row = await service.get_return(session, customer_id, return_id)
    if row is None:
        # 404 for "not yours" as well, so IDs of other customers' returns are not revealed.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Return not found")
    return row
