"""Deterministic aws -> leaseweb rules, one function per resource type."""

import math
import re
from dataclasses import dataclass, field
from typing import Any
from collections.abc import Callable

from sovereign_shift.translator.models import Alternative, Cost, MappingEntry

from . import catalog

ADMIN_PORTS = {22, 3389}
DB_PORTS = {1433, 3306, 5432, 6379, 9200, 27017}
WORLD = {"0.0.0.0/0", "::/0"}
DNS_TTLS = [60, 300, 1800, 3600, 14400, 28800, 43200, 86400]
DNS_TYPES = {"A", "AAAA", "CAA", "CNAME", "MX", "NS", "SRV", "TXT", "SOA", "DS", "TLSA"}
DB_ENGINES = {
    "postgres": "postgres", "aurora-postgresql": "postgres",
    "mysql": "mysql", "mariadb": "mariadb", "aurora": "mysql", "aurora-mysql": "mysql",
}
DB_PORT = {"postgres": 5432, "mysql": 3306, "mariadb": 3306}


@dataclass
class Context:
    """Everything a rule may look at besides its own resource."""

    by_id: dict[str, dict[str, Any]]
    tf_names: dict[str, str]
    region_for: Callable[[str | None], str]
    target_region_override: str | None
    # instance ids that the graph says talk to a given db id
    db_clients: dict[str, set[str]] = field(default_factory=dict)

    def related(self, resource: dict[str, Any], kind: str | None = None, rel: str | None = None) -> list[dict[str, Any]]:
        out = []
        for relation in resource.get("relations", []):
            other = self.by_id.get(relation.get("target"))
            if other and (kind is None or other["type"] == kind) and (rel is None or relation.get("type") == rel):
                out.append(other)
        return out

    def referrers(self, target_id: str, kind: str | None = None, rel: str | None = None) -> list[dict[str, Any]]:
        out = []
        for other in self.by_id.values():
            for relation in other.get("relations", []):
                if relation.get("target") == target_id and (kind is None or other["type"] == kind) and (rel is None or relation.get("type") == rel):
                    out.append(other)
                    break
        return out


def props(resource: dict[str, Any]) -> dict[str, Any]:
    return resource.get("properties") or {}


def first(p: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if p.get(key) not in (None, ""):
            return p[key]
    return default


# ids like SG-001, RDS-001, EC2-001 (letters, then digits allowed)
FIXES = re.compile(r"\(fixes ([A-Z][A-Z0-9]*-\d+)\)")


def entry(resource: dict[str, Any], ctx: Context, **fields: Any) -> MappingEntry:
    # findings this translation removes, read from the "(fixes SG-001)" markers in the notes
    fixes = sorted(set(FIXES.findall(" ".join(fields.get("notes") or []))))
    return MappingEntry(
        source_id=resource["id"], source_type=resource["type"], source_name=resource.get("name"),
        tf_name=ctx.tf_names.get(resource["id"]), fixes=fixes, **fields,
    )


# ---------- instance sizing ----------

# azure vm sizes like Standard_D2s_v5, Standard_E4ds_v5, Standard_D2ps_v5 (p = arm), Standard_NC6s_v3
AZURE_SIZE_RE = re.compile(r"^Standard_([A-Z]+)(\d+)([a-z]*)(?:_v\d+)?$")
AZURE_SERIES = {"D": "m", "A": "m", "E": "r", "M": "r", "L": "r", "F": "c", "B": "t", "N": "g"}
AWS_TYPE_RE = re.compile(r"^(?:db\.)?([a-z]+)(\d+)([a-z-]*)\.(\w+)$")


def aws_specs(instance_type: str, aws_region: str | None = None) -> tuple[float | None, float | None, float | None]:
    """vcpu, memory gib and hourly usd for an aws type, from data/aws_instance_types.json.

    A real price for the resource's own region (scripts/fetch_aws_prices.py) wins over the approximate table.
    """
    data = catalog.aws_types()
    spec = data["ec2"].get(instance_type.removeprefix("db."))
    hourly = data["rds"].get(instance_type) if instance_type.startswith("db.") else (spec[2] if spec else None)
    regional = data.get("regional", {}).get(aws_region or "", {}).get(instance_type)
    return (spec[0] if spec else None, spec[1] if spec else None, regional if regional is not None else hourly)


def aws_price_is_real(instance_type: str, aws_region: str | None) -> bool:
    return instance_type in catalog.aws_types().get("regional", {}).get(aws_region or "", {})


def aws_monthly_eur(hourly_usd: float | None, multiplier: float = 1.0) -> float | None:
    if hourly_usd is None:
        return None
    data = catalog.aws_types()
    return round(hourly_usd * data["hours_per_month"] * data["usd_to_eur"] * multiplier, 2)


def pick_type(
    vcpu: float, memory: float, region: str, family: str | None, prefer_central: bool = False
) -> tuple[catalog.LswType | None, list[str]]:
    """Smallest leaseweb type with at least this vcpu and ram, same family if possible, newest generation.

    prefer_central (databases): only types that can use replicated central storage, if any fit.
    """
    types, _ = catalog.leaseweb_types()
    in_region = [t for t in types if t.region in (None, region) and t.family in ("c", "m", "r")]
    fits = [t for t in in_region if t.vcpu >= vcpu and t.memory_gib >= memory]
    notes = []
    if prefer_central and any("central" in t.storage_types for t in fits):
        fits = [t for t in fits if "central" in t.storage_types]
    candidates = [t for t in fits if t.family == family] if family else []
    if not candidates:
        if family:
            notes.append(f"no {family}-family type fits, used the cheapest type that does")
        candidates = fits
    if not candidates:
        return None, [f"no leaseweb type with {vcpu} vcpu / {memory} GiB in {region}"]
    # fewest vcpu first, then newest generation, then least ram and price
    best = min(candidates, key=lambda t: (t.vcpu, -t.rank, t.memory_gib, t.price_monthly_eur or 1e9))
    return best, notes


def leaseweb_family(aws_family: str, vcpu: float, memory: float) -> str:
    if aws_family.startswith("c"):
        return "c"
    if aws_family.startswith("m"):
        return "m"
    if aws_family[0] in "rxzu":
        return "r"
    # burstable and anything else: decide by ram per vcpu
    ratio = memory / max(vcpu, 1)
    return "c" if ratio <= 2 else "m" if ratio <= 4 else "r"


def storage_for(lsw: catalog.LswType | None, region: str) -> tuple[str, list[str]]:
    """Root disk kind the chosen type can actually use. Many newer types only offer local NVMe."""
    if lsw is None or "central" in lsw.storage_types:
        return "CENTRAL", []
    return "LOCAL", [
        f"{lsw.name} only offers local NVMe disks in {region}: fast, but not replicated, so keep backups "
        "(central network storage needs an older instance generation)"
    ]


def size_instance(
    instance_type: str, vcpu: float | None, memory: float | None, region: str,
    prefer_central: bool = False, aws_region: str | None = None,
) -> dict[str, Any]:
    """Shared by ec2 and rds: returns type, notes, partial flag and both monthly costs."""
    notes: list[str] = []
    partial = False
    spec_vcpu, spec_mem, hourly = aws_specs(instance_type, aws_region)
    vcpu = vcpu or spec_vcpu
    memory = memory or spec_mem
    match = AWS_TYPE_RE.match(instance_type)
    aws_family, suffix, size = (match.group(1), match.group(3), match.group(4)) if match else ("m", "", "")
    azure = AZURE_SIZE_RE.match(instance_type)
    if azure:
        # same family hints as aws: general, memory, compute, burstable, gpu; "p" in the features means arm
        aws_family = AZURE_SERIES.get(azure.group(1)[0], "m")
        suffix, size = ("g" if "p" in azure.group(3) else ""), ""
    if vcpu is None or memory is None:
        notes.append(f"vcpu/ram of {instance_type} unknown, assumed 2 vcpu / 4 GiB")
        vcpu, memory = vcpu or 2, memory or 4
        partial = True
    if "g" in suffix:
        notes.append("aws graviton (arm) -> x86, rebuild images and binaries")
        partial = True
    if aws_family[0] in "gpf" or aws_family in {"inf", "trn", "dl"}:
        notes.append("gpu/accelerator instance, mapped to a cpu type, review by hand")
        partial = True
    family = leaseweb_family(aws_family, vcpu, memory)
    chosen, pick_notes = pick_type(vcpu, memory, region, family, prefer_central)
    notes += pick_notes
    # compare real capacity, not the size name: t3.medium has 2 vcpu / 4 GiB and fits a leaseweb large exactly
    if chosen and (chosen.vcpu > vcpu or chosen.memory_gib >= 2 * memory):
        notes.append(
            f"smallest leaseweb fit is {chosen.vcpu} vcpu / {chosen.memory_gib:g} GiB, "
            f"more than the {vcpu:g} vcpu / {memory:g} GiB used on aws, so this is over-provisioned"
        )
    return {
        "type": chosen, "notes": notes, "partial": partial or chosen is None,
        "vcpu": vcpu, "memory": memory, "aws_hourly": hourly,
    }


def image_for(os_name: str | None) -> tuple[str, list[str], bool, bool]:
    """Leaseweb image id, notes, partial flag, windows flag."""
    table = catalog.images()
    text = (os_name or "").strip().lower()
    for row in table["images"]:
        if text and re.search(row["match"], text):
            notes = [row["note"]] if row.get("note") else []
            if not row.get("verified"):
                notes.append(f"image id {row['id']} not confirmed in the provider docs, check the images data source")
            return row["id"], notes, bool(row.get("note")), bool(row.get("windows"))
    return table["fallback"]["id"], [table["fallback"]["note"]], True, False


def contract() -> dict[str, Any]:
    return {"type": "HOURLY", "billing_frequency": 1, "term": 0}


# ---------- per-type rules ----------

def ec2_instance(r: dict[str, Any], ctx: Context) -> MappingEntry:
    p = props(r)
    region = ctx.region_for(r.get("region"))
    instance_type = first(p, "instance_type", "InstanceType", default="unknown")
    sized = size_instance(instance_type, first(p, "vcpu"), first(p, "memory_gib"), region, aws_region=r.get("region"))
    image, image_notes, image_partial, windows = image_for(first(p, "os", "platform_details"))
    notes = sized["notes"] + image_notes

    volumes = p.get("volumes") or []
    root = next((v for v in volumes if v.get("root")), volumes[0] if volumes else None)
    extra = [v for v in volumes if v is not root]
    disk = int(root.get("size_gib", 0)) if root else 0
    if extra:
        disk += sum(int(v.get("size_gib", 0)) for v in extra)
        notes.append(f"{len(extra)} extra ebs volume(s) merged into the root disk, data copy in the runbook")
    minimum = 50 if windows else 5
    disk = max(disk, minimum)
    too_big = disk > 1000
    if too_big:
        notes.append(f"needs {disk} GB but leaseweb root disks max out at 1000 GB, split data by hand")
        disk = 1000

    key = first(p, "key_name", "KeyName")
    if key:
        notes.append(f"ssh key {key} goes into the cloud-init user_data")
    if p.get("http_tokens") == "optional":
        # imdsv1 matters because it hands out aws iam role credentials, leaseweb instances have none to steal
        notes.append("IMDSv1 credential theft ends with the move: no AWS IAM role credentials on Leaseweb (fixes EC2-001)")
    if p.get("user_data_sha256") or p.get("user_data_length"):
        notes.append("instance had user_data on aws, review it and merge it into the cloud-init by hand")
    lsw = sized["type"]
    storage, storage_notes = storage_for(lsw, region)
    notes += storage_notes
    status = "partial" if (sized["partial"] or image_partial or extra or too_big) else "auto"
    target = {
        "kind": "public_cloud_instance",
        "region": region,
        "instance_type": lsw.name if lsw else None,
        "image_id": image,
        "root_disk_size": disk,
        "root_disk_storage_type": storage,
        "has_private_network": True,
        "contract": contract(),
        "ssh_key_name": key,
    }
    aws_eur = first(p, "monthly_cost_eur") or aws_monthly_eur(sized["aws_hourly"])
    justification = (
        f"{instance_type} ({sized['vcpu']:g} vcpu / {sized['memory']:g} GiB) -> {lsw.name} "
        f"({lsw.vcpu} vcpu / {lsw.memory_gib:g} GiB), smallest {lsw.family}-family fit, newest generation, "
        f"in {catalog.regions()['leaseweb_codes'].get(region, {}).get('location', region)}."
        if lsw else f"no leaseweb type fits {instance_type}"
    )
    return entry(
        r, ctx, status=status if lsw else "manual", via="terraform" if lsw else "report", target=target,
        justification=justification, notes=notes,
        monthly_cost_eur=Cost(
            aws=aws_eur, aws_estimated=not (first(p, "monthly_cost_eur") or aws_price_is_real(instance_type, r.get("region"))),
            leaseweb=lsw.price_monthly_eur if lsw else None,
            leaseweb_estimated=lsw.price_estimated if lsw else False,
        ),
    )


def _rule_sources(rule: dict[str, Any]) -> tuple[list[str], list[str]]:
    cidrs = list(rule.get("cidrs") or []) + list(rule.get("ipv6_cidrs") or [])
    groups = rule.get("source_groups") or rule.get("security_groups") or []
    return cidrs, [g if isinstance(g, str) else g.get("GroupId") for g in groups]


def _ports(rule: dict[str, Any]) -> tuple[str, int | None, int | None]:
    protocol = str(rule.get("protocol", "-1")).lower()
    protocol = {"6": "tcp", "17": "udp", "1": "icmp", "all": "-1"}.get(protocol, protocol)
    return protocol, rule.get("from_port"), rule.get("to_port")


def _covers(start: int | None, end: int | None, ports: set[int]) -> set[int]:
    if start is None or end is None or start < 0:
        return set(ports)
    return {port for port in ports if start <= port <= end}


def security_group(r: dict[str, Any], ctx: Context) -> MappingEntry:
    p = props(r)
    users = ctx.referrers(r["id"], rel="uses_security_group")
    attach = [ctx.tf_names[u["id"]] for u in users if u["type"] in ("ec2_instance", "db_instance")]
    lb_users = [u for u in users if u["type"] == "lb"]
    notes: list[str] = []
    if not attach:
        reason = "only used by a load balancer, leaseweb lbs have no security group" if lb_users else "not attached to anything"
        return entry(
            r, ctx, status="auto", via="report", target=None,
            justification=f"Not recreated: {reason}.", notes=[f"{reason} on aws"],
        )

    # instances that, per the graph, connect to a db using this group
    db_clients = sorted({
        ctx.tf_names[i] for u in users if u["type"] == "db_instance"
        for i in ctx.db_clients.get(u["id"], set()) if i in ctx.tf_names
    })
    rules: list[dict[str, Any]] = []
    for rule in p.get("ingress") or []:
        protocol, start, end = _ports(rule)
        cidrs, groups = _rule_sources(rule)
        proto_list = ["TCP", "UDP", "ICMP"] if protocol == "-1" else [protocol.upper()]
        if protocol == "-1":
            start, end = 1, 65535
            if WORLD & set(cidrs):
                notes.append("all traffic from the internet (SG-003), kept as is, tighten it")
        sources: list[dict[str, Any]] = []
        for cidr in cidrs:
            if cidr in WORLD and protocol in ("tcp", "-1") and _covers(start, end, ADMIN_PORTS):
                sources.append({"cidr": "var:admin_cidr"})
                notes.append(f"port {start}-{end} from {cidr} restricted to var.admin_cidr (fixes SG-001)")
            elif cidr in WORLD and protocol in ("tcp", "-1") and _covers(start, end, DB_PORTS):
                if db_clients:
                    sources += [{"private_ip_of": name} for name in db_clients]
                    notes.append(f"db port {start}-{end} from {cidr} restricted to the app instances' private ips (fixes SG-002)")
                else:
                    sources.append({"cidr": "var:admin_cidr"})
                    notes.append(f"db port {start}-{end} from {cidr} had no known clients, restricted to var.admin_cidr (fixes SG-002)")
            else:
                sources.append({"cidr": cidr})
        for group_id in groups:
            members = [u for u in ctx.referrers(group_id, rel="uses_security_group") if u["type"] in ("ec2_instance", "db_instance")]
            if members:
                sources += [{"private_ip_of": ctx.tf_names[m["id"]]} for m in members]
                notes.append(f"rule from {group_id} became /32 rules on {len(members)} private ip(s), resolved after apply")
            elif any(u["type"] == "lb" for u in ctx.referrers(group_id)):
                sources.append({"cidr": "var:private_network_cidr"})
                notes.append(f"rule from load balancer group {group_id} became the private network range")
            else:
                notes.append(f"rule from {group_id} dropped, nothing uses that group")
        for proto in proto_list:
            for source in _dedupe(sources):
                rule_out = {"protocol": proto, "source": source}
                if proto != "ICMP":
                    rule_out |= {"start_port": start if start is not None else 1, "end_port": end if end is not None else 65535}
                rules.append(rule_out)
    if p.get("egress"):
        notes.append("egress rules not translated, leaseweb firewall rules are inbound only (verify)")
    notes.append("the default leaseweb group allows everything, finalize attaches this one instead")
    return entry(
        r, ctx, status="auto", via="finalize",
        target={"kind": "security_group", "name": r.get("name") or r["id"], "rules": rules, "attach_to": attach},
        justification="Leaseweb security group with the same inbound rules, created through the API because the provider has no resource for it.",
        notes=_dedupe(notes),
    )


def _dedupe(items: list[Any]) -> list[Any]:
    out = []
    for item in items:
        if item not in out:
            out.append(item)
    return out


def db_instance(r: dict[str, Any], ctx: Context) -> MappingEntry:
    p = props(r)
    region = ctx.region_for(r.get("region"))
    engine_raw = str(first(p, "engine", default="")).lower()
    engine = DB_ENGINES.get(engine_raw)
    db_class = first(p, "instance_class", "db_instance_class", default="db.t3.medium")
    multi_az = bool(first(p, "multi_az", default=False))
    aws_eur = first(p, "monthly_cost_eur") or aws_monthly_eur(aws_specs(db_class, r.get("region"))[2], 2.0 if multi_az else 1.0)
    aws_real = aws_price_is_real(db_class, r.get("region"))
    if not engine:
        return entry(
            r, ctx, status="unsupported", via="report", target=None,
            justification=f"No self-hosted recipe for engine '{engine_raw}'.",
            notes=["needs an alternative, see the ai suggestion if any"],
            monthly_cost_eur=Cost(aws=aws_eur, aws_estimated=not aws_real),
        )
    # a database wants replicated central storage when some fitting type offers it
    sized = size_instance(db_class, p.get("vcpu"), p.get("memory_gib"), region, prefer_central=True)
    lsw = sized["type"]
    disk_kind, disk_notes = storage_for(lsw, region)
    storage = int(first(p, "storage_gib", "allocated_storage", "allocated_storage_gib", default=20))
    disk = min(max(math.ceil(storage * 1.2) + 10, 20), 1000)
    # arm vs x86 doesn't matter for a db engine, it gets reinstalled anyway
    notes = [n for n in sized["notes"] if "graviton" not in n] + disk_notes + [
        "no managed database on leaseweb, the engine runs on its own instance",
        "data moves with dump/restore, see the runbook",
        "backups, patching and failover become your job (or use an operator on leaseweb managed kubernetes)",
    ]
    if multi_az:
        notes.append("multi-az on aws, a single instance on leaseweb, add a replica by hand if needed")
    if first(p, "publicly_accessible", default=False):
        notes.append("was publicly accessible, on leaseweb only the app instances may reach it (fixes RDS-001)")
    return entry(
        r, ctx, status="manual", via="runbook",
        target={
            "kind": "self_hosted_db", "engine": engine, "engine_version": first(p, "engine_version"),
            "port": DB_PORT[engine], "region": region,
            "instance_type": lsw.name if lsw else None, "image_id": "UBUNTU_24_04_64BIT",
            "root_disk_size": disk, "root_disk_storage_type": disk_kind,
            "has_private_network": True, "contract": contract(),
        },
        justification=(
            f"{engine} {first(p, 'engine_version', default='')} on a {lsw.name if lsw else '?'} instance "
            f"sized like {db_class}, disk {storage} GB + 20% headroom."
        ),
        notes=notes,
        monthly_cost_eur=Cost(
            aws=aws_eur, aws_estimated=not aws_real,
            leaseweb=lsw.price_monthly_eur if lsw else None, leaseweb_estimated=lsw.price_estimated if lsw else False,
        ),
    )


def lb(r: dict[str, Any], ctx: Context) -> MappingEntry:
    p = props(r)
    region = ctx.region_for(r.get("region"))
    kind = str(first(p, "lb_type", "type", "load_balancer_type", default="application")).lower()
    notes = []
    if str(first(p, "scheme", default="internet-facing")).lower() == "internal":
        notes.append("internal lb on aws, leaseweb lbs are public, restrict it with the backend security groups")
    if kind == "network":
        notes.append("network lb, mapped to tcp listeners")
    if kind not in ("application", "network"):
        return entry(r, ctx, status="unsupported", via="report", target=None,
                     justification=f"{kind} load balancers have no leaseweb equivalent.", notes=notes)
    chosen, _ = pick_type(2, 4, region, "m")
    notes.append("leaseweb lb price not known yet, left out of the cost total")
    return entry(
        r, ctx, status="partial" if notes[:-1] else "auto", via="terraform",
        target={"kind": "load_balancer", "region": region, "type": chosen.name if chosen else None,
                "reference": r.get("name") or r["id"], "contract": contract()},
        justification="Leaseweb public cloud load balancer, smallest size, same region as the backends.",
        notes=notes,
    )


def lb_listener(r: dict[str, Any], ctx: Context) -> MappingEntry:
    p = props(r)
    protocol = str(first(p, "protocol", default="HTTP")).upper()
    port = first(p, "port", default=80)
    balancer = (ctx.related(r, "lb") or ctx.referrers(r["id"], "lb") or [None])[0]
    groups = ctx.related(r, "target_group")
    if not groups and first(p, "default_target_group"):
        tg = ctx.by_id.get(first(p, "default_target_group"))
        groups = [tg] if tg else []
    notes = []
    mapped = {"HTTP": "HTTP", "HTTPS": "HTTPS", "TCP": "TCP", "TLS": "TCP"}.get(protocol)
    if mapped is None:
        return entry(r, ctx, status="unsupported", via="report", target=None,
                     justification=f"{protocol} listeners aren't supported by leaseweb load balancers.")
    status = "auto"
    if protocol == "HTTPS":
        notes.append("acm certificates can't be exported, issue a new one (e.g. let's encrypt) and set it as var")
        status = "partial"
    if protocol == "TLS":
        notes.append("tls listener became plain tcp, terminate tls on the backends")
        status = "partial"
    if p.get("rules") or p.get("extra_rules"):
        notes.append("path/host routing rules aren't supported, only the default target group was kept")
        status = "partial"
    return entry(
        r, ctx, status=status, via="terraform",
        target={"kind": "lb_listener", "protocol": mapped, "port": port,
                "load_balancer": ctx.tf_names.get(balancer["id"]) if balancer else None,
                "default_target_group": ctx.tf_names.get(groups[0]["id"]) if groups else None,
                "certificate": "var:tls_certificate" if mapped == "HTTPS" else None},
        justification=f"{protocol}:{port} listener on the leaseweb lb.", notes=notes,
    )


def target_group(r: dict[str, Any], ctx: Context) -> MappingEntry:
    p = props(r)
    region = ctx.region_for(r.get("region"))
    protocol = str(first(p, "protocol", default="HTTP")).upper()
    port = first(p, "port", default=80)
    members = [m for m in ctx.related(r, "ec2_instance")]
    for target in p.get("targets") or []:
        # scanner gives {"id", "port"}, contract examples give plain ids
        target_id = target.get("id") if isinstance(target, dict) else target
        if target_id in ctx.by_id and ctx.by_id[target_id]["type"] == "ec2_instance" and ctx.by_id[target_id] not in members:
            members.append(ctx.by_id[target_id])
    hc = dict(p.get("health_check") or {})
    for flat, key in (("health_check_path", "path"), ("health_check_protocol", "protocol"), ("health_check_port", "port")):
        if p.get(flat) is not None:
            hc.setdefault(key, p[flat])
    hc_port = hc.get("port", port)
    notes = ["members are registered by finalize after apply, the provider can't do it"]
    if str(first(p, "target_type", default="instance")) != "instance":
        notes.append(f"target type {p['target_type']} on aws, only instances can be leaseweb targets")
    if protocol not in ("HTTP", "HTTPS", "TCP"):
        notes.append(f"{protocol} not supported, used TCP")
        protocol = "TCP"
    return entry(
        r, ctx, status="auto", via="terraform",
        target={
            "kind": "target_group", "name": (r.get("name") or r["id"])[:64], "protocol": protocol,
            "port": port, "region": region,
            "health_check": {
                "protocol": str(hc.get("protocol", protocol)).upper(),
                "port": port if str(hc_port) == "traffic-port" else int(hc_port),
                "uri": hc.get("path", "/"),
                "method": "GET" if str(hc.get("protocol", protocol)).upper() != "TCP" else None,
            },
            "members": [ctx.tf_names[m["id"]] for m in members],
        },
        justification=f"Leaseweb target group, {protocol}:{port}, same health check.", notes=notes,
    )


def s3_bucket(r: dict[str, Any], ctx: Context) -> MappingEntry:
    region = ctx.region_for(r.get("region"))
    info = catalog.regions()
    country = info["leaseweb_codes"].get(region, {}).get("country", "nl")
    endpoint = info["object_storage_endpoints"].get(country, info["object_storage_endpoints"]["nl"])
    notes = ["not in terraform (object storage was reverted in provider 1.32.1), bucket and copy in the runbook"]
    if country not in info["object_storage_endpoints"]:
        notes.append(f"no object storage in {country}, used the nl endpoint")
    p = props(r)
    if p.get("versioning") in (True, "Enabled"):
        notes.append("versioning on aws, check support on leaseweb object storage (not documented)")
    return entry(
        r, ctx, status="partial", via="runbook",
        target={"kind": "object_storage_bucket", "bucket": r.get("name") or r["id"], "endpoint": endpoint},
        justification=f"S3-compatible Leaseweb Object Storage at {endpoint}, synced with rclone.", notes=notes,
    )


def route53_record(r: dict[str, Any], ctx: Context) -> MappingEntry:
    p = props(r)
    rtype = str(first(p, "record_type", "type", default="A")).upper()
    name = str(first(p, "name", default=r.get("name") or r["id"]))
    zone = (ctx.related(r, "route53_zone") or [None])[0]
    domain = (zone.get("name") if zone else None) or first(p, "zone_name", "domain_name")
    alias = p.get("alias") or p.get("alias_target") or p.get("alias_dns_name")
    if rtype in ("NS", "SOA") and domain and name.rstrip(".") == str(domain).rstrip("."):
        return entry(r, ctx, status="auto", via="report", target=None,
                     justification="Zone apex NS/SOA record, leaseweb dns creates its own.")
    ttl = int(first(p, "ttl", default=300))
    nearest = min(DNS_TTLS, key=lambda t: abs(t - ttl))
    notes = ["the domain must be hosted at leaseweb before this record can be created"]
    if nearest != ttl:
        notes.append(f"ttl {ttl} rounded to {nearest}, the only values leaseweb allows")
    if rtype not in DNS_TYPES:
        return entry(r, ctx, status="manual", via="report", target=None,
                     justification=f"{rtype} records aren't supported by leaseweb dns.", notes=notes)
    content = list(p.get("values") or p.get("records") or [])
    if p.get("values_omitted"):
        notes.append(f"{rtype} values weren't scanned (they can hold tokens), copy them by hand")
    if p.get("set_identifier") or p.get("weight") is not None or p.get("failover"):
        notes.append("weighted/failover routing isn't supported, kept as a plain record")
    alias_of = None
    if alias:
        alias_dns = alias.get("dns_name", alias.get("DNSName")) if isinstance(alias, dict) else str(alias)
        alias_of = next((ctx.tf_names[o["id"]] for o in ctx.related(r) if o["type"] in ("lb", "ec2_instance")), None)
        rtype = "A"
        content = []
        notes.append(f"alias to {alias_dns} became an A record to the new {'leaseweb resource ' + alias_of if alias_of else 'ip'} (ip known after apply)")
    for other in ctx.related(r, "elastic_ip"):
        notes.append(f"points at elastic ip {other['id']}, the ip changes on leaseweb")
    return entry(
        r, ctx, status="partial", via="terraform",
        target={"kind": "dns_record", "domain_name": (domain or "").rstrip("."), "name": name if name.endswith(".") else name + ".",
                "type": rtype, "ttl": nearest, "content": content, "alias_of": alias_of},
        justification="Leaseweb DNS record set with the same name and type.", notes=notes,
    )


def route53_zone(r: dict[str, Any], ctx: Context) -> MappingEntry:
    private = bool(props(r).get("private") or props(r).get("private_zone"))
    return entry(
        r, ctx, status="manual", via="report", target=None,
        justification="Zones can't be created with terraform on leaseweb: transfer the domain or point its NS records at leaseweb.",
        notes=["private hosted zone, use /etc/hosts or a resolver on the private network"] if private else [],
    )


# no terraform resource of their own, so via=report keeps the generator from listing them as manual work
def ec2_like_note(kind: str, text: str, status: str = "partial", via: str = "report") -> Callable[[dict[str, Any], Context], MappingEntry]:
    def rule(r: dict[str, Any], ctx: Context) -> MappingEntry:
        return entry(r, ctx, status=status, via=via, target=None, justification=text.format(**_fmt(r, ctx)))
    rule.__name__ = kind
    return rule


def _fmt(r: dict[str, Any], ctx: Context) -> dict[str, str]:
    users = ctx.referrers(r["id"])
    names = ", ".join(sorted(ctx.tf_names.get(u["id"], u["id"]) for u in users)) or "nothing"
    return {"users": names, "name": r.get("name") or r["id"]}


def key_pair(r: dict[str, Any], ctx: Context) -> MappingEntry:
    name = r.get("name") or r["id"]
    users = [i for i in ctx.by_id.values() if i["type"] == "ec2_instance" and props(i).get("key_name") == name]
    if not users:
        return entry(r, ctx, status="auto", via="report", target=None,
                     justification="No instance uses this key, nothing to migrate.")
    names = ", ".join(sorted(ctx.tf_names[u["id"]] for u in users))
    has_key = bool(props(r).get("public_key"))
    return entry(
        # the generator puts the key into each instance's cloud-init, so no resource of its own
        r, ctx, status="auto" if has_key else "partial", via="report",
        target={"kind": "ssh_key", "public_key_from": "inventory" if has_key else "var:ssh_public_key"},
        justification=f"Public key goes into the cloud-init of {names}.",
        notes=[] if has_key else ["public key not in the inventory, pass it as var.ssh_public_key"],
    )


def ebs_volume(r: dict[str, Any], ctx: Context) -> MappingEntry:
    owners = [i for i in ctx.by_id.values() if i["type"] == "ec2_instance"
              and any(v.get("id") == r["id"] for v in props(i).get("volumes") or [])]
    owners += [o for o in ctx.related(r, "ec2_instance") if o not in owners]
    if not owners:
        return entry(r, ctx, status="manual", via="runbook", target=None,
                     justification="Unattached volume: snapshot it and copy the data you still need by hand.")
    owner = ctx.tf_names[owners[0]["id"]]
    is_root = any(v.get("id") == r["id"] and v.get("root") for v in props(owners[0]).get("volumes") or [])
    if is_root:
        return entry(r, ctx, status="auto", via="report", target={"kind": "merged_into_instance", "instance": owner},
                     justification=f"Root disk of {owner}, becomes its root_disk_size.")
    return entry(r, ctx, status="partial", via="runbook", target={"kind": "merged_into_instance", "instance": owner},
                 justification=f"No block volumes on leaseweb, the size was added to {owner}'s root disk, data copied with rsync.")


def elastic_ip(r: dict[str, Any], ctx: Context) -> MappingEntry:
    owner = (ctx.related(r, "ec2_instance") or [None])[0]
    if owner is None:
        return entry(r, ctx, status="auto", via="report", target=None,
                     justification="Not attached to anything on aws, nothing to migrate (release it to stop paying for it).")
    return entry(
        r, ctx, status="manual", via="report", target=None,
        justification="Leaseweb can't reserve or move ips, every instance gets its own public ipv4.",
        notes=[f"{ctx.tf_names[owner['id']]} gets a new ip, update dns and any allow-lists that used the old one"],
    )


def cloudflare_dns_record(r: dict[str, Any], ctx: Context) -> MappingEntry:
    if props(r).get("manual_review") or props(r).get("record_type") not in {"A", "AAAA", "CNAME"}:
        result = unsupported(r, ctx)
        result.justification = "Review proxy behavior or record-specific settings before DNS cutover."
        return result
    return route53_record(r, ctx)


RULES: dict[str, Callable[[dict[str, Any], Context], MappingEntry]] = {
    "ec2_instance": ec2_instance,
    "security_group": security_group,
    "db_instance": db_instance,
    "lb": lb,
    "lb_listener": lb_listener,
    "target_group": target_group,
    "s3_bucket": s3_bucket,
    "cloudflare_r2_bucket": s3_bucket,
    "cloudflare_dns_zone": route53_zone,
    "cloudflare_dns_record": cloudflare_dns_record,
    "route53_record": route53_record,
    "route53_zone": route53_zone,
    "key_pair": key_pair,
    "ebs_volume": ebs_volume,
    "elastic_ip": elastic_ip,
    "vpc": ec2_like_note("vpc", "Collapsed into the leaseweb private network (second nic, dhcp /27), subnet isolation is lost."),
    "subnet": ec2_like_note("subnet", "Collapsed into the leaseweb private network, every instance gets a public ip too (security groups close it)."),
}


def unsupported(r: dict[str, Any], ctx: Context) -> MappingEntry:
    aws_type = props(r).get("aws_type") or r["type"]
    return entry(r, ctx, status="unsupported", via="report", target=None,
                 justification=f"No leaseweb equivalent for {aws_type}.")


def apply_alternative(e: MappingEntry, alt: Alternative, justification: str) -> MappingEntry:
    e.alternative = alt
    e.justification = justification
    e.ai_suggested = True
    e.status = "manual"
    e.via = "report"
    e.notes.append("ai-suggested, review")
    return e
