import json
import re
from collections import Counter
from datetime import datetime, UTC
from html import escape
from pathlib import Path

from sovereign_shift.report import sections
from sovereign_shift.translator import catalog
from sovereign_shift.report.insights import insights
from sovereign_shift.artifacts import indexed, read, save, write


def join_markdown(lines: list[str]) -> str:
    # blank line between blocks, but table rows and mermaid lines stay together
    text = "\n\n".join(lines)
    text = re.sub(r"(\|[^\n]*)\n\n(?=\|)", r"\1\n", text)
    return text.replace("\n\n  n", "\n  n")


def cell(value: object) -> str:
    return escape(str(value)).replace("|", "&#124;").replace("\n", " ")


def display_names(resources: dict, entries: dict) -> dict[str, str]:
    """Human name per resource id: the aws name, or a short form when the name is just an arn."""
    out = {}
    for ident, r in resources.items():
        name = r.get("name") or ident
        if name.startswith("arn:"):
            # listeners have no name, the translator's tf_name (e.g. lb_listener_443) reads better
            name = entries.get(ident, {}).get("tf_name") or name.rsplit("/", 2)[-2]
        out[ident] = name
    return out


def leaseweb_price_notes(source: str) -> list[str]:
    """Say where the Leaseweb prices came from, so nobody mistakes an estimate for a quote."""
    if source.startswith("catalog:"):
        taken = source.split(":", 2)[2][:10]
        notes = [
            f"Leaseweb: Public Cloud API prices from a snapshot taken {taken}, in EUR, without taxes or discounts. "
            "A customer's own contract prices can replace them (SOVEREIGN_LEASEWEB_CATALOG).",
            "Regions that Leaseweb bills in another currency (e.g. London in GBP) show unknown, never a converted guess.",
        ]
        try:
            age = (datetime.now(UTC) - datetime.fromisoformat(taken + "T00:00:00+00:00")).days
        except ValueError:
            return notes
        if age > 30:
            notes.append(f"The price snapshot is {age} days old, refresh it before quoting savings.")
        return notes
    return [
        "Leaseweb: no API snapshot found, so prices are public list prices or estimates (marked *).",
        "Public OpenStack compute prices reflect 1-month savings plans on a DIFFERENT platform and are not confirmed legacy API prices.",
    ]


def aws_price_note(costs: list[dict]) -> str:
    estimated = [c for c in costs if c.get("aws") is not None and c.get("aws_estimated")]
    if not costs or not any(c.get("aws") is not None for c in costs):
        return "AWS: no price available for these resources."
    if not estimated:
        return "AWS: on-demand list prices for the scanned region (AWS Pricing API), without Savings Plans or discounts."
    return ("AWS: on-demand list prices from the AWS Pricing API where marked real, otherwise approximate us-east-1 prices (marked *). "
            "No Savings Plans or discounts.")


def alternative_text(alt: dict) -> str:
    steps = "; ".join(alt.get("manual_steps") or [])
    text = f"AI alternative: {alt.get('name', '?')} (effort {alt.get('effort', '?')}, confidence {alt.get('confidence', '?')})"
    return text + (f". Steps: {steps}" if steps else "")


def report(out: Path, inventory: dict, mapping: dict, no_ai: bool = True) -> None:
    resources, entries = indexed(inventory, mapping)
    graph, findings, plan, book = (
        read(out, name) for name in ("graph", "findings", "finalize", "runbook")
    )
    display = display_names(resources, entries)
    account = inventory.get("account_id", "")
    if account:
        # data gets the account masked before rendering, so look names up by the masked id too
        display |= {k.replace(account, "****" + account[-4:]): v for k, v in display.items()}

    def show(ident: str) -> str:
        return display.get(ident, ident)

    names = {node["id"]: f"n{i}" for i, node in enumerate(graph["nodes"])}
    diagram = ["flowchart LR"]
    for node in graph["nodes"]:
        label = re.sub(r"[^\w .:/-]", "_", display.get(node["id"], node["name"]))
        diagram.append(f'  {names[node["id"]]}["{label}"]')
    for edge in graph["edges"]:
        arrow = "-.->" if edge.get("inferred") else "-->"
        diagram.append(f"  {names[edge['from']]} {arrow} {names[edge['to']]}")
    graph["mermaid"] = "\n".join(diagram)
    costs, work = [], []
    unpriced = 0
    for ident, e in entries.items():
        price = e.get("monthly_cost_eur") or {}
        if price.get("aws") is None and price.get("leaseweb") is None:
            unpriced += 1
        else:
            costs.append({
                "source_id": ident, "name": show(ident), "type": e["source_type"],
                "aws_type": resources[ident].get("properties", {}).get("instance_type")
                or resources[ident].get("properties", {}).get("instance_class"),
                "leaseweb_type": (e.get("target") or {}).get("instance_type"),
                "oversized": any("over-provisioned" in n for n in e.get("notes", [])),
                **price,
            })
        work.append(
            dict(
                source_id=ident,
                name=show(ident),
                status=e["status"],
                via=e["via"],
                what=e.get("justification", ""),
                notes=e.get("notes", []),
                alternative=e.get("alternative"),
                ai_suggested=e.get("ai_suggested", False),
            )
        )
    oversized = [c for c in costs if c["oversized"]]
    cost = {
        "lines": costs,
        "unpriced_resources": unpriced,
        "oversized": len(oversized),
        "assumptions": [
            "Monthly EUR estimates supplied by Translate. Only compute (instances, databases) is priced, the rest has no separate cost here.",
            aws_price_note(costs),
            *leaseweb_price_notes(mapping.get("catalog_source", "")),
            "Additional storage, traffic, public IPs and load balancers are not included in this compute subtotal.",
            "Rows with a price on only one side are left out of both totals.",
            "The smallest Leaseweb size is 2 vCPU, so tiny AWS instances map to a bigger, pricier VM.",
        ],
    }
    source_cloud = inventory.get("source", "aws")
    source_label = {"cloudflare": "Cloudflare", "azure": "Azure", "gcp": "Google Cloud"}.get(source_cloud, "AWS")
    if source_cloud == "azure":
        # the price notes are written for aws, name the right cloud and price api
        cost["assumptions"] = [a.replace("AWS Pricing API", "Azure Retail Prices API").replace("AWS:", "Azure:").replace("tiny AWS", "tiny Azure")
                               for a in cost["assumptions"]]
    if source_cloud == "gcp":
        # no google price list is fetched, so only the leaseweb side has numbers
        cost["assumptions"] = [
            "Google Cloud: list prices weren't fetched, the source side is unpriced. Compare the Leaseweb column with your billing export."
            if a == aws_price_note(costs) else a.replace("tiny AWS", "tiny Google Cloud").replace(
                "Rows with a price on only one side are left out of both totals.", "The Leaseweb total sums every priced Leaseweb row.")
            for a in cost["assumptions"]
        ]
    if source_cloud == "cloudflare":
        cost["assumptions"] = ["Cloudflare usage and billing were not scanned. Migration costs are unpriced."]
    for provider in (source_cloud, "leaseweb"):
        # the translator stores any source cloud's price in the "aws" field
        # totals only count rows priced on both sides, or the comparison isn't like for like
        both = [c for c in costs if c.get("aws") is not None and c.get("leaseweb") is not None]
        values = [c.get("aws" if provider == source_cloud else provider) for c in (costs if source_cloud in ("cloudflare", "gcp") else both)]
        cost[provider + "_priced_subtotal_eur"] = round(sum(v for v in values if v is not None), 2)
        cost[provider + "_monthly_eur"] = (
            round(sum(values), 2) if None not in values and (values or source_cloud in ("aws", "azure")) else None
        )
    account = inventory.get("account_id", "")
    counts = Counter(e["status"] for e in entries.values())
    data = dict(
        generated_at=datetime.now(UTC).isoformat(),
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
    if (out / "assessment.json").exists():
        data["assessment"] = read(out, "assessment")
    if inventory.get("denied"):
        data["denied"] = inventory["denied"]
    if not no_ai:
        insights(out, data, inventory)
    if account:
        data = json.loads(json.dumps(data).replace(account, "****" + account[-4:]))
    save(out, "report", data)
    assessment = data.get("assessment")
    target_location = catalog.regions()["leaseweb_codes"].get(mapping["target_region"], {}).get("location", mapping["target_region"])
    lines = [
        "# Migration assessment",
        f"{len(resources)} resources · {data['source']['account_id']} → {mapping['target_region']}",
        *(sections.executive_summary(assessment, cost, source_label, target_location) if assessment else []),
        "## Dependencies",
        "```mermaid",
        data["graph"]["mermaid"],
        "```",
        *(sections.posture_section(assessment) + sections.risk_section(assessment) if assessment else []),
        "## Monthly costs (EUR)",
        f"| Resource | {source_label} type | {source_label} | Leaseweb type | Leaseweb |",
        "|---|---|---:|---|---:|",
    ]

    def eur(value: object, estimated: bool = False) -> str:
        return "unknown" if value is None else f"{value:.2f}{'*' if estimated else ''}"

    for c in data["cost"]["lines"]:
        flag = " (over-provisioned)" if c["oversized"] else ""
        lines.append(
            f"| {cell(c['name'])} | {cell(c.get('aws_type') or '')} | {eur(c.get('aws'), c.get('aws_estimated', False))} | "
            f"{cell(c.get('leaseweb_type') or '')}{flag} | {eur(c.get('leaseweb'), c.get('leaseweb_estimated', False))} |"
        )
    lines += [
        f"| **Total** | | unknown | | {cost['leaseweb_priced_subtotal_eur']:.2f} |" if source_cloud == "gcp" and costs else
        f"| **Total** | | {cost[source_cloud + '_priced_subtotal_eur']:.2f} | | {cost['leaseweb_priced_subtotal_eur']:.2f} |"
        if costs or source_cloud == "aws" else "| **Total** | | unknown | | unknown |",
        "\n".join(f"- {a}" for a in cost["assumptions"]),
    ]
    if data.get("denied"):
        lines.extend(["## Scan coverage", "Access was denied for these operations."])
        lines.extend(f"- {cell(item['operation'])}" for item in data["denied"])
    if oversized:
        lines.append(
            f"{len(oversized)} of {len(costs)} priced resources are smaller than Leaseweb's smallest size (2 vCPU). "
            "For them the Leaseweb VM is bigger than what runs today, so compare on capacity, not on the bill alone."
        )
    if assessment:
        lines += sections.performance_section(assessment) + sections.scaling_section(assessment)
    lines += [
        "## Migration work",
        "| Resource | Status | Via | Details |",
        "|---|---|---|---|",
    ]
    for e in data["work"]:
        detail = [e["what"], *e["notes"]]
        if e["alternative"]:
            detail.append(alternative_text(e["alternative"]))
        if e["ai_suggested"]:
            detail.insert(0, "ai-suggested")
        lines.append(
            "| "
            + " | ".join(
                cell(v)
                for v in (e["name"], e["status"], e["via"], " ".join(detail))
            )
            + " |"
        )
    lines += [
        "## Finalize after apply",
        "Security group attachments and target registrations are pending until finalize runs.",
    ]
    lines.extend(
        f"- {cell(show(m['source_id']))} — {cell(m['what'])}"
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
                cell(show(f[k]) if k == "resource" else f[k]) for k in ("resource", "severity", "evidence", "fix")
            )
            + " |"
        )
    for item in data["graph"].get("findings", []):
        lines.append(f"- {cell(show(item['resource']))} — {cell(item['message'])}")
    for agent, title in [("explainer","Migration summary"), ("reviewer","Firewall review")]:
        if agent in data:
            lines.extend(["## "+title, "ai-suggested — "+cell(data[agent]["text"]), cell(data[agent]["justification"])])
        elif agent == "reviewer":
            lines.append("Firewall translation is unreviewed.")
    lines.append("## Migration runbook")
    nothing_to_move = []
    for entry in data["runbook"]["entries"]:
        generic = all(
            "No migration template" in i.get("reason", "") or "moves with the instance" in i.get("reason", "")
            for i in entry["not_capable"]
        )
        # networks, groups, keys etc. carry no data, list them once instead of one empty section each
        if not entry["steps"] and not entry["personalised"] and generic:
            nothing_to_move.append(show(entry["source_id"]))
            continue
        lines.append("### " + cell(show(entry["source_id"])))
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
    if nothing_to_move:
        lines.append("No separate data move for: " + cell(", ".join(nothing_to_move)) + " (no data, or moved with their instance).")
    lines += ["## Terraform files", ", ".join(data["terraform_files"])]
    write(
        out / "report.md",
        join_markdown(lines) + "\n",
    )
