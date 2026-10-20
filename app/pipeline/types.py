import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol, ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import ReturnStatus

HALTABLE = frozenset(
    {ReturnStatus.REJECTED, ReturnStatus.AUTO_APPROVED, ReturnStatus.AWAITING_REVIEW}
)

class ItemFacts(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    sku: str
    name: str
    price: Decimal
    paid_amount: Decimal
    delivered_at: datetime | None

class CaseView(BaseModel):
    model_config = ConfigDict(frozen=True)

    return_id: UUID
    customer_id: UUID
    created_at: datetime
    item: ItemFacts
    reason_text: str | None
    outputs: dict[str, dict[str, Any]] = {}

@dataclass(frozen=True)
class Halt:
    status: ReturnStatus
    reason: str

    def __post_init__(self) -> None:
        if self.status not in HALTABLE:
            raise ValueError(f"a stage cannot halt a return in status {self.status.value!r}")

@dataclass(frozen=True)
class StageMeta:
    """What a model-based stage reports about its call, stored on its run_steps row."""

    model: str | None = None
    prompt_version: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None

@dataclass
class StageOutcome:
    output: BaseModel
    halt: Halt | None = None
    meta: StageMeta | None = None

@dataclass
class StageContext:
    case: CaseView
    # For read-only lookups (for example "is there another open return for this item?").
    # The runner, not the stage, writes results and commits.
    session: AsyncSession

class Stage(Protocol):
    name: ClassVar[str]
    timeout_s: ClassVar[float]
    sees_raw_text: ClassVar[bool]

    async def run(self, ctx: StageContext) -> StageOutcome: ...

def stable_hash(value: Any) -> str:
    """SHA-256 of a canonical JSON form. Same input, same hash, on any machine."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()
