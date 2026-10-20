from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ReturnRequest, OrderItem, Order


async def get_with_item(
    session: AsyncSession, return_id: UUID
) -> tuple[ReturnRequest, OrderItem, Order] | None:
    return None


async def claim_for_processing(session: AsyncSession, return_id: UUID) -> bool:
    return False