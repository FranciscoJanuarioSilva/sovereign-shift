import json
import re
from collections import Counter
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from sovereign_shift.artifacts import indexed, read, save, write


def cell(value: object) -> str:
    return escape(str(value)).replace("|", "&#124;").replace("\n", " ")


def report(out: Path, inventory: dict, mapping: dict) -> None:
    resources, entries = indexed(inventory, mapping)
    graph, findings, plan, book = (
        read(out, name) for name in ("graph", "findings", "finalize", "runbook")
    )
    names = {node["id"]: f"n{i}" for i, node in enumerate(graph["nodes"])}
    diagram = ["flowchart LR"]
    for node in graph["nodes"]:
        label = re.sub(r"[^\w .:/-]", "_", node["name"])
        diagram.append(f'  {names[node["id"]]}["{label}"]')
    for edge in graph["edges"]:
        arrow = "-.->" if edge.get("inferred") else "-->"
        diagram.append(f"  {names[edge['from']]} {arrow} {names[edge['to']]}")
    graph["mermaid"] = "\n".join(diagram)
    costs, work = [], []
    for ident, e in entries.items():
        costs.append({"source_id": ident, **(e.get("monthly_cost_eur") or {})})
        work.append(
            dict(
                source_id=ident,
                status=e["status"],
                via=e["via"],
                what=e.get("justification", ""),
                notes=e.get("notes", []),
                alternative=e.get("alternative"),
                ai_suggested=e.get("ai_suggested", False),
            )
        )
    cost = {
        "lines": costs,
        "assumptions": [
            "Monthly EUR estimates supplied by Translate. Missing prices are unknown."
        ],
    }
    for provider in ("aws", "leaseweb"):
        values = [c.get(provider) for c in costs]
        cost[provider + "_monthly_eur"] = (
            round(sum(values), 2) if None not in values else None
        )
    account = inventory.get("account_id", "")
    counts = Counter(e["status"] for e in entries.values())
    data = dict(
        generated_at=datetime.now(timezone.utc).isoformat(),
        source=dict(
            cloud=inventory.get("source", "aws"),
            account_id="****" + account[-4:],
            regions=inventory.get("regions", []),
        ),
        target=dict(cloud="leaseweb", region=mapping["target_region"]),
        summary={
            "resources": len(resources),
            **{
                status: counts[status]
                for status in ("auto", "partial", "manual", "unsupported")
            },
        },
        cost=cost,
        graph=graph,
        work=work,
        findings=findings["findings"],
        runbook=book,
        finalize=plan,
        terraform_files=sorted(p.name for p in (out / "terraform").glob("*.tf")),
    )
    if account:
        data = json.loads(json.dumps(data).replace(account, "****" + account[-4:]))
    save(out, "report", data)
    lines = [
        "# Migration assessment",
        f"{len(resources)} resources · {data['source']['account_id']} → {mapping['target_region']}",
        "## Dependencies",
        "```mermaid",
        data["graph"]["mermaid"],
        "```",
        "## Monthly costs (EUR)",
        "| Resource | AWS | Leaseweb |",
        "|---|---:|---:|",
    ]
    for c in data["cost"]["lines"]:
        lines.append(
            f"| {cell(c['source_id'])} | {c.get('aws') if c.get('aws') is not None else 'unknown'} | {c.get('leaseweb') if c.get('leaseweb') is not None else 'unknown'} |"
        )
    lines += [
        f"| Total | {cost['aws_monthly_eur']} | {cost['leaseweb_monthly_eur']} |",
        "## Migration work",
        "| Resource | Status | Via | Details |",
        "|---|---|---|---|",
    ]
    for e in data["work"]:
        detail = [e["what"], *e["notes"]]
        if e["alternative"]:
            detail.append(str(e["alternative"]))
        if e["ai_suggested"]:
            detail.insert(0, "ai-suggested")
        lines.append(
            "| "
            + " | ".join(
                cell(v)
                for v in (e["source_id"], e["status"], e["via"], " ".join(detail))
            )
            + " |"
        )
    lines += [
        "## Finalize after apply",
        "Security group attachments and target registrations are pending until finalize runs.",
    ]
    lines.extend(
        f"- {cell(m['source_id'])} — {cell(m['what'])}"
        for m in data["finalize"].get("manual", [])
    )
    lines += [
        "## Security findings",
        "| Resource | Severity | Evidence | Action |",
        "|---|---|---|---|",
    ]
    for f in data["findings"]:
        lines.append(
            "| "
            + " | ".join(
                cell(f[k]) for k in ("resource", "severity", "evidence", "fix")
            )
            + " |"
        )
    for item in data["graph"].get("findings", []):
        lines.append(f"- {cell(item['resource'])} — {cell(item['message'])}")
    lines.append("## Migration runbook")
    for entry in data["runbook"]["entries"]:
        lines.append("### " + cell(entry["source_id"]))
        if entry["personalised"]:
            lines.append("ai-suggested — " + cell(entry["justification"]))
        lines.extend(cell(i["reason"]) for i in entry["not_capable"])
        for step in entry["steps"]:
            lines.extend(cell(note) for note in step.get("notes", []))
            lines.extend(
                [
                    cell(step["title"]),
                    "```sh",
                    step["command"],
                    step["verify"],
                    "```",
                ]
            )
    lines += ["## Terraform files", ", ".join(data["terraform_files"])]
    write(
        out / "report.md",
        "\n\n".join(lines).replace("\n\n|", "\n|").replace("\n\n  n", "\n  n") + "\n",
    )
