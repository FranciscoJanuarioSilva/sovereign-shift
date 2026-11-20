"""inventory.json (+ graph) -> mapping.json: rules first, then the ai for what rules can't place."""

import json
import re
import sys
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from sovereign_shift.ai import AIClient, prompt, redact
from sovereign_shift.graph import build_graph
from sovereign_shift.translator.models import Alternative, Mapping, MappingEntry

from . import catalog
from .rules import RULES, Context, apply_alternative, unsupported

# what the ai is told leaseweb can host, so it proposes things that exist
LEASEWEB_CAPABILITIES = [
    "public cloud instances (vms, x86, 2 to 96 vcpu, ubuntu/debian/almalinux/windows)",
    "dedicated bare-metal servers",
    "load balancers (http, https, tcp) with target groups",
    "dns record sets (domain hosted at leaseweb)",
    "s3-compatible object storage",
    "managed kubernetes (control plane free, pay for nodes)",
    "private network between instances",
    "cdn",
    "no managed databases, queues, functions or serverless",
]


class AIAnswer(BaseModel):
    alternative: str = Field(min_length=3, max_length=200)
    justification: str = Field(min_length=10, max_length=600)
    effort: str
    manual_steps: list[str] = Field(default_factory=list, max_length=8)
    confidence: float = Field(ge=0, le=1)


def tf_names(resources: list[dict[str, Any]]) -> dict[str, str]:
    """Stable terraform-safe names, unique across the whole inventory."""
    names: dict[str, str] = {}
    used: set[str] = set()
    for r in sorted(resources, key=lambda x: (x["type"], x["id"])):
        label = r.get("name") or r["id"]
        p = r.get("properties") or {}
        if label.startswith("arn:"):
            # listeners have no name, so build one from the port, else the arn tail
            label = f"{r['type']}_{p['port']}" if p.get("port") else f"{r['type']}_{label.rsplit('/', 1)[-1][:8]}"
        if r["type"] == "route53_record":
            label = f"{label}_{p.get('record_type', p.get('type', ''))}"
        base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "res"
        if not base[0].isalpha():
            base = f"r_{base}"
        name, n = base, 2
        while name in used:
            name, n = f"{base}_{n}", n + 1
        used.add(name)
        names[r["id"]] = name
    return names


def region_mapper(override: str | None):
    info = catalog.regions()
    valid = set(catalog.schema_enums()["region"])

    def region_for(aws_region: str | None) -> str:
        if override:
            return override
        mapped = info["aws_to_leaseweb"].get(aws_region or "", info["default"])
        return mapped if mapped in valid else info["default"]

    return region_for


def db_clients(graph: dict[str, Any], resources: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Instance ids that reach each db, from graph edges plus the db's own sg source groups."""
    out: dict[str, set[str]] = {}
    for edge in graph.get("edges", []):
        if edge.get("type") in ("connects_to", "talks_to"):
            out.setdefault(edge["to"], set()).add(edge["from"])
    by_id = {r["id"]: r for r in resources}

    def groups_of(r: dict[str, Any]) -> set[str]:
        return {rel["target"] for rel in r.get("relations", []) if rel.get("type") == "uses_security_group"}

    # own inference too, so we don't depend on the graph using the same rule field names
    for db in (r for r in resources if r["type"] == "db_instance"):
        sources: set[str] = set()
        for group_id in groups_of(db):
            for rule in (by_id.get(group_id, {}).get("properties") or {}).get("ingress") or []:
                for g in rule.get("source_groups") or rule.get("security_groups") or []:
                    sources.add(g if isinstance(g, str) else g.get("GroupId"))
        for r in resources:
            if r["type"] == "ec2_instance" and groups_of(r) & sources:
                out.setdefault(db["id"], set()).add(r["id"])
    return out


def ai_payload(resource: dict[str, Any], ctx: Context) -> dict[str, Any]:
    neighbours = [
        {"type": o["type"], "aws_type": (o.get("properties") or {}).get("aws_type"), "name": o.get("name")}
        for o in ctx.related(resource) + ctx.referrers(resource["id"])
    ]
    if resource["type"].startswith("cloudflare_"):
        # binding types and topology are enough to suggest a replacement.
        return {"resource": {"type": resource["type"], "record_type": (resource.get("properties") or {}).get("record_type")},
                "neighbours": [{"type": item["type"]} for item in neighbours[:15]],
                "leaseweb_can_host": LEASEWEB_CAPABILITIES}
    return redact({
        "resource": {
            "type": resource["type"],
            "name": resource.get("name"),
            "region": resource.get("region"),
            "properties": resource.get("properties") or {},
            "tags": resource.get("tags") or {},
        },
        "neighbours": neighbours[:15],
        "leaseweb_can_host": LEASEWEB_CAPABILITIES,
    })


def ask_ai(client: AIClient, resource: dict[str, Any], ctx: Context) -> AIAnswer | None:
    user = json.dumps(ai_payload(resource, ctx), indent=1, sort_keys=True, default=str)
    answer = client.complete(prompt("translator"), user, AIAnswer)
    if answer and answer.effort.lower() not in ("low", "medium", "high"):
        answer.effort = "medium"
    return answer


def translate(
    inventory: dict[str, Any],
    graph: dict[str, Any] | None = None,
    target_region: str | None = None,
    ai: AIClient | None = None,
) -> Mapping:
    resources = inventory.get("resources")
    if not isinstance(resources, list):
        raise ValueError("inventory.resources must be a list")
    if target_region and target_region not in catalog.schema_enums()["region"]:
        raise ValueError(f"{target_region} isn't a leaseweb region: {', '.join(catalog.schema_enums()['region'])}")
    graph = graph or build_graph(inventory)
    region_for = region_mapper(target_region)
    ctx = Context(
        by_id={r["id"]: r for r in resources}, tf_names=tf_names(resources),
        region_for=region_for, target_region_override=target_region, db_clients=db_clients(graph, resources),
    )

    entries: list[MappingEntry] = []
    asked = answered = 0
    for resource in resources:
        rule = RULES.get(resource["type"], unsupported)
        result = rule(resource, ctx)
        if result.status == "unsupported" and ai is not None:
            asked += 1
            answer = ask_ai(ai, resource, ctx)
            if answer:
                answered += 1
                result = apply_alternative(
                    result,
                    Alternative(name=answer.alternative, effort=answer.effort.lower(),
                                manual_steps=answer.manual_steps, confidence=answer.confidence),
                    answer.justification,
                )
            else:
                result.notes.append("ai gave no valid suggestion, manual work")
        entries.append(result)

    regions = inventory.get("regions") or [r.get("region") for r in resources if r.get("region")]
    _, catalog_source = catalog.leaseweb_types()
    ai_info: dict[str, Any] = {"used": False}
    if ai is not None:
        ai_info = {**ai.info(), "used": True, "asked": asked, "answered": answered}
        if not ai.enabled:
            ai_info["disabled_reason"] = ai.why_disabled()
    return Mapping(
        source=inventory.get("source", "aws"),
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        target_region=target_region or region_for(regions[0] if regions else None),
        catalog_source=catalog_source,
        ai=ai_info,
        entries=entries,
    )


def summary(mapping: Mapping) -> str:
    counts: dict[str, int] = {}
    for e in mapping.entries:
        counts[e.status] = counts.get(e.status, 0) + 1
    # only rows priced on both sides, like the report
    both = [e for e in mapping.entries if e.monthly_cost_eur.aws is not None and e.monthly_cost_eur.leaseweb is not None]
    aws = sum(e.monthly_cost_eur.aws for e in both)
    lsw = sum(e.monthly_cost_eur.leaseweb for e in both)
    parts = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
    ai = mapping.ai
    ai_text = f", ai answered {ai.get('answered', 0)}/{ai.get('asked', 0)}" if ai.get("used") else ""
    if ai.get("disabled_reason"):
        ai_text += f" (ai off: {ai['disabled_reason']})"
    if mapping.source == "cloudflare":
        return f"{len(mapping.entries)} resources -> {mapping.target_region}: {parts}{ai_text}. Costs unpriced."
    return f"{len(mapping.entries)} resources -> {mapping.target_region}: {parts}{ai_text}. monthly estimate aws {aws:.2f} eur vs leaseweb {lsw:.2f} eur"


def main_files(inventory_path: Path, graph_path: Path | None, out: Path, target_region: str | None, use_ai: bool) -> Mapping:
    inventory = json.loads(inventory_path.read_text())
    graph = json.loads(graph_path.read_text()) if graph_path and graph_path.exists() else None
    client = AIClient(out) if use_ai else None
    if client is not None and not client.enabled:
        print(f"ai off: {client.why_disabled()}, cached answers only", file=sys.stderr)
    mapping = translate(inventory, graph, target_region, client)
    out.mkdir(parents=True, exist_ok=True)
    (out / "mapping.json").write_text(mapping.model_dump_json(indent=2) + "\n")
    return mapping
