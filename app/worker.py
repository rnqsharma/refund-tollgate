"""The arq worker. Run it with:  arq app.worker.WorkerSettings

The API enqueues `process_return(return_id)`. This function hands the id to the pipeline
runner, which does all the real work and decides what happens to the return.
"""

import logging
from typing import Any
from uuid import UUID

from arq import Retry
from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.llm.factory import build_llm_client, LLMNotConfigured
from app.pipeline.registry import build_runner
from app.pipeline.runner import PipelineRunner, ReturnNotFound

log = logging.getLogger(__name__)


def retry_delay_seconds(attempts: int) -> int:
    """Back off between attempts of a failing stage: 10s, 20s, 40s... capped at two minutes."""
    return min(5 * 2**attempts, 120)


async def process_return(ctx: dict[str, Any], return_id: str) -> str:
    runner: PipelineRunner = ctx["runner"]
    try:
        result = await runner.run(UUID(return_id))
    except ReturnNotFound:
        # Retrying cannot make a missing row appear, so drop the job instead of looping.
        log.error("process_return: return %s does not exist; dropping job", return_id)
        return "not_found"

    if result.outcome == "retry":
        delay = retry_delay_seconds(result.attempts)
        log.warning(
            "return %s: stage %s failed (attempt %d); retrying in %ds",
            return_id, result.failed_stage, result.attempts, delay,
        )
        raise Retry(defer=delay)

    log.info("return %s: %s -> %s", return_id, result.outcome, result.status.value)
    return result.status.value


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    ctx["engine"] = engine
    try:
        llm = build_llm_client(settings)
    except LLMNotConfigured as exc:
        log.warning("%s", exc)
        llm = None
    ctx["llm"] = llm
    ctx["runner"] = build_runner(
        async_sessionmaker(engine, expire_on_commit=False), settings
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    if ctx.get("llm") is not None:
        await ctx["llm"].aclose()
    await ctx["engine"].dispose()


class WorkerSettings:
    # arq reads only the attributes defined directly on this class. A subclass that inherits
    # them silently ends up with no functions, so redefine every setting if you subclass.
    functions = [process_return]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    # The runner escalates a return to human review after `stage_max_attempts` failures of one
    # stage, so arq's own limit is only a safety net and must sit comfortably above that.
    max_tries = 10
    # One return should never need more than this in total, whatever the stages do.
    job_timeout = 300
