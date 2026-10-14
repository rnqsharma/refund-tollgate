from uuid import UUID

class JobQueue(Protocol):
    async def enqueue_return(self, return_id: UUID) -> None: ...

    async def close(self) -> None: ...


class ArqJobQueue:

    def __init__(self, pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, redis_url: str) -> "ArqJobQueue":
        # Imported lazily so tests and tools that never touch Redis do not need arq loaded.
        from arq import create_pool
        from arq.connections import RedisSettings

        return cls(await create_pool(RedisSettings.from_dsn(redis_url)))

    async def enqueue_return(self, return_id: UUID) -> None:
        # A fixed _job_id makes arq ignore a second enqueue of the same return.
        await self._pool.enqueue_job("process_return", str(return_id), _job_id=f"return:{return_id}")

    async def close(self) -> None:
        await self._pool.aclose()

class InMemoryJobQueue:
    """Records jobs in a list. Used by tests and for running the API without Redis."""

    def __init__(self) -> None:
        self.jobs: list[UUID] = []

    async def enqueue_return(self, return_id: UUID) -> None:
        self.jobs.append(return_id)

    async def close(self) -> None:
        return None