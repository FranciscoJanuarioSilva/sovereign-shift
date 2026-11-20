"""Optional assessment commentary using aggregate counts and anonymous rule data."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from sovereign_shift import skills
from sovereign_shift.ai.client import AIClient
from sovereign_shift.ai.redact import redact


class Commentary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=1200)
    justification: str = Field(min_length=1, max_length=400)


def insights(out: Path, data: dict, inventory: dict) -> None:
    counts = {
        key: value for key, value in data["summary"].items() if isinstance(value, int)
    }
    groups = {
        r["id"]: r for r in inventory["resources"] if r["type"] == "security_group"
    }
    comparisons = []
    for group in data["finalize"]["security_groups"]:
        source = groups[group["source_id"]].get("properties", {})
        original = []
        for rule in source.get("ingress", []):
            original.append(
                {
                    "public": any(
                        c in {"0.0.0.0/0", "::/0"} for c in rule.get("cidrs", [])
                    ),
                    "group_sources": len(rule.get("source_groups", [])),
                    "ports": [
                        p
                        for p in (rule.get("from_port"), rule.get("to_port"))
                        if type(p) is int
                    ],
                }
            )
        translated = []
        for rule in group["rules"]:
            src = rule["source"]
            cidr = src.get("cidr", "")
            scope = "public" if cidr in {"0.0.0.0/0", "::/0"} else "restricted CIDR"
            if "private_ip_of" in src:
                scope = "individual private IP"
            translated.append(
                {
                    "scope": scope,
                    "ports": [
                        p
                        for p in (rule.get("start_port"), rule.get("end_port"))
                        if type(p) is int
                    ],
                }
            )
        comparisons.append(
            {
                "original": original,
                "translated": translated,
                "attachments": len(group["attach_to"]),
            }
        )
    jobs = [
        (
            "explainer",
            "Summarize this planned migration from resource counts and security finding count.",
            {**counts, "findings": len(data["findings"])},
        ),
        (
            "reviewer",
            "Review these proposed firewall translations for changes of exposure. Mention that effective default groups require verification. Never claim deployment.",
            comparisons,
        ),
    ]
    for agent, instruction, payload in jobs:
        if not payload:
            continue
        client = AIClient(out, agent)
        if client.enabled:
            answer = client.complete(
                instruction
                + ' Output exactly one JSON object shaped like {"text":"one concise paragraph","justification":"one sentence explaining the evidence"}. Both values must be strings. Use exactly these two top-level keys. No wrapper, arrays or commands.',
                json.dumps(payload),
                Commentary,
            )
            if answer:
                data[agent] = {**answer.model_dump(), "ai_suggested": True}

    assessment = data.get("assessment")
    if not assessment:
        return
    rules = (
        " You explain results that are already computed. Never change, recompute or invent a score, rating, price or "
        "resource, only use what the JSON gives you. Plain words, for a customer. "
        'Output exactly one JSON object shaped like {"text":"one concise paragraph","justification":"one sentence naming the evidence"}.'
    )
    r, s = assessment["risk"], assessment["scaling"]
    narratives = [
        ("risk_narrative", "assess-risk", "risk", {
            "overall": r["overall"],
            "top_today": [{k: x[k] for k in ("title", "category", "rating", "rating_after")} for x in r["top_today"]],
            "top_after_migration": [{k: x[k] for k in ("title", "category", "rating_after", "mitigation")} for x in r["top_after_migration"]],
        }),
        ("scaling_advice", "assess-scaling", "scaling", {
            "tiers": [{k: x[k] for k in ("tier", "kind", "servers", "horizontal")} for x in s["tiers"]],
            "single_points_of_failure": s["single_points_of_failure"],
            "scale_up": [{k: x.get(k) for k in ("resource", "from", "to", "extra_eur_month")} for x in s["scale_up"]],
            "limits": [x["limit"] for x in s["limits"]],
        }),
    ]
    for agent, skill, section, payload in narratives:
        client = AIClient(out, agent)
        if not client.enabled:
            continue
        # the skill is the system prompt, so the agent works from the same rubric the code implements
        answer = client.complete(skills.load(skill) + "\n\n" + rules, json.dumps(redact(payload)), Commentary)
        if answer:
            assessment[section]["narrative"] = {**answer.model_dump(), "ai_suggested": True}
