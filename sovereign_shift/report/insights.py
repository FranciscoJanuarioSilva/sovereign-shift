"""Optional assessment commentary using aggregate counts and anonymous rule data."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from sovereign_shift.ai.client import AIClient


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
