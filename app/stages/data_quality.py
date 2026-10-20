from datetime import timedelta
from decimal import Decimal
from typing import ClassVar, Literal
from pydantic import BaseModel, ConfigDict

from app.domain.clock import utcnow
from app.domain.enums import ReturnStatus
from app.pipeline.types import StageContext, StageOutcome, Halt

IssueCode = Literal[
    "not_delivered",
    "invalid_delivery_date",
    "outside_return_window",
    "nothing_paid",
    "duplicate_return"
]

class QualityIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: IssueCode
    message: str

class QualityReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    passed: bool
    issues: list[QualityIssue]

class DataQualityStage:
    name: ClassVar[str] = "data_quality"
    timeout_s: ClassVar[float] = 10.0

    sees_raw_text: ClassVar[bool] = False

    def __init__(self, *, window_days: int = 30) -> None:
        self._window = timedelta(days=window_days)
        self._window_days = window_days

    async def run(self, ctx: StageContext) -> StageOutcome:
        case = ctx.case
        item = case.item
        issues: list[QualityIssue] = []
        now = utcnow()

        if item.delivered_at is None:
            issues.append(QualityIssue(code="not_delivered", message="The item has not been delivered."))
        elif item.delivered_at > now:
            issues.append(
                QualityIssue(
                    code="invalid_delivery_date", message="The recorded delivery date is in the future."
                )
            )
        elif now - item.delivered_at > self._window:
            issues.append(
                QualityIssue(
                    code="outside_return_window",
                    message=f"Delivered more than {self._window_days} days ago.",
                )
            )

        if item.paid_amount <= Decimal("0"):
            issues.append(QualityIssue(code="nothing_paid", message="Nothing was paid for this item."))

        if await returns_repo.has_earlier_active_return(
            ctx.session,
            return_id=case.return_id,
            order_item_id=item.id,
            created_at=case.created_at,
        ):
            issues.append(
                QualityIssue(
                    code="duplicate_return",
                    message="An earlier return for this item is already in progress or granted.",
                )
            )

        report = QualityReport(passed=not issues, issues=issues)
        if report.passed:
            return StageOutcome(output=report)

        reason = "; ".join(i.message for i in issues)
        return StageOutcome(output=report, halt=Halt(ReturnStatus.REJECTED, reason))