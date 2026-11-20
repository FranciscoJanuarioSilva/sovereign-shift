"""Markdown for the assessment sections: executive summary, security posture, risk, performance, scaling."""

from html import escape


def cell(value: object) -> str:
    return escape(str(value)).replace("|", "&#124;").replace("\n", " ")


def eur(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.2f}"


def narrative(section: dict) -> list[str]:
    n = section.get("narrative")
    return [f"ai-suggested — {cell(n['text'])}"] if n else []


def executive_summary(a: dict, cost: dict, source: str, target: str) -> list[str]:
    p, r = a["posture"]["overall"], a["risk"]["overall"]
    lines = ["## Executive summary", "| | Today on " + source + " | After moving to Leaseweb |", "|---|---|---|"]
    if p["before"] is not None:
        lines.append(f"| Security posture | {p['grade_before']} ({p['before']}/100) | {p['grade_after']} ({p['after']}/100) |")
    lines.append(f"| Highest risk | {r['current']} | {r['after_migration']} |")
    aws, lsw = cost.get(f"{source.lower()}_priced_subtotal_eur"), cost.get("leaseweb_priced_subtotal_eur")
    if aws and lsw:
        lines.append(f"| Compute cost (EUR/month) | {aws:.2f} | {lsw:.2f} ({(lsw - aws) / aws * 100:+.0f}%) |")
    lines.append(
        f"Migration readiness: **{r['readiness']}**. The move itself resolves {r['resolved_by_migration']} risks. "
        f"Target: Leaseweb {target}."
    )
    return lines


def posture_section(a: dict) -> list[str]:
    p = a["posture"]
    lines = [
        "## Security posture",
        "Scores start at 100 per area and lose points per finding (critical 40, high 20, medium 8, low 3). "
        "'After' counts the findings the generated Leaseweb setup fixes.",
        "| Area | Today | After migration | Findings | Fixed by the migration |",
        "|---|---:|---:|---:|---:|",
    ]
    for d in p["domains"]:
        if d["assessed"]:
            lines.append(f"| {d['title']} | {d['before']} | {d['after']} | {d['findings']} | {d['fixed']} |")
        else:
            lines.append(f"| {d['title']} | not assessed | not assessed | | |")
    o = p["overall"]
    if o["before"] is not None:
        lines.append(f"| **Overall** | **{o['grade_before']} ({o['before']})** | **{o['grade_after']} ({o['after']})** | | |")
    if p["not_assessed"]:
        lines.append("Not assessed (no data in the scan): " + ", ".join(p["not_assessed"]) + ".")
    for when, title in (("before", "Reachable from the internet today"), ("after", "Reachable from the internet after the migration")):
        items = p["exposure"][when]
        lines.append(f"**{title}:** " + ("; ".join(f"{cell(x['name'])} ({', '.join(x['ports']) or x['how']})" for x in items) or "nothing") + ".")
    return lines


def risk_section(a: dict) -> list[str]:
    r = a["risk"]
    o = r["overall"]
    lines = [
        "## Risk assessment",
        f"Highest risk today: **{o['current']}**. After the migration: **{o['after_migration']}**. "
        f"Migration itself: **{o['migration']}**. Readiness: **{o['readiness']}**.",
        *narrative(r),
        "Score = likelihood (1-5) x impact (1-5). Impact grows with how many resources depend on the one at risk. "
        "Bands: critical 20+, high 12+, medium 6+.",
        "Heat map (rows: likelihood 5 to 1, columns: impact 1 to 5, numbers are risk counts):",
        "| Likelihood \\ Impact | 1 | 2 | 3 | 4 | 5 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for i, row in enumerate(r["heatmap"]):
        lines.append(f"| {5 - i} | " + " | ".join(str(n) if n else "" for n in row) + " |")
    lines += ["### Top risks today", "| Risk | Category | Score | After migration | Mitigation |", "|---|---|---:|---|---|"]
    for x in r["top_today"]:
        lines.append(f"| {cell(x['title'])} | {x['category']} | {x['score']} ({x['rating']}) | {x['rating_after']} | {cell(x['mitigation'])} |")
    lines += ["### Top risks remaining after the migration", "| Risk | Category | Score | Mitigation |", "|---|---|---:|---|"]
    for x in r["top_after_migration"]:
        lines.append(f"| {cell(x['title'])} | {x['category']} | {x['score_after']} ({x['rating_after']}) | {cell(x['mitigation'])} |")
    lines.append(f"Full register: {len(r['register'])} risks in assessment.json.")
    return lines


def performance_section(a: dict) -> list[str]:
    perf = a["performance"]
    lines = ["## Performance", "| Resource | Today | vCPU / RAM | On Leaseweb | vCPU / RAM | Disk |", "|---|---|---|---|---|---|"]
    for x in perf["rows"]:
        lines.append(
            f"| {cell(x['name'])} | {x['aws_type']} | {x['aws_vcpu']} / {x['aws_memory_gib']} GiB | "
            f"{x['leaseweb_type']} | {x['leaseweb_vcpu']} / {x['leaseweb_memory_gib']} GiB | {x['disk'] or ''} |"
        )
    notes = {}
    for x in perf["rows"]:
        for n in x["notes"]:
            notes.setdefault((n["severity"], n["note"]), []).append(x["name"])
    for (severity, note), who in sorted(notes.items(), key=lambda kv: kv[0][0] != "warning"):
        lines.append(f"- {'**warning:** ' if severity == 'warning' else ''}{cell(note)} ({cell(', '.join(who))})")
    lines += [f"- {cell(g)}" for g in perf["general"]]
    lines += [f"- Not assessed: {cell(n)}" for n in perf["not_assessed"]]
    return lines


def scaling_section(a: dict) -> list[str]:
    s = a["scaling"]
    lines = ["## Scaling", *narrative(s), "| Tier | Kind | Servers | Scales out | How |", "|---|---|---:|---|---|"]
    for t in s["tiers"]:
        lines.append(f"| {cell(t['tier'])} | {t['kind']} | {t['servers']} | {'yes' if t['horizontal'] else 'no'} | {cell(t['how'])} |")
    if s["single_points_of_failure"]:
        lines.append("**Single points of failure:** " + "; ".join(f"{cell(x['what'])} ({cell(x['why'])})" for x in s["single_points_of_failure"]) + ".")
    if s["scale_up"]:
        lines += ["Scale up (next size, same family):", "| Resource | From | To | vCPU | RAM (GiB) | Extra EUR/month | Largest |", "|---|---|---|---|---|---:|---|"]
        for u in s["scale_up"]:
            lines.append(
                f"| {cell(u['resource'])} | {u['from']} | {u.get('to') or '-'} | {u.get('vcpu', '')} | {u.get('memory_gib', '')} | "
                f"{eur(u.get('extra_eur_month'))} | {u.get('max', '')} |"
            )
    lines.append("Scale out on Leaseweb:")
    lines += [f"{i}. {cell(step)}" for i, step in enumerate(s["scale_out"], 1)]
    lines.append("Limits to plan around:")
    lines += [f"- {cell(x['limit'])}" for x in s["limits"]]
    return lines
