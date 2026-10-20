from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RunStep
from app.domain.enums import StepStatus


async def record_success(
    session: AsyncSession,
    *,
    return_id: UUID,
    stage: str,
    input_hash: str,
    output: dict[str, Any],
    started_at: datetime,
    finished_at: datetime,
    model: str | None = None,
    prompt_version: str | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
) -> RunStep:
    """Save a stage's result. Raises IntegrityError (on flush) if this stage already succeeded
    for this return, which is how a duplicate worker is stopped from writing a second result."""
    step = RunStep(
        return_id=return_id,
        stage=stage,
        status=StepStatus.SUCCEEDED,
        input_hash=input_hash,
        output_json=output,
        started_at=started_at,
        finished_at=finished_at,
        latency_ms=int((finished_at - started_at).total_seconds() * 1000),
        model=model,
        prompt_version=prompt_version,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
    session.add(step)
    await session.flush()
    return step

async def record_failure(
    session: AsyncSession,
    *,
    return_id: UUID,
    stage: str,
    input_hash: str,
    error: str,
    started_at: datetime,
    finished_at: datetime,
) -> RunStep:
    step = RunStep(
        return_id=return_id,
        stage=stage,
        status=StepStatus.FAILED,
        input_hash=input_hash,
        error=error[:4000],  # a stack trace should not be able to bloat the row
        started_at=started_at,
        finished_at=finished_at,
        latency_ms=int((finished_at - started_at).total_seconds() * 1000),
    )
    session.add(step)
    await session.flush()
    return step

async def succeeded_by_stage(session: AsyncSession, return_id: UUID) -> dict[str, RunStep]:
    """Completed stages for a return, keyed by stage name. This is the resume checkpoint."""
    rows = await session.scalars(
        select(RunStep).where(
            RunStep.return_id == return_id, RunStep.status == StepStatus.SUCCEEDED
        )
    )
    return {step.stage: step for step in rows}