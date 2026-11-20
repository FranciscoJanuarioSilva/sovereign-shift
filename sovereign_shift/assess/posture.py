"""Security posture: domain scores before and after the migration, and what is reachable from the internet."""

from statistics import mean

from .common import DOMAINS, WEIGHTS, WORLD, by_id, domain_of, grade, names, world_ports

PUBLIC_DB_KEYS = ("publicly_accessible",)
PUBLIC_BUCKET_KEYS = ("public", "policy_public", "acl_public")


def _assessed(inventory: dict) -> dict[str, bool]:
    kinds = {r["type"] for r in inventory["resources"]}
    has_imds = any("http_tokens" in (r.get("properties") or {}) for r in inventory["resources"] if r["type"] == "ec2_instance")
    return {
        "network": bool(kinds & {"security_group", "lb", "ec2_instance"}),
        "data": bool(kinds & {"db_instance", "s3_bucket", "ebs_volume"}),
        # identity needs iam data or at least the instance metadata settings
        "identity": bool(kinds & {"iam_account", "iam_access_key"}) or has_imds,
        "availability": bool(kinds & {"db_instance", "lb", "target_group"}),
    }


def _score(findings: list[dict]) -> int:
    return max(0, 100 - sum(WEIGHTS.get(f["severity"], 0) for f in findings))


def exposure_before(inventory: dict, label: dict[str, str]) -> list[dict]:
    resources = inventory["resources"]
    groups = {r["id"]: r for r in resources if r["type"] == "security_group"}
    listeners: dict[str, list[str]] = {}
    for r in resources:
        if r["type"] == "lb_listener":
            for rel in r.get("relations", []):
                listeners.setdefault(rel["target"], []).append(f"{str(r['properties'].get('protocol', '')).lower()}/{r['properties'].get('port')}")
    out = []
    for r in resources:
        p = r.get("properties") or {}
        sgs = [rel["target"] for rel in r.get("relations", []) if rel.get("type") == "uses_security_group"]
        open_ports = sorted({port for g in sgs if g in groups for port in world_ports(groups[g])})
        how = None
        if r["type"] == "ec2_instance" and p.get("public_ip") and open_ports:
            how = "public ip, ports open to the internet"
        elif r["type"] == "db_instance" and any(p.get(k) for k in PUBLIC_DB_KEYS):
            how = "publicly accessible database"
        elif r["type"] == "lb" and str(p.get("scheme", "internet-facing")) == "internet-facing":
            how, open_ports = "internet-facing load balancer", sorted(listeners.get(r["id"], []))
        elif r["type"] == "s3_bucket" and any(p.get(k) for k in PUBLIC_BUCKET_KEYS):
            how, open_ports = "public bucket", ["https"]
        if how:
            out.append({"resource": r["id"], "name": label[r["id"]], "type": r["type"], "how": how, "ports": open_ports})
    return out


def exposure_after(inventory: dict, mapping: dict, label: dict[str, str]) -> list[dict]:
    """On leaseweb every instance has a public ip, so exposure is whatever the translated groups open to the world."""
    entries = mapping.get("entries", [])
    by_tf = {e.get("tf_name"): e["source_id"] for e in entries if e.get("tf_name")}
    ports: dict[str, set[str]] = {}
    for e in entries:
        t = e.get("target") or {}
        if t.get("kind") != "security_group":
            continue
        world = {
            f"{r['protocol'].lower()}/{r.get('start_port')}" + (f"-{r['end_port']}" if r.get("end_port") != r.get("start_port") else "")
            for r in t.get("rules", []) if r.get("source", {}).get("cidr") in WORLD
        }
        for name in t.get("attach_to", []):
            if name in by_tf:
                ports.setdefault(by_tf[name], set()).update(world)
    resources = by_id(inventory["resources"])
    out = [
        {"resource": rid, "name": label[rid], "type": resources[rid]["type"], "how": "public ip, ports open to the internet", "ports": sorted(p)}
        for rid, p in ports.items() if p
    ]
    # load balancers stay public, buckets keep their policy until someone changes it
    for item in exposure_before(inventory, label):
        if item["type"] in ("lb", "s3_bucket"):
            out.append(item)
    return sorted(out, key=lambda x: x["name"])


def posture(inventory: dict, graph: dict, findings: list[dict], mapping: dict) -> dict:
    label = names(inventory, mapping)
    fixes = {e["source_id"]: set(e.get("fixes") or []) for e in mapping.get("entries", [])}
    rows = []
    for f in findings:
        rows.append({
            **f,
            "name": label.get(f["resource"], f["resource"]),
            "domain": domain_of(f["id"]),
            "fixed_by_migration": f["id"] in fixes.get(f["resource"], set()),
        })
    assessed = _assessed(inventory)
    domains = []
    for key, title in DOMAINS.items():
        mine = [f for f in rows if f["domain"] == key]
        before, after = _score(mine), _score([f for f in mine if not f["fixed_by_migration"]])
        domains.append({
            "id": key, "title": title, "assessed": assessed[key] or bool(mine),
            "before": before, "after": after, "findings": len(mine),
            "fixed": sum(f["fixed_by_migration"] for f in mine),
        })
    scored = [d for d in domains if d["assessed"]]
    before = round(mean(d["before"] for d in scored)) if scored else None
    after = round(mean(d["after"] for d in scored)) if scored else None
    return {
        "overall": {
            "before": before, "after": after,
            "grade_before": grade(before) if before is not None else None,
            "grade_after": grade(after) if after is not None else None,
        },
        "domains": domains,
        "not_assessed": [d["title"] for d in domains if not d["assessed"]],
        "findings": sorted(rows, key=lambda f: (-WEIGHTS.get(f["severity"], 0), f["name"], f["id"])),
        "exposure": {"before": exposure_before(inventory, label), "after": exposure_after(inventory, mapping, label)},
    }
