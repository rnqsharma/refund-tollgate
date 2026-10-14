"""Dev helper: create tables and insert one customer with one delivered order item.

Run with: python -m app.seed
(Alembic migrations replace create_all later.)
"""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import Base, Customer, Order, OrderItem


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        customer = Customer()
        session.add(customer)
        await session.flush()
        order = Order(customer_id=customer.id)
        session.add(order)
        await session.flush()
        item = OrderItem(
            order_id=order.id,
            sku="HEADPHONES-001",
            name="Wireless headphones",
            price=Decimal("129.99"),
            paid_amount=Decimal("129.99"),
            delivered_at=datetime.now(UTC) - timedelta(days=5),
        )
        session.add(item)
        await session.commit()

    print(f"customer_id   = {customer.id}")
    print(f"order_item_id = {item.id}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
