"""Performance: capacity before and after, and the platform differences that change how it runs.

Inventory data only. No utilisation metrics are scanned yet, so right-sizing from real load is "not assessed".
"""

from sovereign_shift.translator import catalog
from sovereign_shift.translator.rules import aws_specs

from .common import by_id, names


def leaseweb_spec(name: str | None, region: str | None):
    if not name:
        return None
    types, _ = catalog.leaseweb_types()
    return next((t for t in types if t.name == name and t.region in (None, region)), None)


def row_notes(aws_type: str, mapping_entry: dict, lsw, volumes: list[dict]) -> list[dict]:
    notes = []
    text = " ".join(mapping_entry.get("notes", []))
    t = mapping_entry.get("target") or {}

    def add(severity: str, note: str) -> None:
        notes.append({"severity": severity, "note": note})

    plain = aws_type.removeprefix("db.")
    if plain.startswith("t") or aws_type.startswith("Standard_B"):
        add("info", "AWS burstable CPU (credits) becomes steady vCPU: sustained load runs better, short peaks don't burst.")
    if "graviton" in text:
        add("warning", "ARM (Graviton) to x86: re-run benchmarks after the rebuild, performance per vCPU differs.")
    if lsw and lsw.generation != "7a":
        add("info", f"{lsw.name} has shared vCPU (only the 7a generation is dedicated), so neighbours can affect it.")
    if t.get("root_disk_storage_type") == "LOCAL":
        add("info", "Local NVMe disk: very fast, but not replicated.")
    elif t.get("root_disk_storage_type") == "CENTRAL":
        iops = max((int(v.get("iops") or 0) for v in volumes), default=0)
        if iops > 8000:
            add("warning", f"AWS volume runs at {iops} IOPS, Leaseweb central storage Value tier gives 8K (Performance tier 30K).")
        else:
            add("info", "Central (network) storage: replicated, Value tier 8K IOPS, Performance tier 30K.")
    if "over-provisioned" in text:
        add("info", "More capacity than today: headroom, and part of why the price can be higher.")
    return notes


def performance(inventory: dict, mapping: dict) -> dict:
    label = names(inventory, mapping)
    resources = by_id(inventory["resources"])
    rows = []
    for e in mapping.get("entries", []):
        t = e.get("target") or {}
        if t.get("kind") not in ("public_cloud_instance", "self_hosted_db") or not t.get("instance_type"):
            continue
        r = resources[e["source_id"]]
        p = r.get("properties") or {}
        aws_type = p.get("instance_type") or p.get("instance_class") or "?"
        spec_vcpu, spec_mem, _ = aws_specs(aws_type, r.get("region"))
        lsw = leaseweb_spec(t["instance_type"], t.get("region"))
        rows.append({
            "resource": e["source_id"], "name": label[e["source_id"]], "kind": t["kind"],
            "aws_type": aws_type, "aws_vcpu": p.get("vcpu") or spec_vcpu, "aws_memory_gib": p.get("memory_gib") or spec_mem,
            "leaseweb_type": t["instance_type"], "leaseweb_vcpu": lsw.vcpu if lsw else None,
            "leaseweb_memory_gib": lsw.memory_gib if lsw else None, "disk": t.get("root_disk_storage_type"),
            "notes": row_notes(aws_type, e, lsw, p.get("volumes") or []),
        })
    regions = sorted({r.get("region") for r in inventory["resources"] if r.get("region") not in (None, "global")})
    target = mapping.get("target_region")
    location = catalog.regions()["leaseweb_codes"].get(target, {}).get("location", target)
    general = [
        f"Workloads move from {', '.join(regions) or 'the source region'} to Leaseweb {location}: "
        "users and services that stay near the old region see a different network path, measure latency before cutover."
    ]
    if any(e["source_type"] == "lb" for e in mapping.get("entries", [])):
        general.append("Leaseweb load balancers only balance to backends in the same availability zone, and have no path or host routing.")
    return {
        "rows": rows,
        "general": general,
        "not_assessed": ["Real utilisation (CPU, memory, network over time): not scanned, so sizing matches capacity, not load."],
    }
