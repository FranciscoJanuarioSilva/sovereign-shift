"""Scaling on Leaseweb: tiers, single points of failure, scale-up prices, scale-out recipe, hard limits."""

from sovereign_shift.translator import catalog

from .common import by_id, names

ROOT_DISK_MAX_GB = 1000
LIMITS = [
    {"limit": "Root disk at most 1000 GB per instance, and no separate block volumes", "source": "docs/research/leaseweb-terraform.md"},
    {"limit": "Default private network is a /27 (about 30 hosts), at most /24 on request: the ceiling for scale-out", "source": "docs/research/leaseweb-platform.md"},
    {"limit": "No auto scaling in the Terraform provider (the API has /autoScalingGroups): scale by changing the instance count", "source": "docs/research/leaseweb-api.md"},
    {"limit": "Load balancer backends must be in the same availability zone", "source": "docs/research/leaseweb-platform.md"},
    {"limit": "No managed database: database scaling is vertical, replicas are set up by hand", "source": "docs/research/service-equivalence.md"},
]


def next_size(type_name: str, region: str | None) -> dict | None:
    """The next bigger type in the same family and generation, with its price."""
    types, _ = catalog.leaseweb_types()
    same = [t for t in types if t.region in (None, region)]
    current = next((t for t in same if t.name == type_name), None)
    if current is None:
        return None
    bigger = sorted(
        (t for t in same if t.family == current.family and t.generation == current.generation and t.vcpu > current.vcpu),
        key=lambda t: t.vcpu,
    )
    biggest = max((t for t in same if t.family == current.family and t.generation == current.generation), key=lambda t: t.vcpu)
    if not bigger:
        return {"from": type_name, "to": None, "max": biggest.name, "note": "already the largest size of this generation"}
    up = bigger[0]
    delta = round(up.price_monthly_eur - current.price_monthly_eur, 2) if up.price_monthly_eur is not None and current.price_monthly_eur is not None else None
    return {
        "from": type_name, "to": up.name, "vcpu": f"{current.vcpu} -> {up.vcpu}",
        "memory_gib": f"{current.memory_gib:g} -> {up.memory_gib:g}",
        "extra_eur_month": delta, "max": biggest.name,
    }


def scaling(inventory: dict, graph: dict, mapping: dict) -> dict:
    label = names(inventory, mapping)
    resources = by_id(inventory["resources"])
    entries = mapping.get("entries", [])
    by_tf = {e.get("tf_name"): e["source_id"] for e in entries if e.get("tf_name")}
    tiers, spofs, up = [], [], []
    in_tier: set[str] = set()
    for e in entries:
        t = e.get("target") or {}
        if t.get("kind") == "target_group":
            members = [by_tf[m] for m in t.get("members", []) if m in by_tf]
            in_tier.update(members)
            tiers.append({
                "tier": label[e["source_id"]], "kind": "web behind load balancer", "servers": len(members),
                "members": [label[m] for m in members],
                "horizontal": len(members) >= 2,
                "how": "add servers: raise the instance count in Terraform, apply, then re-run finalize to register them",
            })
            if len(members) < 2:
                spofs.append({"what": label[e["source_id"]], "why": "only one server behind the load balancer"})
    for e in entries:
        t = e.get("target") or {}
        if t.get("kind") == "self_hosted_db":
            p = resources[e["source_id"]].get("properties") or {}
            tiers.append({"tier": label[e["source_id"]], "kind": "database", "servers": 1, "members": [label[e["source_id"]]],
                          "horizontal": False, "how": "scale up the instance; read replicas only by hand"})
            spofs.append({"what": label[e["source_id"]], "why": "single database server" + ("" if p.get("multi_az") else " (also single-zone on AWS)")})
        if t.get("kind") in ("public_cloud_instance", "self_hosted_db") and t.get("instance_type"):
            option = next_size(t["instance_type"], t.get("region"))
            if option:
                up.append({"resource": label[e["source_id"]], **option})
            if (t.get("root_disk_size") or 0) > 0.7 * ROOT_DISK_MAX_GB:
                spofs.append({"what": label[e["source_id"]], "why": f"root disk {t['root_disk_size']} GB is close to the 1000 GB maximum"})
        if t.get("kind") == "public_cloud_instance" and e["source_id"] not in in_tier:
            tiers.append({"tier": label[e["source_id"]], "kind": "standalone server", "servers": 1, "members": [label[e["source_id"]]],
                          "horizontal": False, "how": "put it behind a load balancer to scale out"})
    return {
        "tiers": tiers,
        "single_points_of_failure": spofs,
        "scale_up": up,
        "scale_out": [
            "Make the web servers stateless (sessions and uploads in the database or object storage).",
            "Raise the instance count in the generated Terraform (one resource per server, or add count) and run terraform apply.",
            "Run sovereign-shift finalize again: it attaches the security groups and registers the new servers in the target group.",
            "Watch the private network size: the default /27 holds about 30 hosts.",
        ],
        "limits": LIMITS,
    }
