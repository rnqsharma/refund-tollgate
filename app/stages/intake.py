from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from app.domain.contracts import Claim
from app.domain.enums import ReturnStatus
from app.llm.client import LLMClient
from app.llm.prompts import Prompt
from app.llm.structured import run_structured
from app.llm.types import StructuredOutputError
from app.pipeline.types import StageContext, StageOutcome, Halt, StageMeta, CaseView

_OPEN, _CLOSE = "<customer_text>", "</customer_text>"

_MAX_TEXT = 4000

class IntakeFailed(BaseModel):
    """Stored in place of a Claim when the model never produced a valid one."""

    model_config = ConfigDict(frozen=True)

    reason: str
    attempts: int

def render_case(case: CaseView, reason_text: str) -> str:
    """The user message: trusted order facts first, then the untrusted text in tags."""
    item = case.item
    delivered = item.delivered_at.date().isoformat() if item.delivered_at else "not recorded"
    # A customer must not be able to close the tag early and write outside it.
    safe_text = reason_text[:_MAX_TEXT].replace(_CLOSE, "[removed]").replace(_OPEN, "[removed]")
    return (
        "Order facts:\n"
        f"- item: {item.name} (sku {item.sku})\n"
        f"- price: {item.price}, paid: {item.paid_amount}\n"
        f"- delivered: {delivered}\n"
        f"- request created: {case.created_at.date().isoformat()}\n\n"
        f"{_OPEN}\n{safe_text}\n{_CLOSE}"
    )


class IntakeStage(BaseModel):
    name: ClassVar[str] = "intake"
    # Up to three model calls (one answer, two repairs), possibly across two providers.
    timeout_s: ClassVar[float] = 120.0
    sees_raw_text: ClassVar[bool] = True

    def __init__(self, *, client: LLMClient, prompt: Prompt, model: str | None = None) -> None:
        self._client = client
        self._prompt = prompt
        self._model = model

    async def run(self, ctx: StageContext) -> StageOutcome:
        text = ctx.case.reason_text
        if text is None:
            # The runner hides the text from stages that do not declare they need it. Getting
            # None here means the runner and this stage disagree, which is a bug to surface.
            raise RuntimeError("intake ran without the customer's text")

        try:
            result = await run_structured(
                self._client,
                Claim,
                system=self._prompt.text,
                user=render_case(ctx.case, text),
                model=self._model,
                max_tokens=512,
            )
        except StructuredOutputError as exc:
            # A model that fails the schema three times in a row will not do better on a
            # fourth attempt at temperature 0. Hand the case to a person instead of retrying.
            return StageOutcome(
                output=IntakeFailed(reason="model output never matched the schema", attempts=exc.attempts),
                halt=Halt(
                    ReturnStatus.AWAITING_REVIEW,
                    f"intake could not read the request after {exc.attempts} attempts",
                ),
                meta=StageMeta(
                    prompt_version=self._prompt.label,
                    tokens_in=exc.usage.tokens_in,
                    tokens_out=exc.usage.tokens_out,
                ),
            )

        claim = result.value
        meta = StageMeta(
            model=result.model,
            prompt_version=self._prompt.label,
            tokens_in=result.usage.tokens_in,
            tokens_out=result.usage.tokens_out,
        )
        if claim.injection_suspected:
            return StageOutcome(
                output=claim,
                halt=Halt(
                    ReturnStatus.AWAITING_REVIEW,
                    "the customer's text appears to contain instructions aimed at the system",
                ),
                meta=meta,
            )
        return StageOutcome(output=claim, meta=meta)

