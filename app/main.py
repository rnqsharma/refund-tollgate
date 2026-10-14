from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.api import returns
from app.config import get_settings
from app.jobs import ArqJobQueue, JobQueue


def create_app(*, engine: AsyncEngine | None = None, queue: JobQueue | None = None) -> FastAPI:
    """App factory. Tests pass their own engine and queue; production passes neither.

    Run with: uvicorn app.main:create_app --factory
    """
    settings = get_settings()
    engine = engine or create_async_engine(settings.database_url, pool_pre_ping=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.queue is None:
            app.state.queue = await ArqJobQueue.connect(settings.redis_url)
        yield
        await app.state.queue.close()
        await engine.dispose()

    app = FastAPI(title="refund-tollgate", lifespan=lifespan)
    # expire_on_commit=False keeps row attributes readable after commit without a refresh.
    app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    app.state.queue = queue
    app.include_router(returns.router)

    @app.get("/healthz")
    async def healthz():
        async with app.state.sessionmaker() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok"}

    return app
