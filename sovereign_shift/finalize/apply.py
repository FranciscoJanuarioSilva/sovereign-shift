from ipaddress import ip_address, ip_network
from urllib.parse import quote

import httpx

from sovereign_shift.generator.build import API


def finalize(
    plan: dict,
    outputs: dict,
    admin_cidr: str | None,
    token: str | None,
    client: httpx.Client | None = None,
    *, private_network_cidr: str | None = None,
) -> list[dict]:
    if plan["api"] != API:
        raise ValueError("Unexpected Leaseweb API origin")
    calls = []

    def identifier(ref: str) -> str:
        value = str(outputs[ref]["value"])
        if not value or not all(c.isalnum() or c in "_-" for c in value):
            raise ValueError("Invalid Terraform resource ID")
        return value

    def call(method: str, path: str, body: object = None) -> dict:
        calls.append(dict(method=method, path=path, body=body))
        if not token:
            return {}
        request = client.request if client else httpx.request
        response = request(method, API + path, headers={"X-LSW-Auth": token}, json=body)
        response.raise_for_status()
        return response.json() if response.content else {}

    def listing(path: str, field: str) -> list[dict]:
        if not token:
            return []
        rows = []
        while True:
            page = call("GET", path + (f"?offset={len(rows)}" if rows else ""))
            batch = page[field]
            rows.extend(batch)
            total = page.get("_metadata", {}).get("totalCount", len(rows))
            if len(rows) >= total:
                return rows
            if not batch:
                raise ValueError(f"Incomplete Leaseweb listing for {path}")

    prepared = []
    for group in plan["security_groups"]:
        rules = []
        for rule in group["rules"]:
            source = rule["source"]
            if "private_ip_of" in source:
                instance = identifier(source["private_ip_of"])
                ips = call("GET", f"/instances/{instance}/ips")
                cidr = f"<private IPv4 of {instance}>/32"
                if token:
                    addresses = [
                        ip_address(i["ip"])
                        for i in ips["ips"]
                        if i.get("networkType") == "INTERNAL"
                    ]
                    address = next((a for a in addresses if a.version == 4), None)
                    if address is None:
                        raise ValueError(f"No private IPv4 for {instance}")
                    cidr = str(address) + "/32"
            else:
                value = source["cidr"]
                variables = {"var:admin_cidr": admin_cidr, "var:private_network_cidr": private_network_cidr}
                if value in variables and not variables[value]:
                    option = value.removeprefix("var:").replace("_", "-")
                    if token:
                        raise ValueError(f"Supply --{option} for this firewall rule")
                    cidr = f"<{option}>"
                else:
                    network = ip_network(variables.get(value, value))
                    if value in variables and network.prefixlen == 0:
                        raise ValueError("A restricted source cannot be the entire internet")
                    cidr = str(network)
            body = {"protocol": rule["protocol"], "source": cidr}
            if rule["protocol"] != "ICMP":
                body.update(startPort=rule["start_port"], endPort=rule["end_port"])
            if body not in rules:
                rules.append(body)
        prepared.append(
            (group["name"], rules, [identifier(i) for i in group["attach_to"]])
        )
    registrations = [
        (identifier(t["target_group"]), [identifier(i) for i in t["instances"]])
        for t in plan["target_registrations"]
    ]
    for name, rules, instances in prepared:
        matching = [
            g for g in listing("/securityGroups", "securityGroups") if g["name"] == name
        ]
        if len(matching) > 1 or any(g.get("default") for g in matching):
            raise ValueError(f"Ambiguous or default security group {name}")
        group = (
            matching[0] if matching else call("POST", "/securityGroups", {"name": name})
        )
        group_id = quote(str(group["id"]), safe="") if token else f"<created:{name}>"
        current = listing(f"/securityGroups/{group_id}/firewallRules", "firewallRules")
        missing = [
            r
            for r in rules
            if not any(
                all(other.get(k) == v for k, v in r.items()) for other in current
            )
        ]
        if missing:
            call(
                "POST",
                f"/securityGroups/{group_id}/authorizeFirewallRules",
                {"rules": missing},
            )
        for instance in instances:
            attached = listing(
                f"/instances/{instance}/securityGroups", "securityGroups"
            )
            if not any(str(g["id"]) == group_id for g in attached):
                call(
                    "POST",
                    f"/instances/{instance}/attachSecurityGroups",
                    {"securityGroupIds": [group_id]},
                )
    for group_id, ids in registrations:
        registered = {
            str(t["id"])
            for t in listing(f"/targetGroups/{group_id}/targets", "targets")
        }
        missing_ids = [i for i in ids if i not in registered]
        if missing_ids:
            call("POST", f"/targetGroups/{group_id}/registerTargets", missing_ids)
    return calls
