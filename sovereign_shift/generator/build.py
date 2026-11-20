import hashlib
import json
import re
from collections import defaultdict
from ipaddress import ip_network
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from sovereign_shift.artifacts import indexed, save, write

API = "https://api.leaseweb.com/publicCloud/v1"
KINDS = {
    "public_cloud_instance": "public_cloud_instance",
    # the database lands on its own instance, the data itself moves with the runbook
    "self_hosted_db": "public_cloud_instance",
    "load_balancer": "public_cloud_load_balancer",
    "target_group": "public_cloud_target_group",
    "lb_listener": "public_cloud_load_balancer_listener",
    "dns_record": "dns_resource_record_set",
}


VMS = {"public_cloud_instance", "self_hosted_db"}

# the provider adds the private nic after launch (AddToPrivateNetwork), so it can show up after cloud-init ran.
# the name differs per platform (eth1 on the old one, enp*/ens* on the openstack one), so match "any nic without ipv4".
PRIVATE_NET = """#!/bin/sh
# waits up to 10 min for the leaseweb private network nic and brings it up with dhcp
f=/etc/netplan/60-leaseweb-private.yaml
for try in $(seq 60); do
  nics=""
  for i in $(ls /sys/class/net); do
    [ "$i" = lo ] && continue
    ip -4 -o addr show dev "$i" | grep -q inet || nics="$nics $i"
  done
  if [ -n "$nics" ]; then
    printf 'network:\\n  version: 2\\n  ethernets:\\n' > "$f"
    for i in $nics; do
      # no default route over the private network
      printf '    %s:\\n      dhcp4: true\\n      dhcp4-overrides:\\n        use-routes: false\\n' "$i" >> "$f"
    done
    chmod 600 "$f" && netplan apply && exit 0
  fi
  sleep 10
done
"""

# same major version as on aws, ubuntu's own packages are older and pg_restore can't go backwards
PGDG_KEY = "B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8"


def cloud_init(keys: list[str], db: dict | None = None) -> str:
    config: dict = {
        "write_files": [
            {"path": "/usr/local/sbin/leaseweb-private-net", "permissions": "0755", "content": PRIVATE_NET},
        ],
        "runcmd": [["sh", "-c", "nohup /usr/local/sbin/leaseweb-private-net >/var/log/leaseweb-private-net.log 2>&1 &"]],
    }
    if keys:
        config["ssh_authorized_keys"] = keys
    if db:
        engine = str(db.get("engine", "")).lower()
        major = str(db.get("engine_version") or "").split(".")[0]
        if engine.startswith("postgres"):
            package = f"postgresql-{major}" if major.isdigit() else "postgresql"
            config["apt"] = {"sources": {"pgdg": {
                "source": "deb http://apt.postgresql.org/pub/repos/apt $RELEASE-pgdg main", "keyid": PGDG_KEY,
            }}}
            config["packages"] = [package]
            config["runcmd"] += [
                # listen on the private network too, the leaseweb security group decides who gets in
                ["sh", "-c", "sed -i \"s/^#*listen_addresses.*/listen_addresses = '*'/\" /etc/postgresql/*/main/postgresql.conf"],
                ["sh", "-c", "echo 'host all all samenet scram-sha-256' >> /etc/postgresql/*/main/pg_hba.conf"],
                ["systemctl", "restart", "postgresql"],
            ]
        elif engine in {"mysql", "mariadb"}:
            config["packages"] = ["mariadb-server" if engine == "mariadb" else "mysql-server"]
            config["runcmd"] += [
                ["sh", "-c", "sed -i 's/^bind-address.*/bind-address = 0.0.0.0/' /etc/mysql/*.conf.d/*.cnf"],
                ["systemctl", "restart", "mariadb" if engine == "mariadb" else "mysql"],
            ]
    return "#cloud-config\n" + yaml.safe_dump(config, sort_keys=False)


def literal(value: object) -> str:
    return (
        json.dumps(value, ensure_ascii=False).replace("${", "$${").replace("%{", "%%{")
    )


LABEL = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def resource_labels(resources: dict, entries: dict) -> dict[str, str]:
    """Terraform labels from the translator's tf_name, so no aws id or account number ends up in main.tf."""
    labels: dict[str, str] = {}
    used: set[str] = set()
    for key in resources:
        name = entries.get(key, {}).get("tf_name") or ""
        if not LABEL.match(name) or name in used:
            # fallback is a hash only, never the raw id (arns carry the account id)
            name = "r_" + hashlib.sha256(key.encode()).hexdigest()[:12]
        used.add(name)
        labels[key] = name
    return labels


def rendered(entry: dict, target: dict) -> bool:
    # manual entries stay out of terraform, except a self-hosted db: its vm is terraform, its data is the runbook
    if entry["status"] in {"auto", "partial"}:
        return True
    return target.get("kind") == "self_hosted_db" and bool(target.get("instance_type")) and entry["status"] == "manual"


def generate(out: Path, inventory: dict, graph: dict, mapping: dict) -> dict:
    resources, entries = indexed(inventory, mapping)
    labels = resource_labels(resources, entries)
    targets = {key: entry.get("target") or {} for key, entry in entries.items()}
    related = defaultdict(set)
    for edge in graph["edges"]:
        if not edge.get("inferred"):
            related[edge["from"]].add(edge["to"])
    members = defaultdict(list)
    for key, links in related.items():
        if targets.get(key, {}).get("kind") in VMS and rendered(entries[key], targets[key]):
            for link in sorted(links):
                members[link].append(key)
    mapped_instances = {
        entry["tf_name"]: labels[key] for key, entry in entries.items()
        if entry.get("tf_name") and targets[key].get("kind") in VMS and rendered(entry, targets[key])
    }
    plan = dict(api=API, security_groups=[], target_registrations=[], manual=[])
    items = []
    for key, entry in entries.items():
        t = targets[key]
        kind = t.get("kind")
        props = resources[key].get("properties", {})
        links = sorted(related[key])
        if not rendered(entry, t):
            continue
        if kind == "security_group":
            rules = []
            attachments = [labels[i] for i in sorted(members[key])]
            if "rules" in t:
                attachments = []
                for name in t["attach_to"]:
                    if name in mapped_instances:
                        attachments.append(mapped_instances[name])
                    else:
                        plan["manual"].append(dict(source_id=key, what=f"Attach this group to {name} after manual provisioning"))
                for rule in t["rules"]:
                    source = rule["source"]
                    if "private_ip_of" in source:
                        name = source["private_ip_of"]
                        if name not in mapped_instances:
                            plan["manual"].append(dict(source_id=key, what=f"Resolve private address of {name} after manual provisioning"))
                            continue
                        source = {"private_ip_of": mapped_instances[name]}
                    translated = {**rule, "source": source}
                    if translated not in rules:
                        rules.append(translated)
            for rule in ([] if "rules" in t else props.get("ingress", [])):
                protocol = str(rule.get("protocol")).upper()
                start, end = rule.get("from_port"), rule.get("to_port")
                if (
                    protocol not in {"TCP", "UDP"}
                    or not isinstance(start, int)
                    or not isinstance(end, int)
                ):
                    plan["manual"].append(
                        dict(source_id=key, what="Review unsupported ingress rule")
                    )
                    continue
                sources = []
                for cidr in rule.get("cidrs", []):
                    network = ip_network(cidr)
                    if network.prefixlen == 0 and any(
                        start <= p <= end
                        for p in (22, 3389, 3306, 5432, 1433, 27017, 6379, 9200)
                    ):
                        if start == end and start in (22, 3389):
                            sources.append({"cidr": "var:admin_cidr"})
                        else:
                            plan["manual"].append(
                                dict(
                                    source_id=key,
                                    what=f"Supply restricted sources for {protocol} {start}-{end}",
                                )
                            )
                    else:
                        sources.append({"cidr": str(network)})
                for group in rule.get("source_groups", []):
                    if not members[group]:
                        plan["manual"].append(
                            dict(
                                source_id=key,
                                what=f"Resolve missing source group {group}",
                            )
                        )
                    sources.extend({"private_ip_of": labels[i]} for i in members[group])
                rules.extend(
                    dict(protocol=protocol, start_port=start, end_port=end, source=s)
                    for s in sources
                )
            plan["manual"].append(
                dict(
                    source_id=key,
                    what="Check effective ingress after attachment, including the default allow-all group",
                )
            )
            if props.get("egress"):
                plan["manual"].append(
                    dict(
                        source_id=key,
                        what="Verify outbound policy and effective default group after attachment",
                    )
                )
            plan["security_groups"].append(
                dict(
                    source_id=key,
                    name=labels[key],
                    rules=rules,
                    attach_to=attachments,
                )
            )
            continue
        if kind not in KINDS:
            if entry["via"] == "terraform":
                plan["manual"].append(
                    dict(
                        source_id=key,
                        what="Review resource without standalone Terraform representation",
                    )
                )
            continue
        region = t.get("region", mapping["target_region"])
        contract = {"type": "HOURLY", "term": 0, "billing_frequency": 1}
        refs = {}
        if kind in VMS:
            key_name = props.get("key_name")
            if key_name:
                links = sorted(
                    set(links)
                    | {
                        i
                        for i, r in resources.items()
                        if r["type"] == "key_pair"
                        and r.get("name") == key_name
                        and r.get("region") == resources[key].get("region")
                    }
                )
            keys = [
                resources[i]["properties"]["public_key"]
                for i in links
                if i in resources
                and resources[i].get("properties", {}).get("public_key")
            ]
            attrs = dict(
                region=region,
                type=t["instance_type"],
                image={"id": t["image_id"]},
                root_disk_size=t["root_disk_size"],
                root_disk_storage_type=t.get("root_disk_storage_type", "CENTRAL"),
                has_private_network=True,
                contract=contract,
                reference=resources[key].get("name", key),
                user_data=cloud_init(keys, t if kind == "self_hosted_db" else None),
            )
            if props.get("key_name") and not keys:
                plan["manual"].append(
                    dict(
                        source_id=key,
                        what="Supply the missing SSH public key before apply",
                    )
                )
        elif kind == "load_balancer":
            attrs = dict(
                region=region,
                type=t["instance_type"] if "instance_type" in t else t["type"],
                contract=contract,
            )
        elif kind == "target_group":
            attrs = dict(
                region=region,
                name=t.get("name", resources[key].get("name", key)),
                port=t["port"],
                protocol=t["protocol"],
            )
            if t.get("health_check"):
                attrs["health_check"] = {
                    k: v
                    for k, v in t["health_check"].items()
                    if k in {"port", "protocol", "uri", "method", "host"}
                }
            instances = [
                labels[i]
                for i in links
                if targets.get(i, {}).get("kind") == "public_cloud_instance"
                and entries[i]["status"] in {"auto", "partial"}
            ]
            if instances:
                plan["target_registrations"].append(
                    dict(target_group=labels[key], instances=instances)
                )
        elif kind == "lb_listener":
            attrs = dict(protocol=t["protocol"], port=t["port"])
            if attrs["protocol"].upper() == "HTTPS":
                plan["manual"].append(
                    dict(
                        source_id=key,
                        what="Configure HTTPS listener with customer certificate",
                    )
                )
                continue
            for field, role in (
                ("load_balancer_id", "load_balancer"),
                ("default_rule", "target_group"),
            ):
                candidates = [
                    i
                    for i in links
                    if targets.get(i, {}).get("kind") == role
                    and entries[i]["status"] in {"auto", "partial"}
                ]
                if len(candidates) != 1:
                    raise ValueError(f"{key} needs one {role} relation")
                ref = f"leaseweb_{KINDS[role]}.{labels[candidates[0]]}.id"
                refs[field] = (
                    ref
                    if field == "load_balancer_id"
                    else "{ target_group_id = " + ref + " }"
                )
        else:
            attrs = {
                field: t[field] for field in ("domain_name", "name", "ttl", "type")
            }
            if t.get("content"):
                attrs["content"] = t["content"]
            else:
                destinations = [
                    i
                    for i in links
                    if targets.get(i, {}).get("kind")
                    in {"load_balancer", "public_cloud_instance"}
                    and entries[i]["status"] in {"auto", "partial"}
                ]
                if len(destinations) != 1 or attrs["type"] != "A":
                    plan["manual"].append(
                        dict(
                            source_id=key, what="Resolve DNS destination before cutover"
                        )
                    )
                    continue
                dest = destinations[0]
                ref = f"leaseweb_{KINDS[targets[dest]['kind']]}.{labels[dest]}"
                refs["content"] = (
                    f'[one([for ip in {ref}.ips : ip.ip if can(cidrnetmask(format("%s/32", ip.ip))) '
                    '&& !can(regex("^(10[.]|192[.]168[.]|172[.](1[6-9]|2[0-9]|3[01])[.])", ip.ip))])]'
                )
        items.append(
            dict(
                provider_type="leaseweb_" + KINDS[kind],
                label=labels[key],
                attributes={**{k: literal(v) for k, v in attrs.items()}, **refs},
                export=kind in VMS | {"target_group"},
            )
        )
    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent), undefined=StrictUndefined
    )
    write(
        out / "terraform/main.tf",
        env.get_template("main.tf.j2").render(resources=items),
    )
    save(out, "finalize", plan)
    return plan
