"""Evaluate checks only when the inventory contains the required evidence."""

from .build import _allows_port, _rules


def findings(inventory: dict, graph: dict) -> list[dict]:
    result = []
    checks = {
        "s3_bucket": [
            ("public", True, "S3-001", "critical", "Review public bucket access"),
            (
                "public_access_block",
                False,
                "S3-002",
                "high",
                "Enable public access blocking",
            ),
            ("encrypted", False, "S3-003", "medium", "Enable default encryption"),
            ("versioning", False, "S3-004", "low", "Enable object versioning"),
        ],
        "db_instance": [
            (
                "publicly_accessible",
                True,
                "RDS-001",
                "critical",
                "Restrict database ingress",
            ),
            ("storage_encrypted", False, "RDS-002", "high", "Encrypt database storage"),
            ("backup_retention_period", 0, "RDS-003", "medium", "Configure backups"),
        ],
        "ec2_instance": [
            ("http_tokens", "optional", "EC2-001", "high", "Require IMDSv2")
        ],
        "ebs_volume": [
            ("encrypted", False, "EC2-002", "medium", "Encrypt volume data")
        ],
    }
    groups = {r["id"] for r in inventory["resources"] if r["type"] == "target_group"}
    backends = {e["to"] for e in graph["edges"] if e["from"] in groups}
    vpcs = [r for r in inventory["resources"] if r["type"] == "vpc"]
    for resource in inventory["resources"]:
        kind = resource["type"]
        props = resource.get("properties", {})

        def add(code: str, severity: str, title: str, evidence: str) -> None:
            result.append(
                dict(
                    id=code,
                    severity=severity,
                    resource=resource["id"],
                    title=title,
                    evidence=evidence,
                    fixed_by_migration=False,
                    fix=title,
                )
            )

        for key, value, code, severity, title in checks.get(kind, []):
            if props.get(key) == value and not (
                code == "S3-001" and props.get("static_website")
            ):
                add(code, severity, title, f"{key} = {value}")
        if kind == "security_group":
            for rule in _rules(resource):
                cidrs = [
                    *rule.get("cidrs", []),
                    *(r["CidrIp"] for r in rule.get("IpRanges", [])),
                    *(r["CidrIpv6"] for r in rule.get("Ipv6Ranges", [])),
                ]
                internet = set(cidrs) & {"0.0.0.0/0", "::/0"}
                if not internet:
                    continue
                for ports, code, severity in [
                    ((22, 3389), "SG-001", "critical"),
                    ((3306, 5432, 1433, 27017, 6379, 9200), "SG-002", "high"),
                ]:
                    for port in ports:
                        if _allows_port(rule, port):
                            add(
                                code,
                                severity,
                                f"Restrict public TCP/{port}",
                                ", ".join(sorted(internet)),
                            )
                if str(rule.get("protocol", rule.get("IpProtocol"))) == "-1":
                    add(
                        "SG-003",
                        "medium",
                        "Restrict all-protocol ingress",
                        ", ".join(sorted(internet)),
                    )
            if props.get("attached_eni_count") == 0:
                add("SG-004", "low", "Review unused group", "No attached ENIs")
        if (
            kind == "lb_listener"
            and props.get("protocol") == "HTTP"
            and props.get("default_action") == "forward"
        ):
            add(
                "ELB-001",
                "medium",
                "Redirect HTTP to HTTPS",
                "HTTP forwarding listener",
            )
        if (
            kind == "ec2_instance"
            and props.get("public_ip")
            and resource["id"] in backends
        ):
            add(
                "EC2-003",
                "medium",
                "Restrict backend ingress",
                "Public load balancer backend",
            )
        if kind == "vpc" and props.get("is_default") and len(vpcs) == 1:
            add(
                "NET-001",
                "info",
                "Review default VPC use",
                "Only scanned VPC is default",
            )
        if kind == "iam_account" and (
            props.get("root_access_keys") or props.get("root_mfa") is False
        ):
            add(
                "IAM-001",
                "critical",
                "Secure root credentials",
                "Active root key or missing MFA",
            )
        if kind == "iam_access_key" and (
            props.get("age_days", 0) > 90 or props.get("unused")
        ):
            add("IAM-002", "high", "Review stale access key", "Old or unused key")
    return sorted(result, key=lambda f: (f["resource"], f["id"], f["title"]))
