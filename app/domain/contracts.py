"""The typed outputs that model-based stages hand to each other.

Every model reply is validated against one of these before anything else sees it, and none
may carry fields the schema does not list.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ReasonCategory = Literal[
    "defective",
    "damaged_in_transit",
    "not_as_described",
    "wrong_item",
    "missing_parts",
    "late_delivery",
    "changed_mind",
    "other",
]

# Short on purpose: these strings are produced from untrusted customer text and are read by
# later stages, so they stay bounded and are treated as data, never as instructions.
ShortText = Annotated[str, StringConstraints(max_length=200)]


class Claim(BaseModel):
    """What the customer says is wrong, as the Intake stage understood it."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    reason_category: ReasonCategory
    claimed_defect: ShortText | None
    contradictions: Annotated[list[ShortText], Field(max_length=5)]
    injection_suspected: bool
    confidence: Annotated[float, Field(ge=0, le=1)]
