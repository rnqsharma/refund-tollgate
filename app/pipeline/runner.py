"""The pipeline runner: runs stages in order, checkpoints each one, and fails closed.

Guarantees:
  * Resumable. A stage that has a succeeded row in run_steps is never run again, so a crashed
    or retried job continues at the first unfinished stage.
  * Atomic. A stage's result, and the status change it asks for, commit together or not at all.
  * Fail closed. A stage that keeps failing, or a pipeline that ends without a decision, sends
    the return to human review. Nothing in here can approve a refund by accident.
  * Safe under duplicates. Two workers on the same return cannot write two results for a stage
    (the database refuses the second), though both may spend time computing it.
"""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.clock import as_utc, utcnow
from app.domain.enums import ReturnStatus
from app.pipeline.types import CaseView, Halt, ItemFacts, Stage, StageContext, stable_hash, StageMeta
from app.repository import returns as returns_repo
from app.repository import run_steps as steps_repo

log = logging.getLogger(__name__)

FINALIZE = "finalize"  # pseudo-stage that records how and why a run ended

DEFAULT_FALLTHROUGH = Halt(
    ReturnStatus.AWAITING_REVIEW, "pipeline finished without any stage making a decision"
)

def _meta_columns(meta: StageMeta | None) -> dict[str, Any]:
    if meta is None:
        return {}
    return {
        "model": meta.model,
        "prompt_version": meta.prompt_version,
        "tokens_in": meta.tokens_in,
        "tokens_out": meta.tokens_out,
    }


class ReturnNotFound(Exception):
    pass


@dataclass(frozen=True)
class RunResult:
    # finished  - the return reached a status chosen by a stage or the fallthrough
    # skipped   - nothing to do: the return was already decided (duplicate or late job)
    # retry     - a stage failed but has attempts left; call run() again after a delay
    # escalated - a stage kept failing, so the return was sent to human review
    outcome: Literal["finished", "skipped", "retry", "escalated"]
    status: ReturnStatus
    failed_stage: str | None = None
    attempts: int = 0


class PipelineRunner:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        stages: Sequence[Stage],
        *,
        max_attempts: int = 3,
        fallthrough: Halt = DEFAULT_FALLTHROUGH,
    ) -> None:
        names = [s.name for s in stages]
        if len(set(names)) != len(names) or FINALIZE in names:
            raise ValueError(f"stage names must be unique and not {FINALIZE!r}: {names}")
        self._sm = sessionmaker
        self._stages = list(stages)
        self._max_attempts = max_attempts
        self._fallthrough = fallthrough

    # ------------------------------------------------------------------ public API

    async def run(self, return_id: UUID) -> RunResult:
        case, outputs = await self._start(return_id)
        if case is None:
            async with self._sm() as s:
                current = await returns_repo.get(s, return_id)
            return RunResult("skipped", current.status)

        for stage in self._stages:
            if stage.name in outputs:
                continue  # checkpoint hit: done on an earlier run

            result = await self._run_stage(stage, case, outputs)
            if result is not None:
                return result

        return await self._finish(return_id, self._fallthrough)

    # --------------------------------------------------------------------- internals

    async def _start(self, return_id: UUID) -> tuple[CaseView | None, dict[str, dict[str, Any]]]:
        """Claim the return and load what earlier runs already finished."""
        async with self._sm() as s:
            loaded = await returns_repo.get_with_item(s, return_id)
            if loaded is None:
                raise ReturnNotFound(str(return_id))
            ret, item, _order = loaded

            if not await returns_repo.claim_for_processing(s, return_id):
                await s.rollback()
                return None, {}

            done = await steps_repo.succeeded_by_stage(s, return_id)
            case = CaseView(
                return_id=ret.id,
                customer_id=ret.customer_id,
                created_at=as_utc(ret.created_at),
                item=ItemFacts(
                    id=item.id,
                    sku=item.sku,
                    name=item.name,
                    price=item.price,
                    paid_amount=item.paid_amount,
                    delivered_at=as_utc(item.delivered_at) if item.delivered_at else None,
                ),
                reason_text=ret.reason_text,
            )
            await s.commit()

        known = {st.name for st in self._stages}
        return case, {name: step.output_json or {} for name, step in done.items() if name in known}

    async def _run_stage(
        self, stage: Stage, case: CaseView, outputs: dict[str, dict[str, Any]]
    ) -> RunResult | None:
        """Run one stage. Returns a RunResult if the run should stop, else None to continue."""
        # Build the exact view this stage is allowed to see, and hash what it saw.
        view = case.model_copy(
            update={
                "outputs": dict(outputs),
                "reason_text": case.reason_text if stage.sees_raw_text else None,
            }
        )
        input_hash = stable_hash(view)
        started = utcnow()

        try:
            async with self._sm() as read_session:
                async with asyncio.timeout(stage.timeout_s):
                    outcome = await stage.run(StageContext(case=view, session=read_session))
            output_json = outcome.output.model_dump(mode="json")
        except Exception as exc:  # noqa: BLE001 - any stage failure is handled the same way
            return await self._on_failure(stage, case, input_hash, started, exc)

        async with self._sm() as s:
            try:
                await steps_repo.record_success(
                    s,
                    return_id=case.return_id,
                    stage=stage.name,
                    input_hash=input_hash,
                    output=output_json,
                    started_at=started,
                    finished_at=utcnow(),
                )
                if outcome.halt is not None:
                    await self._record_halt(s, case.return_id, outcome.halt)
                await s.commit()
            except IntegrityError:
                # Another worker already finished this stage (or the whole run). Their result
                # stands; ours is discarded.
                await s.rollback()
                return await self._adopt_winner(s, stage, case.return_id, outputs)

        outputs[stage.name] = output_json
        if outcome.halt is not None:
            log.info("return %s halted at %s -> %s", case.return_id, stage.name, outcome.halt.status)
            return RunResult("finished", outcome.halt.status)
        return None

    async def _on_failure(
        self, stage: Stage, case: CaseView, input_hash: str, started, exc: BaseException
    ) -> RunResult:
        error = f"{type(exc).__name__}: {exc}"
        log.warning("return %s stage %s failed: %s", case.return_id, stage.name, error)

        async with self._sm() as s:
            await steps_repo.record_failure(
                s,
                return_id=case.return_id,
                stage=stage.name,
                input_hash=input_hash,
                error=error,
                started_at=started,
                finished_at=utcnow(),
            )
            attempts = await steps_repo.failure_count(s, case.return_id, stage.name)

            if attempts < self._max_attempts:
                await s.commit()
                return RunResult(
                    "retry", ReturnStatus.PROCESSING, failed_stage=stage.name, attempts=attempts
                )

            # Out of attempts: fail closed, to a human.
            halt = Halt(
                ReturnStatus.AWAITING_REVIEW,
                f"stage {stage.name!r} failed {attempts} times; last error: {error}",
            )
            try:
                await self._record_halt(s, case.return_id, halt)
                await s.commit()
            except IntegrityError:
                await s.rollback()  # someone else already finalized this return
            current = await returns_repo.get(s, case.return_id)
        return RunResult(
            "escalated", current.status, failed_stage=stage.name, attempts=attempts
        )

    async def _finish(self, return_id: UUID, halt: Halt) -> RunResult:
        """End a run that no stage halted, using the fail-closed fallthrough."""
        async with self._sm() as s:
            try:
                await self._record_halt(s, return_id, halt)
                await s.commit()
            except IntegrityError:
                await s.rollback()
            current = await returns_repo.get(s, return_id)
        return RunResult("finished", current.status)

    async def _record_halt(self, s: AsyncSession, return_id: UUID, halt: Halt) -> None:
        """Write the 'finalize' audit row and move the status. The caller commits."""
        now = utcnow()
        payload = {"status": halt.status.value, "reason": halt.reason}
        await steps_repo.record_success(
            s,
            return_id=return_id,
            stage=FINALIZE,
            input_hash=stable_hash(payload),
            output=payload,
            started_at=now,
            finished_at=now,
        )
        await returns_repo.transition(
            s, return_id, halt.status, from_=[ReturnStatus.PROCESSING]
        )

    async def _adopt_winner(
        self, s: AsyncSession, stage: Stage, return_id: UUID, outputs: dict[str, dict[str, Any]]
    ) -> RunResult | None:
        done = await steps_repo.succeeded_by_stage(s, return_id)
        winner = done.get(stage.name)
        current = await returns_repo.get(s, return_id)
        if current.status != ReturnStatus.PROCESSING:
            return RunResult("skipped", current.status)
        if winner is None:  # the conflict was not about this stage; do not hide it
            raise RuntimeError(f"integrity error for {stage.name!r} with no winning step")
        outputs[stage.name] = winner.output_json or {}
        return None