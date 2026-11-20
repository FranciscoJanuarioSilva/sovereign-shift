"""Resolve inventory relations and infer database access from security groups."""

from typing import Any

import networkx as nx


def _rules(resource: dict[str, Any]) -> list[dict[str, Any]]:
    properties = resource.get("properties", {})
    return properties.get("ingress", properties.get("IpPermissions", []))


def _allows_port(rule: dict[str, Any], port: int) -> bool:
    protocol = str(rule.get("protocol", rule.get("IpProtocol", ""))).lower()
    if protocol == "-1":
        return True
    if protocol not in {"tcp", "6"}:
        return False
    start = rule.get("from_port", rule.get("FromPort"))
    end = rule.get("to_port", rule.get("ToPort"))
    return isinstance(start, int) and isinstance(end, int) and start <= port <= end


def _source_groups(rule: dict[str, Any]) -> set[str]:
    groups = rule.get("security_groups", rule.get("UserIdGroupPairs", []))
    return {
        group if isinstance(group, str) else group["GroupId"]
        for group in groups
    }


def build_graph(inventory: dict[str, Any]) -> dict[str, Any]:
    """Build the stable graph contract, preserving unresolved relation targets.

    SG properties accept normalized ingress rules or boto3 IpPermissions.
    Normalized rules use protocol, from_port, to_port and security_groups.
    """
    resources = inventory.get("resources")
    if not isinstance(resources, list):
        raise ValueError("inventory.resources must be a list")
    graph = nx.MultiDiGraph()
    by_id: dict[str, dict[str, Any]] = {}
    for resource in resources:
        resource_id = resource["id"]
        resource_type = resource["type"]
        if not isinstance(resource_id, str) or not resource_id:
            raise ValueError("resource IDs must be nonempty strings")
        if resource_id in by_id:
            raise ValueError(f"duplicate resource ID: {resource_id}")
        by_id[resource_id] = resource
        graph.add_node(
            resource_id, type=resource_type, name=resource.get("name") or resource_id
        )

    findings: list[dict[str, Any]] = []
    for resource_id, resource in by_id.items():
        for relation in resource.get("relations", []):
            target, kind = relation["target"], relation["type"]
            if not isinstance(target, str) or not target or not isinstance(kind, str):
                raise ValueError("relations need a nonempty target and a string type")
            if target not in graph:
                graph.add_node(target, type="unknown", name=target, unresolved=True)
                findings.append({
                    "id": "GRAPH-001", "resource": target, "severity": "warning",
                    "message": "Referenced resource was absent from the inventory.",
                })
            graph.add_edge(resource_id, target, key=kind, type=kind)

    security_groups = {
        resource_id: {
            target for _, target, kind in graph.out_edges(resource_id, keys=True)
            if kind == "uses_security_group"
        }
        for resource_id in by_id
    }
    instances = [
        resource_id for resource_id, resource in by_id.items()
        if resource["type"] == "ec2_instance"
    ]
    for database_id, database in by_id.items():
        if database["type"] != "db_instance":
            continue
        properties = database.get("properties", {})
        engine = str(properties.get("engine", "")).lower()
        endpoint = properties.get("endpoint", {})
        endpoint_port = endpoint.get("Port", endpoint.get("port")) if isinstance(endpoint, dict) else None
        port = properties.get("port", endpoint_port)
        if port is None:
            port = {"postgres": 5432, "aurora-postgresql": 5432,
                    "mysql": 3306, "mariadb": 3306, "aurora": 3306,
                    "aurora-mysql": 3306}.get(engine)
        if not isinstance(port, int):
            continue
        allowed: set[str] = set()
        for group_id in security_groups[database_id]:
            for rule in _rules(by_id.get(group_id, {})):
                if _allows_port(rule, port):
                    allowed.update(_source_groups(rule))
        for instance_id in instances:
            if security_groups[instance_id] & allowed:
                # an explicit relationship takes precedence over an inference
                if not graph.has_edge(instance_id, database_id, "connects_to"):
                    graph.add_edge(
                        instance_id, database_id, key="connects_to",
                        type="connects_to", inferred=True,
                    )

    return {
        "nodes": [
            {"id": node, **attributes}
            for node, attributes in sorted(graph.nodes(data=True))
        ],
        "edges": [
            {"from": source, "to": target, **attributes}
            for source, target, _, attributes in sorted(graph.edges(keys=True, data=True))
        ],
        "findings": sorted(findings, key=lambda item: (item["id"], item["resource"])),
    }
