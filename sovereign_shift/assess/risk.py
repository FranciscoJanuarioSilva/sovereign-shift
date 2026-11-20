"""Risk register: likelihood x impact for the current infrastructure and for the migration itself.

The scoring rules are written down in skills/assess-risk/SKILL.md, keep the two in sync.
"""

import networkx as nx

from .common import by_id, clamp, names

LIKELIHOOD_BY_SEVERITY = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 1}
# an open security group exposes every server that uses it, so it counts like a server
BASE_IMPACT = {"db_instance": 4, "s3_bucket": 3, "ec2_instance": 3, "lb": 3, "target_group": 3, "security_group": 3}
# exposure to the internet only makes security and data risks more likely, not availability ones
EXPOSURE_CATEGORIES = {"security", "data"}
CATEGORY_OF_DOMAIN = {"network": "security", "identity": "security", "data": "data", "availability": "availability"}


def rating(score: int) -> str:
    return "critical" if score >= 20 else "high" if score >= 12 else "medium" if score >= 6 else "low"


def dependents(graph: dict) -> dict[str, int]:
    """How many resources point at each one, directly or through others (its blast radius)."""
    g = nx.DiGraph()
    g.add_nodes_from(n["id"] for n in graph["nodes"])
    g.add_edges_from((e["from"], e["to"]) for e in graph["edges"])
    return {n: len(nx.ancestors(g, n)) for n in g.nodes}


def impact(kind: str, blast: int) -> int:
    return clamp(BASE_IMPACT.get(kind, 2) + (1 if blast >= 2 else 0) + (1 if blast >= 5 else 0))


# migration risks that only exist while moving, not once the system runs on leaseweb
CUTOVER = ("M-DATA-", "M-IP-", "M-TLS-", "M-DNS-", "M-ARM-", "M-AI-", "M-UNS-")


def make(rid: str, title: str, category: str, likelihood: int, impact_: int, resources: list[str],
         evidence: str, mitigation: str, mitigated_by_migration: bool = False, likelihood_after: int | None = None) -> dict:
    score = likelihood * impact_
    # after the migration: gone if the migration fixes it, else re-scored (e.g. no longer exposed)
    after = None if mitigated_by_migration else (likelihood_after or likelihood) * impact_
    return {
        "id": rid, "title": title, "category": category,
        "likelihood": likelihood, "impact": impact_, "score": score, "rating": rating(score),
        "score_after": after, "rating_after": rating(after) if after is not None else "resolved",
        "resources": resources, "evidence": evidence, "mitigation": mitigation,
        "mitigated_by_migration": mitigated_by_migration,
        "phase": "cutover" if rid.startswith(CUTOVER) else "lasting",
    }


def security_risks(inventory: dict, posture: dict, blast: dict[str, int]) -> list[dict]:
    kinds = {r["id"]: r["type"] for r in inventory["resources"]}
    exposed = {x["resource"] for x in posture["exposure"]["before"]}
    exposed_after = {x["resource"] for x in posture["exposure"]["after"]}
    out = []
    for i, f in enumerate(posture["findings"]):
        if f["severity"] == "info":
            continue
        category = CATEGORY_OF_DOMAIN.get(f["domain"], "security")
        base = LIKELIHOOD_BY_SEVERITY[f["severity"]]
        bonus = category in EXPOSURE_CATEGORIES
        out.append(make(
            f"R-{f['id']}-{i}", f"{f['title']} ({f['name']})", category,
            clamp(base + (1 if bonus and f["resource"] in exposed else 0)),
            impact(kinds.get(f["resource"], ""), blast.get(f["resource"], 0)), [f["name"]],
            f"{f['id']}: {f['evidence']}",
            f["fix"] + (" The migration already does this." if f["fixed_by_migration"] else ""),
            f["fixed_by_migration"],
            likelihood_after=clamp(base + (1 if bonus and f["resource"] in exposed_after else 0)),
        ))
    return out


def availability_risks(inventory: dict, mapping: dict, label: dict[str, str]) -> list[dict]:
    resources = inventory["resources"]
    members: dict[str, list[str]] = {}
    for e in mapping.get("entries", []):
        t = e.get("target") or {}
        if t.get("kind") == "target_group":
            members[e["source_id"]] = t.get("members", [])
    backends = {m for ms in members.values() for m in ms}
    tf = {e["source_id"]: e.get("tf_name") for e in mapping.get("entries", [])}
    out = []
    for gid, ms in members.items():
        if len(ms) == 1:
            out.append(make(f"R-SPOF-{tf.get(gid)}", f"Load balancer sends all traffic to one server ({label[gid]})",
                            "availability", 3, 4, [label[gid], ms[0]], "target group has a single member",
                            "Run at least two servers behind the load balancer."))
    for r in resources:
        if r["type"] == "ec2_instance" and (r.get("properties") or {}).get("public_ip") and tf.get(r["id"]) not in backends and members:
            out.append(make(f"R-SPOF-{tf.get(r['id'])}", f"Public server outside the load balancer ({label[r['id']]})",
                            "availability", 2, 3, [label[r["id"]]], "public ip, not in any target group",
                            "Put it behind the load balancer or document why it serves traffic directly."))
    return out


def migration_risks(inventory: dict, mapping: dict, label: dict[str, str]) -> list[dict]:
    out = []
    groups = False
    for e in mapping.get("entries", []):
        name = label.get(e["source_id"], e["source_id"])
        notes = " ".join(e.get("notes", []))
        t = e.get("target") or {}
        kind = e["source_type"]
        if e.get("ai_suggested"):
            out.append(make(f"M-AI-{e.get('tf_name')}", f"No Leaseweb equivalent for {name}, AI-suggested replacement",
                            "migration", 4, 3, [name], (e.get("alternative") or {}).get("name", "ai suggestion"),
                            "Review the suggested replacement and test it before cutover."))
        elif e["status"] == "unsupported":
            out.append(make(f"M-UNS-{e.get('tf_name')}", f"No Leaseweb equivalent for {name}", "migration", 4, 3, [name],
                            e.get("justification", ""), "Design a replacement by hand (see the report's manual work)."))
        if t.get("kind") == "self_hosted_db":
            out.append(make(f"M-DB-{e.get('tf_name')}", f"Database becomes self-managed ({name})", "operational", 3, 4, [name],
                            "no managed database on Leaseweb", "Automate backups and patching, test a restore before cutover."))
        if e["via"] == "runbook" and t.get("kind") != "self_hosted_db":
            out.append(make(f"M-DATA-{e.get('tf_name')}", f"Data must be copied ({name})", "migration", 3, 3, [name],
                            "not moved by terraform", "Rehearse the runbook, compare checksums or row counts after the copy."))
        if t.get("kind") == "self_hosted_db":
            out.append(make(f"M-DATA-{e.get('tf_name')}", f"Database data must be dumped and restored ({name})", "migration", 3, 4, [name],
                            "dump/restore in the runbook", "Rehearse the dump/restore, plan a write freeze for cutover."))
        if "graviton" in notes:
            out.append(make(f"M-ARM-{e.get('tf_name')}", f"ARM to x86 rebuild ({name})", "migration", 3, 3, [name],
                            "aws graviton instance", "Rebuild images and binaries for x86 and run the test suite."))
        if "local NVMe" in notes:
            out.append(make(f"M-NVME-{e.get('tf_name')}", f"Data on a non-replicated local disk ({name})", "data", 2, 4, [name],
                            "type only offers local NVMe", "Keep the app stateless or back up off the host."))
        if kind == "elastic_ip" and e["status"] == "manual":
            out.append(make(f"M-IP-{e.get('tf_name')}", f"Public IP changes ({name})", "migration", 4, 2, [name],
                            "leaseweb can't keep or reserve the aws ip", "Lower DNS TTLs a day ahead, update allow-lists."))
        if kind == "lb_listener" and t.get("protocol") == "HTTPS":
            out.append(make(f"M-TLS-{e.get('tf_name')}", f"TLS certificate must be re-issued ({name})", "migration", 3, 3, [name],
                            "acm certificates can't be exported", "Issue a certificate (e.g. Let's Encrypt) before cutover."))
        if kind == "route53_zone":
            out.append(make(f"M-DNS-{e.get('tf_name')}", f"DNS zone must move ({name})", "migration", 3, 3, [name],
                            "zones can't be created with terraform on leaseweb", "Transfer the domain or change NS records, with low TTLs."))
        groups = groups or t.get("kind") == "security_group"
    if groups:
        out.append(make("M-FW-default", "Leaseweb's default security group allows all traffic", "security", 3, 4, [],
                        "until finalize attaches our groups; whether the default can be detached is unverified",
                        "Run finalize right after apply and check the effective rules before going live."))
    return out


def risk(inventory: dict, graph: dict, posture: dict, mapping: dict) -> dict:
    label = names(inventory, mapping)
    blast = dependents(graph)
    register = security_risks(inventory, posture, blast) + availability_risks(inventory, mapping, label) + migration_risks(inventory, mapping, label)
    register = list(by_id(register).values())
    register.sort(key=lambda r: (-r["score"], r["category"], r["title"]))
    current = [r for r in register if not r["id"].startswith("M-")]
    migration = [r for r in register if r["id"].startswith("M-")]
    # what is left once the system runs on leaseweb: unfixed risks plus lasting ones the move introduces
    remaining = [r for r in register if r["score_after"] is not None and r["phase"] == "lasting"]
    order = ["low", "medium", "high", "critical"]

    def worst(items: list[dict], key: str = "rating") -> str:
        return max((r[key] for r in items), key=order.index, default="low")

    worst_migration = worst(migration)
    readiness = "not ready" if worst_migration == "critical" else "ready with conditions" if worst_migration == "high" else "ready"
    heatmap = [[sum(1 for r in register if r["likelihood"] == lk and r["impact"] == im) for im in range(1, 6)] for lk in range(5, 0, -1)]
    return {
        "overall": {
            "current": worst(current), "after_migration": worst(remaining, "rating_after"),
            "resolved_by_migration": sum(1 for r in register if r["mitigated_by_migration"]),
            "migration": worst_migration, "readiness": readiness,
            "counts": {k: sum(1 for r in register if r["rating"] == k) for k in ("critical", "high", "medium", "low")},
        },
        # rows are likelihood 5 down to 1, columns impact 1 to 5
        "heatmap": heatmap,
        "top_today": [r for r in register if not r["id"].startswith("M-")][:5],
        "top_after_migration": sorted(remaining, key=lambda r: -r["score_after"])[:5],
        "register": register,
    }
