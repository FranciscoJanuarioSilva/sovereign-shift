"""Read-only Google Cloud inventory, in the same neutral shape the AWS scanner writes.

collect() reads the REST APIs with a viewer token and keeps the raw records.
build_inventory() turns those records into inventory.json and is tested offline (testdata/gcp_api_sample.json).
"""

import hashlib
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

Item = dict[str, Any]
WORLD = "0.0.0.0/0"
DB_PORTS = {"postgres": 5432, "mysql": 3306, "sqlserver": 1433}
READ_ONLY_SCOPE = "https://www.googleapis.com/auth/cloud-platform.read-only"
COMPUTE = "https://compute.googleapis.com/compute/v1/projects/{project}/"
# record types whose values are addresses or names, the rest (TXT, SPF...) can hold tokens
DNS_VALUE_TYPES = {"A", "AAAA", "CNAME", "MX", "NS", "PTR", "SRV", "CAA"}


class ScanError(ValueError):
    pass


# ---------- helpers ----------

def path(url: str | None) -> str:
    """'https://.../projects/p/zones/z/instances/vm' -> 'zones/z/instances/vm', so ids never carry the project."""
    if not url:
        return ""
    if "/projects/" in url:
        tail = url.split("/projects/", 1)[1]
    elif url.startswith("projects/"):
        tail = url.removeprefix("projects/")
    else:
        return url
    return tail.split("/", 1)[1] if "/" in tail else ""


def name_of(url: str | None) -> str:
    return (url or "").rstrip("/").rsplit("/", 1)[-1]


def region_of(location: str) -> str:
    # zones end in a single letter (europe-west4-a), regions don't
    return location.rsplit("-", 1)[0] if re.fullmatch(r"[a-z]+-[a-z]+\d+-[a-z]", location) else location


def location_of(p: str) -> str:
    parts = p.split("/")
    if len(parts) > 1 and parts[0] in ("zones", "regions", "locations"):
        return region_of(parts[1])
    return "global"


def gid(url: str | None, api: str = "") -> str:
    return f"gcp:{api + '/' if api else ''}{path(url)}"


def links(kind: str, *targets: str | None) -> list[Item]:
    return [{"type": kind, "target": t} for t in sorted(set(filter(None, targets)))]


def resource(kind: str, ident: str, region: str, properties: Item, *, name: str,
             tags: dict | None = None, relations: list[Item] | None = None, cloud_type: str = "") -> Item:
    return {
        "id": ident, "type": kind, "region": region, "name": name,
        "properties": {**properties, "cloud_type": cloud_type}, "tags": tags or {},
        "relations": relations or [],
    }


def port_range(spec: str | None) -> tuple[int | None, int | None]:
    if spec in (None, ""):
        return None, None
    start, _, end = str(spec).partition("-")
    return int(start), int(end or start)


def metadata(meta: Item | None) -> dict[str, str]:
    return {i["key"]: i.get("value", "") for i in (meta or {}).get("items", [])}


def truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in ("true", "1", "yes")


def sa_label(email: str) -> str:
    # the default compute account carries the project number, keep it out of names
    local = email.split("@", 1)[0]
    return "default-compute" if re.fullmatch(r"\d+-compute", local) else local


def ssh_keys(text: str) -> list[tuple[str, str]]:
    """'alice:ssh-ed25519 AAAA... alice@laptop' lines -> [(user, public key)]."""
    out = []
    for line in text.splitlines():
        user, sep, key = line.strip().partition(":")
        if sep and key.strip().startswith(("ssh-", "ecdsa-", "sk-")):
            out.append((user, key.strip()))
    return out


def machine_spec(name: str) -> tuple[float | None, float | None]:
    """vcpu and gib parsed from a name, for custom types or Cloud SQL tiers when the api gave nothing."""
    name = name.removeprefix("db-")
    if m := re.search(r"custom-(\d+)-(\d+)", name):
        return int(m.group(1)), int(m.group(2)) / 1024
    if m := re.fullmatch(r"perf-optimized-n-(\d+)", name, re.I):
        return int(m.group(1)), int(m.group(1)) * 8
    shared = {"f1-micro": (1, 0.6), "g1-small": (1, 1.7)}
    if name in shared:
        return shared[name]
    if m := re.fullmatch(r"n1-(standard|highmem|highcpu)-(\d+)", name):
        per = {"standard": 3.75, "highmem": 6.5, "highcpu": 0.9}[m.group(1)]
        return int(m.group(2)), int(m.group(2)) * per
    return None, None


# ---------- firewall rules -> security groups ----------

def firewall_rules(fw: Item, source_instances: list[str]) -> tuple[list[Item], list[str]]:
    """Allow entries of one firewall rule as neutral rules, plus protocols leaseweb can't filter."""
    cidrs = list(fw.get("sourceRanges") or [])
    if not cidrs and not source_instances and not fw.get("sourceTags") and not fw.get("sourceServiceAccounts"):
        # an ingress rule without any source means the whole internet
        cidrs = [WORLD]
    out, skipped = [], []
    for allowed in fw.get("allowed") or []:
        protocol = str(allowed.get("IPProtocol", "all")).lower()
        protocol = {"all": "-1", "6": "tcp", "17": "udp", "1": "icmp"}.get(protocol, protocol)
        if protocol not in ("tcp", "udp", "icmp", "-1"):
            skipped.append(protocol)
            continue
        for spec in allowed.get("ports") or [None]:
            start, end = port_range(spec)
            if start is None and protocol in ("tcp", "udp"):
                start, end = 1, 65535
            # gcp writes 0-65535, port 0 isn't a real port and leaseweb ranges start at 1
            start = max(start, 1) if start is not None else None
            out.append({
                "protocol": protocol, "from_port": start, "to_port": end, "cidrs": cidrs,
                "source_groups": [], "source_instances": source_instances,
                "gcp_rule": fw["name"], "priority": fw.get("priority", 1000),
            })
    return out, skipped


def build_firewalls(raw: Item, instances: list[Item]) -> tuple[list[Item], dict[str, list[str]]]:
    """GCP firewall rules target instances by network, tag or service account.

    One neutral security group per (network, target), so instances use the groups that match them, like aws.
    sourceTags and sourceServiceAccounts become the instances carrying them, resolved to private ips after apply.
    """
    by_network: dict[str, list[Item]] = {}
    for inst in instances:
        for nic in inst.get("networkInterfaces", []):
            by_network.setdefault(path(nic.get("network")), []).append(inst)

    def members(network: str, tags: list[str], accounts: list[str]) -> list[str]:
        out = []
        for inst in by_network.get(network, []):
            emails = {sa.get("email") for sa in inst.get("serviceAccounts", [])}
            if set(tags) & set((inst.get("tags") or {}).get("items", [])) or set(accounts) & emails:
                out.append(gid(inst["selfLink"]))
        return sorted(set(out))

    groups: dict[str, Item] = {}
    for fw in sorted(raw.get("firewalls", []), key=lambda f: (f.get("priority", 1000), f["name"])):
        if fw.get("disabled"):
            continue
        network = path(fw.get("network"))
        net_name = name_of(network)
        targets = [("tag", t, t) for t in fw.get("targetTags") or []]
        targets += [("sa", e, "sa-" + sa_label(e)) for e in fw.get("targetServiceAccounts") or []]
        for kind, value, label in targets or [("all", "", "all")]:
            key = f"{network}/firewall/{kind}/{label}"
            group = groups.setdefault(key, {
                "id": f"gcp:{key}", "network": network, "kind": kind, "value": value,
                "name": f"{net_name}-{label}", "ingress": [], "egress": [], "deny_rules": [],
                "skipped_protocols": [], "rules": [],
            })
            group["rules"].append(fw["name"])
            if fw.get("denied"):
                group["deny_rules"].append(fw["name"])
                continue
            if fw.get("direction", "INGRESS") == "EGRESS":
                group["egress"].append({"gcp_rule": fw["name"], "destinations": fw.get("destinationRanges") or [WORLD]})
                continue
            sources = members(network, fw.get("sourceTags") or [], fw.get("sourceServiceAccounts") or [])
            rules, skipped = firewall_rules(fw, sources)
            group["ingress"] += rules
            group["skipped_protocols"] += skipped

    # which groups each instance ends up in
    uses: dict[str, list[str]] = {}
    for group in groups.values():
        for inst in by_network.get(group["network"], []):
            emails = {sa.get("email") for sa in inst.get("serviceAccounts", [])}
            hit = (
                group["kind"] == "all"
                or (group["kind"] == "tag" and group["value"] in (inst.get("tags") or {}).get("items", []))
                or (group["kind"] == "sa" and group["value"] in emails)
            )
            if hit:
                uses.setdefault(gid(inst["selfLink"]), []).append(group["id"])

    out = []
    for group in groups.values():
        props = {"ingress": group["ingress"], "egress": group["egress"], "gcp_rules": group["rules"]}
        if group["deny_rules"]:
            props["deny_rules"] = group["deny_rules"]
        if group["skipped_protocols"]:
            props["skipped_protocols"] = sorted(set(group["skipped_protocols"]))
        relations = links("in_vpc", gid(group["network"]))
        relations += links("ingress_from_instance", *(i for r in group["ingress"] for i in r["source_instances"]))
        out.append(resource("security_group", group["id"], "global", props, name=group["name"],
                            relations=relations, cloud_type="compute.googleapis.com/Firewall"))
    return out, uses


# ---------- load balancers ----------

def build_load_balancers(raw: Item, refs: Item, members: Item) -> list[Item]:
    """forwarding rule -> proxy -> url map -> backend service -> instance group, flattened to lb/listener/target group.

    Forwarding rules that share an ip are one load balancer (http:80 and https:443 usually do).
    """
    out: list[Item] = []
    lbs: dict[tuple[str, str], Item] = {}
    backends: dict[str, Item] = {}
    rules = sorted(raw.get("forwarding_rules", []), key=lambda f: f["name"])

    def chain(fr: Item) -> tuple[str, Item, Item]:
        target = path(fr.get("target"))
        proxy = refs.get(target, {})
        return target, proxy, refs.get(path(proxy.get("urlMap")), {})

    # name each lb after its serving url map, not the http->https redirect map that shares the ip
    labels: dict[tuple[str, str], str] = {}
    for fr in rules:
        _, proxy, url_map = chain(fr)
        key = (location_of(path(fr["selfLink"])), fr.get("IPAddress") or path(fr["selfLink"]))
        if url_map and not (url_map.get("defaultUrlRedirect") or {}).get("httpsRedirect"):
            labels.setdefault(key, name_of(proxy.get("urlMap")))
    for fr in rules:
        fr_path = path(fr["selfLink"])
        scope = location_of(fr_path)
        target, proxy, url_map = chain(fr)
        service = path(url_map.get("defaultService") or proxy.get("service") or fr.get("backendService"))
        if "/targetPools/" in target:
            service = target
        kind = target.split("/")[-2] if target else "backendServices"
        protocol = {"targetHttpProxies": "HTTP", "targetHttpsProxies": "HTTPS", "targetSslProxies": "TLS"}.get(kind, "TCP")
        if str(fr.get("IPProtocol", "TCP")).upper() == "UDP":
            protocol = "UDP"
        redirect = bool((url_map.get("defaultUrlRedirect") or {}).get("httpsRedirect"))

        key = (scope, fr.get("IPAddress") or fr_path)
        lb = lbs.get(key)
        if lb is None:
            label = labels.get(key) or fr["name"]
            lb = resource(
                "lb", f"gcp:{scope}/loadBalancers/{label}", scope,
                {
                    "lb_type": "application" if protocol in ("HTTP", "HTTPS") else "network",
                    "scheme": "internal" if str(fr.get("loadBalancingScheme", "")).startswith("INTERNAL") else "internet-facing",
                    "ip_address": fr.get("IPAddress"),
                    "load_balancing_scheme": fr.get("loadBalancingScheme"),
                },
                name=label, cloud_type="compute.googleapis.com/ForwardingRule",
            )
            lbs[key] = lb
            out.append(lb)
        start, _ = port_range(fr.get("portRange") or ((fr.get("ports") or [None])[0]))
        out.append(resource(
            "lb_listener", "gcp:" + fr_path, scope,
            {
                "protocol": protocol, "port": start or (443 if protocol == "HTTPS" else 80),
                "default_actions": ["redirect"] if redirect else ["forward"],
                "redirects_to_https": redirect,
                "rules": bool(url_map.get("pathMatchers") or url_map.get("hostRules")),
                "certificates": [name_of(c) for c in proxy.get("sslCertificates") or []],
            },
            name=fr["name"],
            relations=links("listens_on", lb["id"]) + links("forwards_to", None if redirect else (gid(service) if service else None)),
            cloud_type="compute.googleapis.com/ForwardingRule",
        ))
        if service and not redirect:
            backends.setdefault(service, {"lbs": set()})["lbs"].add(lb["id"])

    regions: dict[str, str] = {}
    for service, info in sorted(backends.items()):
        backend = refs.get(service, {})
        scope = location_of(service)
        targets: list[str] = []
        named_port = None
        target_type = "instance"
        for b in backend.get("backends") or []:
            group_path = path(b.get("group"))
            if "/networkEndpointGroups/" in group_path:
                target_type = "network_endpoint_group"
                continue
            group = refs.get(group_path, {})
            targets += [gid(i) for i in members.get(group_path, [])]
            for np in group.get("namedPorts") or []:
                if np.get("name") == backend.get("portName", "http"):
                    named_port = np.get("port")
        if "/targetPools/" in service:
            targets = [gid(i) for i in backend.get("instances") or []]
        hc = refs.get(path((backend.get("healthChecks") or [None])[0]), {})
        hc_type = str(hc.get("type", "TCP")).upper()
        hc_body = hc.get(hc_type.lower() + "HealthCheck") or {}
        if "requestPath" in hc:
            # legacy http health checks (target pools) have no type field
            hc_type = "HTTP"
        protocol = str(backend.get("protocol", "TCP")).upper()
        protocol = {"HTTP2": "HTTP", "SSL": "TCP"}.get(protocol, protocol)
        port = named_port or backend.get("port") or (80 if protocol == "HTTP" else 443 if protocol == "HTTPS" else None)
        targets = sorted(set(targets))
        if scope == "global" and targets:
            # a global lb has no region, it lives where its backends run
            scope = location_of(path(targets[0].removeprefix("gcp:")))
            for lb_id in info["lbs"]:
                regions.setdefault(lb_id, scope)
        out.append(resource(
            "target_group", "gcp:" + service, scope,
            {
                "protocol": protocol, "port": port, "target_type": target_type,
                "health_check_protocol": hc_type, "health_check_path": hc_body.get("requestPath") or hc.get("requestPath"),
                "health_check_port": hc_body.get("port") or hc.get("port") or "traffic-port",
                "targets": [{"id": t} for t in targets],
            },
            name=name_of(service),
            relations=links("associated_with", *sorted(info["lbs"])) + links("targets", *targets),
            cloud_type="compute.googleapis.com/TargetPool" if "/targetPools/" in service else "compute.googleapis.com/BackendService",
        ))
    for r in out:
        lb_id = r["id"] if r["type"] == "lb" else next((x["target"] for x in r["relations"] if x["type"] == "listens_on"), None)
        if r["region"] == "global" and lb_id in regions:
            r["region"] = regions[lb_id]
    return out


# ---------- the inventory ----------

def build_inventory(raw: Item) -> Item:
    """Turn collected GCP REST records into inventory.json."""
    out: list[Item] = []
    refs = {path(k): v for k, v in (raw.get("refs") or {}).items()}
    members = {path(k): [path(i) for i in v] for k, v in (raw.get("group_members") or {}).items()}
    machine_types = {path(k): v for k, v in (raw.get("machine_types") or {}).items()}
    disks = {path(d["selfLink"]): d for d in raw.get("disks", [])}
    instances = [i for i in raw.get("instances", []) if i.get("status") not in ("DELETING",)]
    project_meta = metadata(raw.get("project_metadata"))

    for net in raw.get("networks", []):
        out.append(resource("vpc", gid(net["selfLink"]), "global",
                            {"auto_subnets": net.get("autoCreateSubnetworks", False),
                             "default": net.get("name") == "default", "mtu": net.get("mtu")},
                            name=net["name"], cloud_type="compute.googleapis.com/Network"))
    for sn in raw.get("subnetworks", []):
        out.append(resource("subnet", gid(sn["selfLink"]), region_of(name_of(sn.get("region"))),
                            {"cidr": sn.get("ipCidrRange"), "private_google_access": sn.get("privateIpGoogleAccess", False)},
                            name=sn["name"], relations=links("in_vpc", gid(sn.get("network"))),
                            cloud_type="compute.googleapis.com/Subnetwork"))

    groups, uses = build_firewalls(raw, instances)
    out += groups

    # static external addresses, only the ones on instances: lb addresses travel with the lb
    addresses: dict[str, list[str]] = {}
    for addr in raw.get("addresses", []):
        if addr.get("addressType", "EXTERNAL") != "EXTERNAL":
            continue
        users = [path(u) for u in addr.get("users") or []]
        if any("/forwardingRules/" in u for u in users):
            continue
        owner = next((u for u in users if "/instances/" in u), None)
        ident = gid(addr["selfLink"])
        if owner:
            addresses.setdefault(owner, []).append(ident)
        out.append(resource("elastic_ip", ident, location_of(path(addr["selfLink"])),
                            {"public_ip": addr.get("address"), "status": addr.get("status")},
                            name=addr["name"], relations=links("attached_to", gid(owner) if owner else None),
                            cloud_type="compute.googleapis.com/Address"))

    keys: dict[tuple[str, str], Item] = {}
    used_disks: set[str] = set()
    for inst in instances:
        inst_path = path(inst["selfLink"])
        ident = "gcp:" + inst_path
        region = location_of(inst_path)
        mt_path = path(inst.get("machineType"))
        mt_name = name_of(mt_path)
        spec = machine_types.get(mt_path, {})
        vcpu = spec.get("guestCpus")
        memory = spec["memoryMb"] / 1024 if spec.get("memoryMb") else None
        if vcpu is None:
            vcpu, memory = machine_spec(mt_name)
        meta = metadata(inst.get("metadata"))

        volumes, os_name = [], None
        for d in inst.get("disks", []):
            src = path(d.get("source"))
            disk = disks.get(src, {})
            used_disks.add(src)
            if d.get("boot"):
                os_name = name_of(disk.get("sourceImage")) or name_of((d.get("licenses") or [None])[0]) or None
            volumes.append({
                "id": "gcp:" + src if src else f"{ident}/{d.get('deviceName')}",
                "device_name": d.get("deviceName"), "root": bool(d.get("boot")),
                "size_gib": int(disk.get("sizeGb") or d.get("diskSizeGb") or 0),
                "volume_type": name_of(disk.get("type")), "encrypted": True,
            })

        # ssh keys: instance metadata, plus the project's unless blocked. os login ignores both.
        found = ssh_keys(meta.get("ssh-keys", ""))
        if not truthy(meta.get("block-project-ssh-keys")):
            found += ssh_keys(project_meta.get("ssh-keys", ""))
        key_name = None
        for user, key in found:
            if (region, user) not in keys:
                keys[region, user] = resource("key_pair", f"gcp:{region}/sshKeys/{user}", region,
                                              {"public_key": key, "fingerprint": hashlib.sha256(key.encode()).hexdigest()[:16]},
                                              name=user, cloud_type="compute.googleapis.com/Metadata/ssh-keys")
            key_name = key_name or user
        startup = meta.get("startup-script", "") + meta.get("user-data", "")

        nics = inst.get("networkInterfaces", [])
        public = [c.get("natIP") for n in nics for c in n.get("accessConfigs") or [] if c.get("natIP")]
        props: Item = {
            "instance_type": mt_name, "vcpu": vcpu, "memory_gib": memory,
            "os": os_name, "state": {"TERMINATED": "stopped"}.get(inst.get("status", ""), str(inst.get("status", "")).lower()),
            "public_ip": bool(public), "public_ip_address": public[0] if public else None,
            "private_ip": nics[0].get("networkIP") if nics else None,
            "volumes": volumes, "key_name": key_name,
            "network_tags": (inst.get("tags") or {}).get("items", []),
            "zone": name_of(inst.get("zone")),
        }
        if spec.get("architecture"):
            props["architecture"] = spec["architecture"].lower()
        if startup:
            props["user_data_sha256"] = hashlib.sha256(startup.encode()).hexdigest()
            props["user_data_length"] = len(startup)
        if truthy(meta.get("enable-oslogin") or project_meta.get("enable-oslogin")):
            props["os_login"] = True
        scheduling = inst.get("scheduling") or {}
        if scheduling.get("preemptible") or scheduling.get("provisioningModel") == "SPOT":
            props["spot"] = True
        if inst.get("guestAccelerators"):
            props["accelerators"] = sum(a.get("acceleratorCount", 0) for a in inst["guestAccelerators"])
        out.append(resource(
            "ec2_instance", ident, region, props, name=inst["name"], tags=inst.get("labels") or {},
            relations=(
                links("in_vpc", *(gid(n.get("network")) for n in nics))
                + links("in_subnet", *(gid(n.get("subnetwork")) for n in nics if n.get("subnetwork")))
                + links("uses_security_group", *uses.get(ident, []))
                + links("uses_volume", *(v["id"] for v in volumes))
                + links("uses_key_pair", keys[region, key_name]["id"] if key_name else None)
                + links("uses_elastic_ip", *addresses.get(inst_path, []))
            ),
            cloud_type="compute.googleapis.com/Instance",
        ))
    out += keys.values()

    for disk_path, disk in disks.items():
        users = [gid(u) for u in disk.get("users") or []]
        out.append(resource("ebs_volume", "gcp:" + disk_path, location_of(disk_path),
                            {"size_gib": int(disk.get("sizeGb") or 0), "volume_type": name_of(disk.get("type")),
                             "encrypted": True, "cmek": bool((disk.get("diskEncryptionKey") or {}).get("kmsKeyName"))},
                            name=disk["name"], relations=links("attached_to", *users),
                            cloud_type="compute.googleapis.com/Disk"))

    out += build_load_balancers(raw, refs, members)

    # cloud sql, its authorized networks and private ip access behave like a security group
    by_network = {}
    for inst in instances:
        for nic in inst.get("networkInterfaces", []):
            by_network.setdefault(path(nic.get("network")), []).append(gid(inst["selfLink"]))
    for db in raw.get("sql_instances", []):
        version = str(db.get("databaseVersion", ""))
        engine_raw, _, engine_version = version.partition("_")
        engine = {"POSTGRES": "postgres", "MYSQL": "mysql", "SQLSERVER": "sqlserver"}.get(engine_raw, engine_raw.lower())
        settings = db.get("settings") or {}
        ip = settings.get("ipConfiguration") or {}
        tier = settings.get("tier", "")
        vcpu, memory = machine_spec(tier)
        backup = settings.get("backupConfiguration") or {}
        authorized = [n["value"] for n in ip.get("authorizedNetworks") or [] if n.get("value")]
        public = bool(ip.get("ipv4Enabled"))
        private_net = path(ip.get("privateNetwork"))
        port = DB_PORTS.get(engine)
        ident = f"gcp:sql/instances/{db['name']}"
        region = db.get("region", "global")
        group_id = ident + "/access"
        clients = sorted(set(by_network.get(private_net, []))) if private_net else []
        ingress = []
        if port and (public and authorized or clients):
            ingress.append({"protocol": "tcp", "from_port": port, "to_port": port,
                            "cidrs": sorted(set(authorized)) if public else [], "source_groups": [],
                            "source_instances": clients})
        out.append(resource("security_group", group_id, region, {"ingress": ingress, "egress": []},
                            name=f"{db['name']}-access", relations=links("in_vpc", gid(private_net) if private_net else None),
                            cloud_type="sqladmin.googleapis.com/Instance/ipConfiguration"))
        out.append(resource(
            "db_instance", ident, region,
            {
                "engine": engine, "engine_version": engine_version.replace("_", "."), "instance_class": tier,
                "vcpu": vcpu, "memory_gib": memory,
                "storage_gib": int(settings.get("dataDiskSizeGb") or 10),
                "storage_encrypted": True,
                "publicly_accessible": public and bool(authorized),
                "backup_retention_days": ((backup.get("backupRetentionSettings") or {}).get("retainedBackups") or 7) if backup.get("enabled") else 0,
                "multi_az": settings.get("availabilityType") == "REGIONAL",
                "port": port, "edition": settings.get("edition"),
                "replica": db.get("instanceType") == "READ_REPLICA_INSTANCE",
            },
            name=db["name"], tags=settings.get("userLabels") or {},
            relations=(links("in_vpc", gid(private_net) if private_net else None) + links("uses_security_group", group_id)
                       + links("replica_of", f"gcp:sql/instances/{db['masterInstanceName'].split(':')[-1]}" if db.get("masterInstanceName") else None)),
            cloud_type="sqladmin.googleapis.com/Instance",
        ))

    for bucket in raw.get("buckets", []):
        iam = (raw.get("bucket_iam") or {}).get(bucket["name"]) or {}
        public_members = {"allUsers", "allAuthenticatedUsers"}
        cfg = bucket.get("iamConfiguration") or {}
        props = {
            "policy_public": any(public_members & set(b.get("members", [])) for b in iam.get("bindings", [])),
            "public_access_block": {f: cfg.get("publicAccessPrevention") == "enforced"
                                    for f in ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")},
            "encryption": ["kms" if (bucket.get("encryption") or {}).get("defaultKmsKeyName") else "google-managed"],
            "versioning": "Enabled" if (bucket.get("versioning") or {}).get("enabled") else "Disabled",
            "storage_class": bucket.get("storageClass"),
            "uniform_access": bool((cfg.get("uniformBucketLevelAccess") or {}).get("enabled")),
        }
        if not iam:
            props.pop("policy_public")
        if (bucket.get("website") or {}).get("mainPageSuffix"):
            props["static_website"] = True
        out.append(resource("s3_bucket", f"gcp:storage/b/{bucket['name']}", str(bucket.get("location", "")).lower() or "global",
                            props, name=bucket["name"], tags=bucket.get("labels") or {},
                            cloud_type="storage.googleapis.com/Bucket"))

    # dns records point at whatever owns the address, so the translator can redirect them
    owners: dict[str, list[str]] = {}
    for r in out:
        p = r["properties"]
        for value in (p.get("public_ip_address"), p.get("ip_address"), p.get("public_ip") if r["type"] == "elastic_ip" else None):
            if isinstance(value, str):
                owners.setdefault(value, []).append(r["id"])
    for zone in raw.get("dns_zones", []):
        zone_id = f"gcp:dns/managedZones/{zone['name']}"
        out.append(resource("route53_zone", zone_id, "global", {"private": zone.get("visibility") == "private",
                                                                 "dnssec": (zone.get("dnssecConfig") or {}).get("state") == "on"},
                            name=zone["dnsName"], tags=zone.get("labels") or {}, cloud_type="dns.googleapis.com/ManagedZone"))
        for rec in (raw.get("dns_records") or {}).get(zone["name"], []):
            rtype = rec["type"]
            props: Item = {"record_type": rtype, "ttl": rec.get("ttl", 300), "zone_name": zone["dnsName"]}
            values = list(rec.get("rrdatas") or [])
            if rtype in DNS_VALUE_TYPES:
                props["values"] = values
            elif values:
                props["values_omitted"] = True
            if rec.get("routingPolicy"):
                props["routing_policy"] = next(iter(rec["routingPolicy"]), "custom")
            targets = [o for v in props.get("values", []) for o in owners.get(v, [])]
            out.append(resource("route53_record", f"{zone_id}/rrsets/{rec['name']}/{rtype}", "global", props,
                                name=rec["name"], relations=links("in_zone", zone_id) + links("points_to", *targets),
                                cloud_type="dns.googleapis.com/ResourceRecordSet"))

    for o in raw.get("other", []):
        out.append(resource("other", o["id"], o.get("region") or "global", o.get("properties") or {},
                            name=o["name"], tags=o.get("labels") or {}, cloud_type=o["cloud_type"]))

    # multi-region bucket locations (eu, us, eur4) aren't regions
    regions = sorted({r["region"] for r in out if re.search(r"-[a-z]+\d", r["region"])})
    return {
        "source": "gcp",
        "account_id": raw.get("project_id", ""),
        "scanned_at": raw.get("scanned_at") or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "regions": regions,
        "denied": raw.get("denied") or [],
        "resources": sorted(out, key=lambda r: (r["region"], r["type"], r["id"])),
    }


# ---------- live collection ----------

class Reader:
    """GET (and the read-only listInstances POST) against the google apis, 403 recorded as denied."""

    def __init__(self, client: httpx.Client, project: str) -> None:
        self.client = client
        self.project = project
        self.denied: list[Item] = []

    def call(self, url: str, service: str, method: str = "GET", params: Item | None = None) -> Item | None:
        # read-only on purpose: the only post we make is instanceGroups.listInstances, which lists members
        if method != "GET" and not url.endswith("/listInstances"):
            raise ScanError(f"refusing a {method} call, the scanner is read-only")
        response = self.client.request(method, url, params=params, json={"instanceState": "ALL"} if method == "POST" else None)
        if response.status_code in (401, 403):
            reason = ""
            try:
                details = response.json().get("error", {})
                reason = (details.get("errors") or [{}])[0].get("reason") or details.get("status", "")
            except ValueError:
                pass
            error = "ServiceDisabled" if reason in ("accessNotConfigured", "SERVICE_DISABLED") else "AccessDenied"
            operation = path(url.split("?")[0]) or url.split("/projects/")[0]
            self.denied.append({"service": service, "region": "global", "operation": operation, "error": error})
            return None
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise ScanError(f"Google Cloud scan failed in {service} (HTTP {response.status_code})")
        return response.json()

    def rows(self, url: str, service: str, key: str = "items", method: str = "GET") -> list[Item]:
        out, token, seen = [], None, set()
        while True:
            body = self.call(url, service, method, {"pageToken": token} if token else None)
            if body is None:
                return out
            found = body.get(key)
            if isinstance(found, dict):
                # aggregated lists: {"zones/x": {"instances": [...]}, ...}
                for scoped in found.values():
                    for value in scoped.values():
                        if isinstance(value, list):
                            out += value
            else:
                out += found or []
            token = body.get("nextPageToken")
            if not token:
                return out
            if token in seen:
                raise ScanError("Google Cloud returned a repeated page token")
            seen.add(token)


def collect(project: str, client: httpx.Client) -> Item:
    """Every record build_inventory needs, read with a viewer role."""
    reader = Reader(client, project)
    compute = COMPUTE.format(project=project)
    raw: Item = {"project_id": project, "refs": {}, "group_members": {}, "machine_types": {}}

    def ref(url: str | None, service: str = "compute") -> Item:
        p = path(url)
        if not p:
            return {}
        if p not in raw["refs"]:
            raw["refs"][p] = reader.call(compute + p, service) or {}
        return raw["refs"][p]

    raw["networks"] = reader.rows(compute + "global/networks", "compute")
    raw["subnetworks"] = reader.rows(compute + "aggregated/subnetworks", "compute")
    raw["firewalls"] = reader.rows(compute + "global/firewalls", "compute")
    raw["instances"] = reader.rows(compute + "aggregated/instances", "compute")
    raw["disks"] = reader.rows(compute + "aggregated/disks", "compute")
    raw["addresses"] = reader.rows(compute + "aggregated/addresses", "compute") + reader.rows(compute + "global/addresses", "compute")
    raw["project_metadata"] = (reader.call(compute.rstrip("/"), "compute") or {}).get("commonInstanceMetadata", {})
    for inst in raw["instances"]:
        mt = path(inst.get("machineType"))
        if mt and mt not in raw["machine_types"]:
            raw["machine_types"][mt] = reader.call(compute + mt, "compute") or {}

    # aggregated forwarding rules include the global ones, dedupe in case the api lists them twice
    rules = reader.rows(compute + "aggregated/forwardingRules", "compute") + reader.rows(compute + "global/forwardingRules", "compute")
    raw["forwarding_rules"] = list({r["selfLink"]: r for r in rules}.values())
    for fr in raw["forwarding_rules"]:
        target = ref(fr.get("target"))
        url_map = ref(target.get("urlMap"))
        services = [fr.get("backendService"), target.get("service"), url_map.get("defaultService")]
        services += [m.get("defaultService") for m in url_map.get("pathMatchers") or []]
        for service in filter(None, services):
            backend = ref(service)
            for hc in backend.get("healthChecks") or []:
                ref(hc)
            for b in backend.get("backends") or []:
                group = path(b.get("group"))
                if "/instanceGroups/" in group and group not in raw["group_members"]:
                    ref(group)
                    listed = reader.rows(compute + group + "/listInstances", "compute", method="POST")
                    raw["group_members"][group] = [i["instance"] for i in listed if i.get("instance")]
        for proxy_cert in target.get("sslCertificates") or []:
            raw["refs"].setdefault(path(proxy_cert), {"name": name_of(proxy_cert)})

    raw["sql_instances"] = reader.rows(f"https://sqladmin.googleapis.com/v1/projects/{project}/instances", "sqladmin")
    body = reader.call("https://storage.googleapis.com/storage/v1/b", "storage", params={"project": project})
    raw["buckets"] = (body or {}).get("items", [])
    raw["bucket_iam"] = {}
    for bucket in raw["buckets"]:
        policy = reader.call(f"https://storage.googleapis.com/storage/v1/b/{quote(bucket['name'], safe='')}/iam", "storage")
        if policy:
            raw["bucket_iam"][bucket["name"]] = {"bindings": policy.get("bindings", [])}

    dns = f"https://dns.googleapis.com/dns/v1/projects/{project}/managedZones"
    raw["dns_zones"] = reader.rows(dns, "dns", key="managedZones")
    raw["dns_records"] = {z["name"]: reader.rows(f"{dns}/{quote(z['name'], safe='')}/rrsets", "dns", key="rrsets")
                          for z in raw["dns_zones"]}

    # services without a neutral type, metadata only (never env vars, code or data)
    other = []
    for service, url, key, cloud_type, keep in [
        ("container", f"https://container.googleapis.com/v1/projects/{project}/locations/-/clusters", "clusters",
         "container.googleapis.com/Cluster", lambda c: {"node_count": c.get("currentNodeCount"), "autopilot": bool((c.get("autopilot") or {}).get("enabled")),
                                                       "machine_types": sorted({(p.get("config") or {}).get("machineType") for p in c.get("nodePools") or []} - {None})}),
        ("run", f"https://run.googleapis.com/v2/projects/{project}/locations/-/services", "services",
         "run.googleapis.com/Service", lambda s: {"ingress": s.get("ingress")}),
        ("cloudfunctions", f"https://cloudfunctions.googleapis.com/v2/projects/{project}/locations/-/functions", "functions",
         "cloudfunctions.googleapis.com/Function", lambda f: {"runtime": (f.get("buildConfig") or {}).get("runtime")}),
        ("redis", f"https://redis.googleapis.com/v1/projects/{project}/locations/-/instances", "instances",
         "redis.googleapis.com/Instance", lambda r: {"tier": r.get("tier"), "memory_size_gb": r.get("memorySizeGb"), "redis_version": r.get("redisVersion")}),
        ("pubsub", f"https://pubsub.googleapis.com/v1/projects/{project}/topics", "topics",
         "pubsub.googleapis.com/Topic", lambda t: {}),
    ]:
        for row in reader.rows(url, service, key=key):
            p = path(row.get("selfLink") or row.get("name"))
            other.append({"id": f"gcp:{service}/{p}", "name": name_of(p), "region": location_of(p),
                          "cloud_type": cloud_type, "properties": keep(row), "labels": row.get("labels") or row.get("resourceLabels") or {}})
    raw["other"] = other
    raw["denied"] = reader.denied
    return raw


def access_token() -> str:
    """A token from GCP_ACCESS_TOKEN, or application default credentials with the read-only scope."""
    token = os.getenv("GCP_ACCESS_TOKEN")
    if token:
        return token
    try:
        import google.auth
        import google.auth.transport.requests
    except ImportError:
        raise ScanError("Set GCP_ACCESS_TOKEN (gcloud auth print-access-token --impersonate-service-account=<viewer sa>) "
                        "or install google-auth for application default credentials") from None
    try:
        credentials, _ = google.auth.default(scopes=[READ_ONLY_SCOPE])
        credentials.refresh(google.auth.transport.requests.Request())
    except Exception:
        raise ScanError("No Google Cloud credentials found (GCP_ACCESS_TOKEN or application default credentials)") from None
    return credentials.token


def scan(project: str | None = None) -> Item:
    project = project or os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    if not project or not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project):
        raise ScanError("Set GCP_PROJECT_ID (or pass --project) to a valid Google Cloud project id")
    with httpx.Client(timeout=30, headers={"Authorization": f"Bearer {access_token()}"}) as client:
        try:
            return build_inventory(collect(project, client))
        except ScanError:
            raise
        except (httpx.RequestError, KeyError, TypeError, ValueError):
            raise ScanError("Unable to read Google Cloud inventory metadata") from None
