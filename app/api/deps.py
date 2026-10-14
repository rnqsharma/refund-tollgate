from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs import JobQueue

async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def get_queue(request: Request) -> JobQueue:
    return request.app.state.queue


def get_customer_id(x_customer_id: Annotated[UUID, Header()]) -> UUID:
    """Stand-in for authentication.

    v1 trusts an X-Customer-Id header. Later this becomes "verify the JWT and return its
    subject", and nothing else in the API changes because everything depends on this function.
    """
    return x_customer_id


SessionDep = Annotated[AsyncSession, Depends(get_session)]
QueueDep = Annotated[JobQueue, Depends(get_queue)]
CustomerIdDep = Annotated[UUID, Depends(get_customer_id)]


