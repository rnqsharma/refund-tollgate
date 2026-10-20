from enum import StrEnum


class ReturnStatus(StrEnum):
    """Lifecycle of a return. Mirrors the state machine in the design doc."""

    RECEIVED = "received"
    PROCESSING = "processing"
    REJECTED = "rejected"
    AUTO_APPROVED = "auto_approved"
    AWAITING_REVIEW = "awaiting_review"
    FAILED = "failed"
    APPROVED = "approved"
    DENIED = "denied"


FINAL_STATUSES = frozenset(
    {
        ReturnStatus.REJECTED,
        ReturnStatus.AUTO_APPROVED,
        ReturnStatus.APPROVED,
        ReturnStatus.DENIED,
    }
)

class StepStatus(StrEnum):
    """Outcome of one execution of one pipeline stage."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"