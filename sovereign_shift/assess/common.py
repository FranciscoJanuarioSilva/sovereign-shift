"""Shared helpers for the assessment sections: weights, grades, names, internet exposure."""

from typing import Any

# points taken off a 100-point domain score per finding (skills/assess-security-posture/SKILL.md)
WEIGHTS = {"critical": 40, "high": 20, "medium": 8, "low": 3, "info": 0}
WORLD = {"0.0.0.0/0", "::/0"}
DOMAINS = {
    "network": "Network exposure",
    "data": "Data protection",
    "identity": "Access and identity",
    "availability": "Availability",
}
# finding id (or prefix) -> domain, first match wins
DOMAIN_OF = [
    ("RDS-001", "network"), ("RDS-002", "data"), ("RDS-003", "availability"), ("RDS-004", "availability"),
    ("EC2-001", "identity"), ("EC2-002", "data"), ("EC2-003", "network"),
    ("SG-", "network"), ("NET-", "network"), ("ELB-", "network"),
    ("S3-", "data"), ("IAM-", "identity"),
]


def domain_of(finding_id: str) -> str:
    return next((d for prefix, d in DOMAIN_OF if finding_id.startswith(prefix)), "network")


def grade(score: float) -> str:
    return "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 40 else "F"


def names(inventory: dict, mapping: dict) -> dict[str, str]:
    """Readable name per resource id, never a raw arn."""
    tf = {e["source_id"]: e.get("tf_name") for e in mapping.get("entries", [])}
    out = {}
    for r in inventory["resources"]:
        name = r.get("name") or r["id"]
        if name.startswith("arn:"):
            name = tf.get(r["id"]) or name.rsplit("/", 2)[-2]
        out[r["id"]] = name
    return out


def world_ports(group: dict) -> list[str]:
    """Inbound ports a security group opens to the whole internet, e.g. ["tcp/22", "all"]."""
    out = []
    for rule in (group.get("properties") or {}).get("ingress") or []:
        cidrs = set(rule.get("cidrs") or [])
        if not cidrs & WORLD:
            continue
        protocol = str(rule.get("protocol", "-1")).lower()
        start, end = rule.get("from_port"), rule.get("to_port")
        if protocol in ("-1", "all"):
            out.append("all")
        elif start == end:
            out.append(f"{protocol}/{start}")
        else:
            out.append(f"{protocol}/{start}-{end}")
    return sorted(set(out))


def clamp(value: float, low: int = 1, high: int = 5) -> int:
    return int(max(low, min(high, round(value))))


def by_id(items: list[dict[str, Any]], key: str = "id") -> dict[str, dict[str, Any]]:
    return {item[key]: item for item in items}
