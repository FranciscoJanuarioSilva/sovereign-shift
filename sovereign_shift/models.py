"""Shared validation for the downstream file boundaries."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)


class Relation(Contract):
    type: str
    target: str


class Resource(Contract):
    id: str = Field(min_length=1)
    type: str
    properties: dict = Field(default_factory=dict)
    relations: list[Relation] = Field(default_factory=list)


class Inventory(Contract):
    resources: list[Resource]


class Entry(Contract):
    source_id: str
    source_type: str
    status: Literal["auto", "partial", "manual", "unsupported"]
    via: Literal["terraform", "finalize", "runbook", "report"]
    target: dict | None = None


class Mapping(Contract):
    target_region: str
    entries: list[Entry]


class Node(Contract):
    id: str
    type: str
    name: str


class Edge(Contract):
    model_config = ConfigDict(extra="allow", strict=True, populate_by_name=True)
    source: str = Field(alias="from")
    to: str
    type: str


class Graph(Contract):
    nodes: list[Node]
    edges: list[Edge]


class Findings(Contract):
    findings: list[dict]


class Finalize(Contract):
    api: Literal["https://api.leaseweb.com/publicCloud/v1"]
    security_groups: list[dict]
    target_registrations: list[dict]


class Runbook(Contract):
    generated_by: Literal["ai", "template-default"]
    entries: list[dict]


class Report(Contract):
    source: dict
    target: dict
    cost: dict
    graph: dict
    work: list[dict]
    findings: list[dict]
    runbook: dict
    terraform_files: list[str]


CONTRACTS = dict(
    inventory=Inventory,
    mapping=Mapping,
    graph=Graph,
    findings=Findings,
    finalize=Finalize,
    runbook=Runbook,
    report=Report,
)
