"""Read-only Azure inventory (Reader role), in the same neutral shape the AWS scanner writes.

Not verified against a live subscription yet: build_inventory() is tested with SDK-shaped sample
records (testdata/azure_sdk_sample.json). The live part only collects those records with the SDK.
"""

import ipaddress
import os
from datetime import datetime, timezone
from typing import Any

Item = dict[str, Any]
WORLD = {"*", "internet", "0.0.0.0/0", "any"}
DB_PORTS = {"postgres": 5432, "mysql": 3306}


class ScanError(Exception):
    pass


def name_of(arm_id: str | None) -> str:
    return (arm_id or "").rstrip("/").rsplit("/", 1)[-1]


def parent(arm_id: str, levels: int = 2) -> str:
    # an ip configuration id ends in /ipConfigurations/<name>, its nic is two segments up
    return arm_id.rstrip("/").rsplit("/", levels)[0]


def links(kind: str, *targets: str | None) -> list[Item]:
    return [{"type": kind, "target": t} for t in sorted(set(filter(None, targets)))]


def resource(kind: str, ident: str, region: str, properties: Item, *, name: str | None = None,
             tags: dict | None = None, relations: list[Item] | None = None, cloud_type: str = "") -> Item:
    return {
        "id": ident, "type": kind, "region": region, "name": name or name_of(ident),
        "properties": {**properties, "cloud_type": cloud_type}, "tags": tags or {},
        "relations": relations or [],
    }


def port_range(value: str) -> tuple[int | None, int | None]:
    if value in ("*", "", None):
        return None, None
    start, _, end = str(value).partition("-")
    return int(start), int(end or start)


def nsg_rules(rules: list[Item]) -> list[Item]:
    """Inbound Allow rules as neutral rules. A Deny that comes first (lower priority) and covers everything wins."""
    out = []
    blocked_all = False
    for rule in sorted(rules, key=lambda r: r.get("priority", 65000)):
        if str(rule.get("direction", "")).lower() != "inbound":
            continue
        sources = [rule.get("source_address_prefix")] + list(rule.get("source_address_prefixes") or [])
        sources = [s for s in sources if s]
        if str(rule.get("access", "")).lower() == "deny":
            blocked_all = blocked_all or ({str(s).lower() for s in sources} & WORLD and rule.get("destination_port_range") == "*")
            continue
        if blocked_all:
            continue
        cidrs = []
        for s in sources:
            if str(s).lower() in WORLD:
                cidrs.append("0.0.0.0/0")
            else:
                try:
                    cidrs.append(str(ipaddress.ip_network(s, strict=False)))
                except ValueError:
                    pass  # service tags like VirtualNetwork stay internal, nothing to open
        protocol = {"tcp": "tcp", "udp": "udp", "icmp": "icmp", "*": "-1"}.get(str(rule.get("protocol", "*")).lower(), "-1")
        ranges = [rule.get("destination_port_range")] + list(rule.get("destination_port_ranges") or [])
        for value in [r for r in ranges if r]:
            start, end = port_range(value)
            # "*" on tcp or udp means every port of that protocol, not every protocol
            if start is None and protocol in ("tcp", "udp"):
                start, end = 0, 65535
            if cidrs:
                out.append({"protocol": protocol, "from_port": start, "to_port": end, "cidrs": cidrs, "source_groups": []})
    return out


def firewall_cidrs(rules: list[Item]) -> list[str]:
    cidrs = []
    for r in rules:
        start, end = ipaddress.ip_address(r["start_ip_address"]), ipaddress.ip_address(r["end_ip_address"])
        if str(start) == "0.0.0.0" and str(end) == "255.255.255.255":
            cidrs.append("0.0.0.0/0")
        else:
            cidrs += [str(n) for n in ipaddress.summarize_address_range(start, end)]
    return cidrs


def build_inventory(raw: Item) -> Item:
    """Turn collected Azure records (SDK as_dict() shape) into inventory.json."""
    out: list[Item] = []
    sizes = {loc: {s["name"]: s for s in items} for loc, items in raw.get("vm_sizes", {}).items()}
    disks = {d["id"]: d for d in raw.get("disks", [])}
    nics = {n["id"]: n for n in raw.get("network_interfaces", [])}
    pips = {p["id"]: p for p in raw.get("public_ips", [])}
    vm_of_nic = {n_id: vm["id"] for vm in raw.get("virtual_machines", [])
                 for n_id in (x["id"] for x in vm.get("network_profile", {}).get("network_interfaces", []))}
    subnet_nsg: dict[str, str] = {}

    for vnet in raw.get("virtual_networks", []):
        loc = vnet["location"]
        out.append(resource("vpc", vnet["id"], loc, {"cidr": (vnet.get("address_space", {}).get("address_prefixes") or [None])[0]},
                            name=vnet["name"], tags=vnet.get("tags"), cloud_type="Microsoft.Network/virtualNetworks"))
        for sn in vnet.get("subnets", []):
            nsg = (sn.get("network_security_group") or {}).get("id")
            if nsg:
                subnet_nsg[sn["id"]] = nsg
            out.append(resource("subnet", sn["id"], loc, {"cidr": sn.get("address_prefix")}, name=sn["name"],
                                relations=links("in_vpc", vnet["id"]), cloud_type="Microsoft.Network/virtualNetworks/subnets"))

    for nsg in raw.get("network_security_groups", []):
        out.append(resource("security_group", nsg["id"], nsg["location"], {"ingress": nsg_rules(nsg.get("security_rules", [])), "egress": []},
                            name=nsg["name"], tags=nsg.get("tags"), cloud_type="Microsoft.Network/networkSecurityGroups"))

    keys: dict[str, Item] = {}
    for vm in raw.get("virtual_machines", []):
        loc = vm["location"]
        size = vm["hardware_profile"]["vm_size"]
        spec = sizes.get(loc, {}).get(size, {})
        image = vm.get("storage_profile", {}).get("image_reference") or {}
        os_disk = vm.get("storage_profile", {}).get("os_disk", {})
        volumes = []
        for disk_ref, root in [(os_disk, True)] + [(d, False) for d in vm.get("storage_profile", {}).get("data_disks", [])]:
            d = disks.get((disk_ref.get("managed_disk") or {}).get("id"), {})
            volumes.append({"id": d.get("id") or disk_ref.get("name"), "size_gib": d.get("disk_size_gb") or disk_ref.get("disk_size_gb"),
                            "encrypted": bool(d.get("encryption", {}).get("type")), "root": root})
        ssh = (((vm.get("os_profile") or {}).get("linux_configuration") or {}).get("ssh") or {}).get("public_keys") or []
        key_name = None
        if ssh:
            key_name = f"{vm['name']}-ssh"
            keys[key_name] = resource("key_pair", f"{vm['id']}/sshKey", loc, {"public_key": ssh[0].get("key_data")},
                                      name=key_name, cloud_type="Microsoft.Compute/sshPublicKeys")
        subnets, groups, ips = [], [], []
        for ref in vm.get("network_profile", {}).get("network_interfaces", []):
            nic = nics.get(ref["id"], {})
            if (nic.get("network_security_group") or {}).get("id"):
                groups.append(nic["network_security_group"]["id"])
            for cfg in nic.get("ip_configurations", []):
                sn = (cfg.get("subnet") or {}).get("id")
                subnets.append(sn)
                groups.append(subnet_nsg.get(sn))
                ips.append((cfg.get("public_ip_address") or {}).get("id"))
        out.append(resource(
            "ec2_instance", vm["id"], loc,
            {
                "instance_type": size,
                "vcpu": spec.get("number_of_cores"),
                "memory_gib": (spec.get("memory_in_mb") or 0) / 1024 or None,
                "os": f"{image.get('offer', '')} {image.get('sku', '')}".strip().lower() or None,
                "volumes": volumes, "key_name": key_name, "public_ip": any(ips),
            },
            name=vm["name"], tags=vm.get("tags"),
            relations=links("in_subnet", *subnets) + links("uses_security_group", *groups)
            + links("uses_volume", *(v["id"] for v in volumes)) + links("uses_elastic_ip", *ips),
            cloud_type="Microsoft.Compute/virtualMachines",
        ))
    out += keys.values()

    for d in raw.get("disks", []):
        out.append(resource("ebs_volume", d["id"], d["location"], {"size_gib": d.get("disk_size_gb"), "encrypted": bool(d.get("encryption", {}).get("type"))},
                            name=d["name"], cloud_type="Microsoft.Compute/disks"))

    for p in raw.get("public_ips", []):
        cfg = (p.get("ip_configuration") or {}).get("id", "")
        vm = vm_of_nic.get(parent(cfg)) if "/networkInterfaces/" in cfg else None
        out.append(resource("elastic_ip", p["id"], p["location"], {"public_ip": p.get("ip_address")}, name=p["name"],
                            relations=links("attached_to", vm), cloud_type="Microsoft.Network/publicIPAddresses"))

    for lb in raw.get("load_balancers", []):
        loc = lb["location"]
        public = any((f.get("public_ip_address") or {}).get("id") for f in lb.get("frontend_ip_configurations", []))
        out.append(resource("lb", lb["id"], loc, {"lb_type": "network", "scheme": "internet-facing" if public else "internal"},
                            name=lb["name"], tags=lb.get("tags"), cloud_type="Microsoft.Network/loadBalancers"))
        probes = {p["id"]: p for p in lb.get("probes", [])}
        rules_by_pool: dict[str, Item] = {}
        for rule in lb.get("load_balancing_rules", []):
            pool = (rule.get("backend_address_pool") or {}).get("id")
            rules_by_pool[pool] = rule
            out.append(resource("lb_listener", rule["id"], loc,
                                {"protocol": "TCP" if str(rule.get("protocol")).lower() == "tcp" else "UDP", "port": rule.get("frontend_port")},
                                name=f"{lb['name']}-{rule['name']}", relations=links("listens_on", lb["id"]) + links("forwards_to", pool),
                                cloud_type="Microsoft.Network/loadBalancers/loadBalancingRules"))
        for pool in lb.get("backend_address_pools", []):
            members = [vm_of_nic.get(parent(c["id"])) for c in pool.get("backend_ip_configurations", [])]
            rule = rules_by_pool.get(pool["id"], {})
            probe = probes.get((rule.get("probe") or {}).get("id"), {})
            out.append(resource(
                "target_group", pool["id"], loc,
                {
                    "protocol": "HTTP" if str(probe.get("protocol", "")).lower() == "http" else "TCP",
                    "port": rule.get("backend_port"), "target_type": "instance",
                    "health_check_path": probe.get("request_path"), "health_check_protocol": str(probe.get("protocol", "TCP")).upper(),
                    "health_check_port": probe.get("port"), "targets": [{"id": m} for m in members if m],
                },
                name=f"{lb['name']}-{pool['name']}",
                relations=links("associated_with", lb["id"]) + links("targets", *members),
                cloud_type="Microsoft.Network/loadBalancers/backendAddressPools",
            ))

    for engine, servers in (("postgres", raw.get("postgres", [])), ("mysql", raw.get("mysql", []))):
        for s in servers:
            loc = s["location"]
            sku = s.get("sku", {}).get("name")
            spec = sizes.get(loc, {}).get(sku, {})
            fw_rules = raw.get("db_firewall", {}).get(s["id"], [])
            public = (s.get("network") or {}).get("public_network_access") == "Enabled"
            relations = []
            if public and fw_rules:
                # the server firewall acts like a security group, so model it as one
                fw_id = f"{s['id']}/firewall"
                port = DB_PORTS[engine]
                out.append(resource("security_group", fw_id, loc,
                                    {"ingress": [{"protocol": "tcp", "from_port": port, "to_port": port, "cidrs": firewall_cidrs(fw_rules), "source_groups": []}],
                                     "egress": []},
                                    name=f"{s['name']}-firewall", cloud_type="Microsoft.DBforPostgreSQL/flexibleServers/firewallRules"))
                relations = links("uses_security_group", fw_id)
            out.append(resource(
                "db_instance", s["id"], loc,
                {
                    "engine": engine, "engine_version": s.get("version"), "instance_class": sku,
                    "vcpu": spec.get("number_of_cores"), "memory_gib": (spec.get("memory_in_mb") or 0) / 1024 or None,
                    "storage_gib": (s.get("storage") or {}).get("storage_size_gb"),
                    "publicly_accessible": public, "storage_encrypted": True,
                    "multi_az": (s.get("high_availability") or {}).get("mode", "Disabled") != "Disabled",
                    "backup_retention_days": (s.get("backup") or {}).get("backup_retention_days"),
                    "port": DB_PORTS[engine],
                },
                name=s["name"], tags=s.get("tags"), relations=relations,
                cloud_type=f"Microsoft.DB{'forPostgreSQL' if engine == 'postgres' else 'forMySQL'}/flexibleServers",
            ))

    for a in raw.get("storage_accounts", []):
        out.append(resource("s3_bucket", a["id"], a["location"],
                            {"public": bool(a.get("allow_blob_public_access")), "encryption": ["AES256"], "versioning": "Unknown"},
                            name=a["name"], tags=a.get("tags"), cloud_type="Microsoft.Storage/storageAccounts"))

    for z in raw.get("dns_zones", []):
        out.append(resource("route53_zone", z["id"], "global", {}, name=z["name"] + ".", cloud_type="Microsoft.Network/dnszones"))
        for rec in raw.get("dns_records", {}).get(z["id"], []):
            rtype = rec["type"].rsplit("/", 1)[-1]
            values = [a["ipv4_address"] for a in rec.get("a_records") or []] + ([rec["cname_record"]["cname"]] if rec.get("cname_record") else [])
            # point at whatever owns the ip (load balancer or vm), so the translator can redirect the record
            pip_targets = []
            for pip in raw.get("public_ips", []):
                if pip.get("ip_address") in values:
                    cfg = (pip.get("ip_configuration") or {}).get("id", "")
                    owner = parent(cfg) if "/loadBalancers/" in cfg else vm_of_nic.get(parent(cfg))
                    pip_targets += [pip["id"], owner]
            out.append(resource("route53_record", rec["id"], "global", {"record_type": rtype, "ttl": rec.get("ttl"), "values": values},
                                name=f"{rec['name']}.{z['name']}.", relations=links("in_zone", z["id"]) + links("points_to", *pip_targets),
                                cloud_type="Microsoft.Network/dnszones/recordsets"))

    for o in raw.get("other", []):
        out.append(resource("other", o["id"], o.get("location", "global"), {"kind": o.get("kind")}, name=o["name"],
                            tags=o.get("tags"), cloud_type=o["type"]))

    regions = sorted({r["region"] for r in out if r["region"] != "global"})
    return {
        "source": "azure",
        "account_id": raw.get("subscription_id", ""),
        "scanned_at": raw.get("scanned_at") or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "regions": regions,
        "resources": sorted(out, key=lambda r: (r["region"], r["type"], r["id"])),
        **({"denied": raw["denied"]} if raw.get("denied") else {}),
    }


def collect(subscription_id: str) -> Item:  # pragma: no cover - needs a live subscription
    """Read every record build_inventory needs, with the Reader role only."""
    try:
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.compute import ComputeManagementClient
        from azure.mgmt.network import NetworkManagementClient
        from azure.mgmt.rdbms.mysql_flexibleservers import MySQLManagementClient
        from azure.mgmt.rdbms.postgresql_flexibleservers import PostgreSQLManagementClient
        from azure.mgmt.resource import ResourceManagementClient
        from azure.mgmt.storage import StorageManagementClient
        from azure.mgmt.dns import DnsManagementClient
    except ImportError as exc:
        raise ScanError("Azure SDK missing: pip install -e '.[azure]'") from exc

    cred = DefaultAzureCredential()
    compute = ComputeManagementClient(cred, subscription_id)
    network = NetworkManagementClient(cred, subscription_id)
    raw: Item = {"subscription_id": subscription_id, "denied": []}

    def grab(key: str, call) -> list:
        try:
            return [x.as_dict() for x in call()]
        except Exception as exc:  # one denied service shouldn't stop the scan
            raw["denied"].append({"service": key, "error": type(exc).__name__})
            return []

    raw["virtual_machines"] = grab("virtual_machines", compute.virtual_machines.list_all)
    raw["disks"] = grab("disks", compute.disks.list)
    raw["vm_sizes"] = {loc: grab(f"vm_sizes:{loc}", lambda loc=loc: compute.virtual_machine_sizes.list(loc))
                       for loc in sorted({vm["location"] for vm in raw["virtual_machines"]})}
    raw["network_interfaces"] = grab("network_interfaces", network.network_interfaces.list_all)
    raw["public_ips"] = grab("public_ips", network.public_ip_addresses.list_all)
    raw["network_security_groups"] = grab("nsgs", network.network_security_groups.list_all)
    raw["virtual_networks"] = grab("vnets", network.virtual_networks.list_all)
    raw["load_balancers"] = grab("load_balancers", network.load_balancers.list_all)
    pg = PostgreSQLManagementClient(cred, subscription_id)
    my = MySQLManagementClient(cred, subscription_id)
    raw["postgres"] = grab("postgres", pg.servers.list)
    raw["mysql"] = grab("mysql", my.servers.list)
    raw["db_firewall"] = {}
    for client, servers in ((pg, raw["postgres"]), (my, raw["mysql"])):
        for s in servers:
            rg = s["id"].split("/resourceGroups/")[1].split("/")[0]
            raw["db_firewall"][s["id"]] = grab(f"firewall:{s['name']}", lambda rg=rg, s=s, c=client: c.firewall_rules.list_by_server(rg, s["name"]))
    raw["storage_accounts"] = grab("storage", StorageManagementClient(cred, subscription_id).storage_accounts.list)
    dns = DnsManagementClient(cred, subscription_id)
    raw["dns_zones"] = grab("dns_zones", dns.zones.list)
    raw["dns_records"] = {}
    for z in raw["dns_zones"]:
        rg = z["id"].split("/resourceGroups/")[1].split("/")[0]
        raw["dns_records"][z["id"]] = grab(f"dns:{z['name']}", lambda rg=rg, z=z: dns.record_sets.list_all_by_dns_zone(rg, z["name"]))
    known = ("Microsoft.Compute/", "Microsoft.Network/", "Microsoft.DBforPostgreSQL/", "Microsoft.DBforMySQL/", "Microsoft.Storage/")
    everything = grab("resources", ResourceManagementClient(cred, subscription_id).resources.list)
    raw["other"] = [r for r in everything if not r["type"].startswith(known)]
    return raw


def scan(subscription_id: str | None = None) -> Item:  # pragma: no cover - needs a live subscription
    subscription_id = subscription_id or os.environ.get("AZURE_SUBSCRIPTION_ID")
    if not subscription_id:
        raise ScanError("Set AZURE_SUBSCRIPTION_ID (and Reader credentials for DefaultAzureCredential).")
    return build_inventory(collect(subscription_id))
