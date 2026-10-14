"""API-facing Pydantic models. These are the contract with clients, not the DB rows."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ReturnStatus


class ReturnCreate(BaseModel):
    # extra="forbid": unknown fields are a client bug, so reject them instead of ignoring them.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    order_item_id: UUID
    # Untrusted free text. It is stored as-is and only ever treated as data downstream.
    reason_text: str = Field(min_length=10, max_length=2000)


class ReturnRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_item_id: UUID
    status: ReturnStatus
    reason_text: str
    created_at: datetime
