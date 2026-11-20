"""Pydantic models for what the translator writes to mapping.json (see docs/contracts.md)."""

from typing import Any, Literal

from pydantic import BaseModel, Field

Status = Literal["auto", "partial", "manual", "unsupported"]
Via = Literal["terraform", "finalize", "runbook", "report"]


class Cost(BaseModel):
    aws: float | None = None
    leaseweb: float | None = None
    # true when a price came from an estimate, not a real price list
    aws_estimated: bool = False
    leaseweb_estimated: bool = False


class Alternative(BaseModel):
    """What the translator agent proposes for a resource with no leaseweb equivalent."""

    name: str
    effort: Literal["low", "medium", "high"]
    manual_steps: list[str] = Field(default_factory=list, max_length=8)
    confidence: float = Field(ge=0, le=1)


class MappingEntry(BaseModel):
    source_id: str
    source_type: str
    source_name: str | None = None
    # terraform-safe name, also used by finalize.json to refer to resources
    tf_name: str | None = None
    status: Status
    via: Via
    target: dict[str, Any] | None = None
    alternative: Alternative | None = None
    justification: str
    ai_suggested: bool = False
    monthly_cost_eur: Cost = Field(default_factory=Cost)
    notes: list[str] = Field(default_factory=list)


class Mapping(BaseModel):
    generated_at: str
    target_region: str
    catalog_source: str
    ai: dict[str, Any] = Field(default_factory=dict)
    entries: list[MappingEntry]
