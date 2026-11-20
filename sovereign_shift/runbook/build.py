import hashlib
import json
import os
import re
from pathlib import Path

import yaml
from openai import OpenAI, OpenAIError
from pydantic import BaseModel, ConfigDict

from sovereign_shift.artifacts import indexed, write


class SelectedStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    inputs: dict[str, str]


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: list[SelectedStep]
    notes: dict[str, list[str]]
    justification: str


def validate_selection(choice: Selection, steps: list[dict]) -> None:
    required = [step["id"] for step in steps]
    if [item.id for item in choice.steps] != required:
        raise ValueError("Missing, unknown or out-of-order migration step")
    for item, template in zip(choice.steps, steps):
        expected = {k: spec["source"] for k, spec in template["inputs"].items()}
        if item.inputs != expected:
            raise ValueError("Unknown input value or provenance")
    if set(choice.notes) - set(required):
        raise ValueError("Unknown step in notes")
    approved = {
        "Schedule a maintenance window.",
        "Verify destination capacity.",
        "Confirm the application is quiesced.",
    }
    if any(note not in approved for notes in choice.notes.values() for note in notes):
        raise ValueError("Unknown runbook note")
    if choice.justification not in {
        "engine-specific migration",
        "resource-type migration",
    }:
        raise ValueError("Unknown justification")


def runbook(out: Path, inventory: dict, mapping: dict, no_ai: bool) -> dict:
    resources, entries = indexed(inventory, mapping)
    templates = Path(__file__).with_name("templates")
    if not templates.exists():
        templates = Path(__file__).resolve().parents[2] / "runbook/templates"
    library = {}
    for path in sorted(templates.glob("*.yaml")):
        template = yaml.safe_load(path.read_text())
        library[template["resource_type"], template["engine"]] = template["steps"]
    model = os.getenv("SOVEREIGN_AI_MODEL")
    key = os.getenv("SOVEREIGN_AI_API_KEY")
    client = None
    if not no_ai and key and model:
        client = OpenAI(
            api_key=key,
            base_url=os.getenv(
                "SOVEREIGN_AI_BASE_URL", "https://eu.openrouter.ai/api/v1"
            ),
            timeout=15,
            max_retries=1,
        )
    result = []
    for identifier, resource in resources.items():
        kind = resource["type"]
        engine = (
            resource.get("properties", {}).get("engine")
            if kind == "db_instance"
            else None
        )
        steps = library.get((kind, engine), [])
        entry = dict(
            source_id=identifier,
            source_type=kind,
            personalised=False,
            not_capable=[],
            steps=[],
        )
        result.append(entry)
        if not steps:
            entry["not_capable"].append(
                {"what": kind, "reason": "No migration template for this resource"}
            )
            continue
        notes = {}
        if client:
            # send only local template identifiers and a fixed status vocabulary
            status = entries[identifier]["status"]
            payload = json.dumps(
                dict(
                    steps=[
                        {
                            "id": s["id"],
                            "inputs": {k: v["source"] for k, v in s["inputs"].items()},
                        }
                        for s in steps
                    ],
                    size_gib=resource.get("properties", {}).get("size_gib")
                    if type(resource.get("properties", {}).get("size_gib")) is int
                    else None,
                    status=status
                    if status in {"auto", "partial", "manual", "unsupported"}
                    else "unknown",
                )
            )
            cache = (
                out
                / ".cache"
                / (
                    hashlib.sha256((str(model) + payload).encode()).hexdigest()
                    + ".json"
                )
            )
            try:
                if cache.exists():
                    choice = Selection.model_validate_json(cache.read_text())
                else:
                    response = client.chat.completions.create(
                        model=model,
                        response_format={"type": "json_object"},
                        messages=[
                            {
                                "role": "system",
                                "content": "Return JSON with steps (copy supplied IDs and input provenance in dependency order), justification (engine-specific migration or resource-type migration), and notes keyed by step ID. Select applicable notes from: Schedule a maintenance window. Verify destination capacity. Confirm the application is quiesced.",
                            },
                            {"role": "user", "content": payload},
                        ],
                    )
                    choice = Selection.model_validate_json(
                        response.choices[0].message.content or ""
                    )
                validate_selection(choice, steps)
                write(cache, choice.model_dump_json())
                notes = choice.notes
                entry.update(
                    personalised=True,
                    ai_suggested=True,
                    justification=choice.justification,
                )
            except (ValueError, OpenAIError, IndexError):
                pass
        for template in steps:
            values, origins = {}, {}
            for name, spec in template["inputs"].items():
                value = (
                    resource.get(spec.get("field", ""))
                    if spec["source"] == "inventory"
                    else None
                )
                if value and re.fullmatch(
                    r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", str(value)
                ):
                    origins[name], values[name] = "inventory", value
                else:
                    origins[name], values[name] = (
                        "customer",
                        f"<CUSTOMER: {name.replace('_', ' ')}>",
                    )
            entry["steps"].append(
                dict(
                    id=template["id"],
                    title=template["title"],
                    command=template["command"].format_map(values),
                    verify=template["verify"].format_map(values),
                    inputs=origins,
                    notes=notes.get(template["id"], []),
                )
            )
    used_ai = any(e["personalised"] for e in result)
    return dict(
        generated_by="ai" if used_ai else "template-default",
        model=model if used_ai else None,
        entries=result,
    )
