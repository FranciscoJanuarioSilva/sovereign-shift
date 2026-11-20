"""Build the migration inventory from read-only AWS APIs."""

from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

from boto3 import Session
from botocore.exceptions import ClientError

Item = dict[str, Any]


def items(client: Any, operation: str, key: str, **kwargs: Any) -> Iterator[Item]:
    if client.can_paginate(operation):
        pages = client.get_paginator(operation).paginate(**kwargs)
    else:
        pages = [getattr(client, operation)(**kwargs)]
    for page in pages:
        yield from page.get(key, [])


def fields(item: Item, **names: str) -> Item:
    return {name: item[key] for name, key in names.items() if key in item}


def links(kind: str, *targets: str | None) -> list[Item]:
    return [{"type": kind, "target": target} for target in sorted(set(filter(None, targets)))]


def resource(
    kind: str, ident: str, region: str, properties: Item,
    *, name: str | None = None, tags: list[Item] | None = None,
    relations: list[Item] | None = None,
) -> Item:
    tag_map = {tag["Key"]: tag["Value"] for tag in tags or []}
    tagged_name = tag_map.pop("Name", None)
    return {
        "id": ident, "type": kind, "region": region,
        "name": tagged_name or name or ident,
        "properties": properties, "tags": tag_map,
        "relations": relations or [],
    }


def optional(call: Any, missing: tuple[str, ...], **kwargs: Any) -> Item:
    try:
        return call(**kwargs)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in missing:
            return {}
        raise


def security_rules(rules: list[Item]) -> list[Item]:
    return [
        {
            "protocol": rule["IpProtocol"],
            "from_port": rule.get("FromPort"),
            "to_port": rule.get("ToPort"),
            "cidrs": [
                *[entry["CidrIp"] for entry in rule.get("IpRanges", [])],
                *[entry["CidrIpv6"] for entry in rule.get("Ipv6Ranges", [])],
            ],
            "source_groups": [
                entry["GroupId"] for entry in rule.get("UserIdGroupPairs", []) if "GroupId" in entry
            ],
            "prefix_list_ids": [entry["PrefixListId"] for entry in rule.get("PrefixListIds", [])],
        }
        for rule in rules
    ]


def scan_ec2(ec2: Any, region: str) -> Iterator[Item]:
    network = [
        ("vpc", "describe_vpcs", "Vpcs", "VpcId"),
        ("subnet", "describe_subnets", "Subnets", "SubnetId"),
        ("security_group", "describe_security_groups", "SecurityGroups", "GroupId"),
    ]
    for kind, operation, key, id_key in network:
        for item in items(ec2, operation, key):
            properties = fields(
                item, cidr="CidrBlock", default="IsDefault",
                availability_zone="AvailabilityZone", map_public_ip="MapPublicIpOnLaunch",
            )
            relations = []
            if kind != "vpc":
                relations += links("in_vpc", item.get("VpcId"))
            if kind == "security_group":
                for direction, key_name in [("ingress", "IpPermissions"), ("egress", "IpPermissionsEgress")]:
                    rules = security_rules(item.get(key_name, []))
                    properties[direction] = rules
                    relations += links(
                        f"{direction}_security_group",
                        *(group for rule in rules for group in rule["source_groups"]),
                    )
            yield resource(
                kind, item[id_key], region, properties, name=item.get("GroupName"),
                tags=item.get("Tags"), relations=relations,
            )

    keys = {}
    for key_pair in items(ec2, "describe_key_pairs", "KeyPairs", IncludePublicKey=True):
        keys[key_pair["KeyName"]] = key_pair["KeyPairId"]
        yield resource(
            "key_pair", key_pair["KeyPairId"], region,
            fields(key_pair, fingerprint="KeyFingerprint", public_key="PublicKey"),
            name=key_pair["KeyName"], tags=key_pair.get("Tags"),
        )

    volumes = {}
    for volume in items(ec2, "describe_volumes", "Volumes"):
        ident = volume["VolumeId"]
        volumes[ident] = fields(
            volume, size_gib="Size", encrypted="Encrypted", volume_type="VolumeType",
            availability_zone="AvailabilityZone", iops="Iops", throughput="Throughput",
        )
        yield resource("ebs_volume", ident, region, volumes[ident], tags=volume.get("Tags"))

    addresses: dict[str, list[str]] = {}
    for address in items(ec2, "describe_addresses", "Addresses"):
        # aws creates these for albs and public rds instances, they aren't the customer's eips
        if address.get("ServiceManaged"):
            continue
        ident = address.get("AllocationId") or address["PublicIp"]
        if address.get("InstanceId"):
            addresses.setdefault(address["InstanceId"], []).append(ident)
        yield resource(
            "elastic_ip", ident, region,
            fields(address, public_ip="PublicIp", private_ip="PrivateIp", domain="Domain"),
            tags=address.get("Tags"), relations=links("attached_to", address.get("InstanceId")),
        )

    specs: dict[str, Item] = {}
    images: dict[str, str] = {}
    for reservation in items(ec2, "describe_instances", "Reservations"):
        for instance in reservation["Instances"]:
            if instance["State"]["Name"] == "terminated":
                continue
            ident = instance["InstanceId"]
            properties = fields(
                instance, instance_type="InstanceType", image_id="ImageId", key_name="KeyName",
                public_ip_address="PublicIpAddress", private_ip="PrivateIpAddress",
                root_device_name="RootDeviceName", architecture="Architecture",
            )
            instance_type = instance["InstanceType"]
            if instance_type not in specs:
                spec = ec2.describe_instance_types(InstanceTypes=[instance_type])["InstanceTypes"][0]
                specs[instance_type] = {
                    "vcpu": spec["VCpuInfo"]["DefaultVCpus"],
                    "memory_gib": spec["MemoryInfo"]["SizeInMiB"] / 1024,
                }
            properties.update(specs[instance_type])
            cpu = instance.get("CpuOptions", {})
            if cpu.get("CoreCount") and cpu.get("ThreadsPerCore"):
                properties["vcpu"] = cpu["CoreCount"] * cpu["ThreadsPerCore"]

            image_id = instance["ImageId"]
            if image_id not in images:
                result = optional(
                    ec2.describe_images, ("InvalidAMIID.NotFound", "InvalidAMIID.Unavailable"),
                    ImageIds=[image_id],
                ).get("Images", [])
                image = result[0] if result else {}
                images[image_id] = image.get("Name") or image.get("PlatformDetails") or "unknown"
            properties["os"] = instance.get("Platform") or images[image_id]
            properties["state"] = instance["State"]["Name"]
            properties["public_ip"] = bool(instance.get("PublicIpAddress"))
            properties.update(fields(instance.get("MetadataOptions", {}), http_tokens="HttpTokens"))
            properties["volumes"] = [
                {"id": block["Ebs"]["VolumeId"], "device_name": block["DeviceName"],
                 "root": block["DeviceName"] == instance.get("RootDeviceName"),
                 **volumes.get(block["Ebs"]["VolumeId"], {})}
                for block in instance.get("BlockDeviceMappings", [])
                if block.get("Ebs", {}).get("VolumeId")
            ]
            yield resource(
                "ec2_instance", ident, region, properties, tags=instance.get("Tags"),
                relations=(
                    links("in_vpc", instance.get("VpcId"))
                    + links("in_subnet", instance.get("SubnetId"))
                    + links("uses_security_group", *(sg["GroupId"] for sg in instance.get("SecurityGroups", [])))
                    + links("uses_volume", *(volume["id"] for volume in properties["volumes"]))
                    + links("uses_key_pair", keys.get(instance.get("KeyName")))
                    + links("uses_elastic_ip", *addresses.get(ident, []))
                ),
            )


def forward_targets(actions: list[Item]) -> list[str]:
    return [
        *[a["TargetGroupArn"] for a in actions if "TargetGroupArn" in a],
        *[g["TargetGroupArn"] for a in actions for g in a.get("ForwardConfig", {}).get("TargetGroups", [])],
    ]


def scan_elb(elb: Any, region: str) -> Iterator[Item]:
    for lb in items(elb, "describe_load_balancers", "LoadBalancers"):
        arn = lb["LoadBalancerArn"]
        yield resource(
            "lb", arn, region, fields(lb, lb_type="Type", dns_name="DNSName", scheme="Scheme",
                                     ip_address_type="IpAddressType"),
            name=lb["LoadBalancerName"],
            relations=(
                links("in_vpc", lb.get("VpcId"))
                + links("in_subnet", *(az.get("SubnetId") for az in lb.get("AvailabilityZones", [])))
                + links("uses_security_group", *lb.get("SecurityGroups", []))
            ),
        )
        for listener in items(elb, "describe_listeners", "Listeners", LoadBalancerArn=arn):
            listener_arn = listener["ListenerArn"]
            actions = listener.get("DefaultActions", [])
            targets = forward_targets(actions)
            if lb["Type"] == "application":
                for rule in items(elb, "describe_rules", "Rules", ListenerArn=listener_arn):
                    targets.extend(forward_targets(rule.get("Actions", [])))
            yield resource(
                "lb_listener", listener_arn, region,
                {
                    **fields(listener, port="Port", protocol="Protocol", ssl_policy="SslPolicy"),
                    "default_actions": [action["Type"] for action in actions],
                    "redirects_to_https": any(
                        action.get("RedirectConfig", {}).get("Protocol") == "HTTPS" for action in actions
                    ),
                    "certificate_arns": [cert["CertificateArn"] for cert in listener.get("Certificates", [])],
                },
                relations=links("listens_on", arn) + links("forwards_to", *targets),
            )

    for group in items(elb, "describe_target_groups", "TargetGroups"):
        arn = group["TargetGroupArn"]
        targets = [
            fields(entry["Target"], id="Id", port="Port", availability_zone="AvailabilityZone")
            for entry in items(elb, "describe_target_health", "TargetHealthDescriptions", TargetGroupArn=arn)
        ]
        yield resource(
            "target_group", arn, region,
            {
                **fields(group, port="Port", protocol="Protocol", target_type="TargetType",
                         health_check_path="HealthCheckPath", health_check_protocol="HealthCheckProtocol",
                         health_check_port="HealthCheckPort"),
                "targets": targets,
            },
            name=group["TargetGroupName"],
            relations=(
                links("in_vpc", group.get("VpcId"))
                + links("associated_with", *group.get("LoadBalancerArns", []))
                + links("targets", *(target["id"] for target in targets))
            ),
        )


def scan_rds(rds: Any, region: str) -> Iterator[Item]:
    for db in items(rds, "describe_db_instances", "DBInstances"):
        subnet_group = db.get("DBSubnetGroup", {})
        yield resource(
            "db_instance", db.get("DBInstanceArn") or db["DBInstanceIdentifier"], region,
            {
                **fields(db, engine="Engine", engine_version="EngineVersion", instance_class="DBInstanceClass",
                         db_name="DBName", storage_gib="AllocatedStorage", storage_encrypted="StorageEncrypted",
                         publicly_accessible="PubliclyAccessible", backup_retention_days="BackupRetentionPeriod",
                         multi_az="MultiAZ"),
                **fields(db.get("Endpoint", {}), endpoint="Address", port="Port"),
            },
            name=db["DBInstanceIdentifier"], tags=db.get("TagList"),
            relations=(
                links("in_vpc", subnet_group.get("VpcId"))
                + links("in_subnet", *(s["SubnetIdentifier"] for s in subnet_group.get("Subnets", [])))
                + links("uses_security_group", *(sg["VpcSecurityGroupId"] for sg in db.get("VpcSecurityGroups", [])))
            ),
        )


def scan_s3(session: Session, region: str, regions: list[str]) -> Iterator[Item]:
    s3 = session.client("s3", region_name=region)
    clients = {region: s3}
    for bucket in items(s3, "list_buckets", "Buckets"):
        name = bucket["Name"]
        location = bucket.get("BucketRegion")
        if not location:
            constraint = s3.get_bucket_location(Bucket=name).get("LocationConstraint")
            location = {"EU": "eu-west-1", None: "us-east-1"}.get(constraint, constraint)
        if location not in regions:
            continue
        if location not in clients:
            clients[location] = session.client("s3", region_name=location)
        client = clients[location]
        policy = optional(client.get_bucket_policy_status, ("NoSuchBucketPolicy",), Bucket=name)
        block = optional(client.get_public_access_block, ("NoSuchPublicAccessBlockConfiguration",), Bucket=name)
        encryption = optional(
            client.get_bucket_encryption, ("ServerSideEncryptionConfigurationNotFoundError",), Bucket=name,
        )
        acl = client.get_bucket_acl(Bucket=name)
        tags = optional(client.get_bucket_tagging, ("NoSuchTagSet",), Bucket=name)
        yield resource(
            "s3_bucket", name, location,
            {
                "policy_public": policy.get("PolicyStatus", {}).get("IsPublic", False),
                "acl_public": any(
                    grant["Grantee"].get("URI") == "http://acs.amazonaws.com/groups/global/AllUsers"
                    for grant in acl.get("Grants", [])
                ),
                "public_access_block": block.get("PublicAccessBlockConfiguration", {}),
                "encryption": [
                    rule["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"]
                    for rule in encryption.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
                ],
                "versioning": client.get_bucket_versioning(Bucket=name).get("Status", "Disabled"),
            },
            tags=tags.get("TagSet"),
        )


def scan_route53(route53: Any, resources: list[Item]) -> Iterator[Item]:
    endpoints: dict[str, list[str]] = {}
    for item in resources:
        key = {"lb": "dns_name", "elastic_ip": "public_ip"}.get(item["type"])
        if key and (value := item["properties"].get(key)):
            endpoints.setdefault(value.rstrip(".").lower(), []).append(item["id"])

    for zone in items(route53, "list_hosted_zones", "HostedZones"):
        zone_id = zone["Id"].rsplit("/", 1)[-1]
        yield resource(
            "route53_zone", zone_id, "global", fields(zone.get("Config", {}), private="PrivateZone"),
            name=zone["Name"],
        )
        for record in items(route53, "list_resource_record_sets", "ResourceRecordSets", HostedZoneId=zone_id):
            ident = f'{zone_id}/{record["Name"]}/{record["Type"]}'
            if "SetIdentifier" in record:
                ident += "/" + record["SetIdentifier"]
            properties = fields(
                record, record_type="Type", ttl="TTL", set_identifier="SetIdentifier",
                weight="Weight", failover="Failover",
            )
            values = [entry["Value"] for entry in record.get("ResourceRecords", [])]
            alias = record.get("AliasTarget", {})
            properties.update(fields(alias, alias_dns_name="DNSName", alias_zone_id="HostedZoneId"))
            # TXT and NAPTR values can carry tokens and arbitrary text.
            if record["Type"] in {"A", "AAAA", "CNAME", "MX", "NS", "PTR", "SRV", "CAA"}:
                properties["values"] = values
            elif values:
                properties["values_omitted"] = True
            targets = []
            for value in [*properties.get("values", []), alias.get("DNSName", "")]:
                key = value.rstrip(".").lower()
                targets.extend(endpoints.get(key, endpoints.get(key.removeprefix("dualstack."), [])))
            yield resource(
                "route53_record", ident, "global", properties, name=record["Name"],
                relations=links("in_zone", zone_id) + links("points_to", *targets),
            )


# what an scp, a region opt-out or a missing permission looks like
DENIED = ("UnauthorizedOperation", "AccessDenied", "AccessDeniedException", "UnrecognizedClientException", "AuthFailure", "OptInRequired")


def guarded(scanner: Iterator[Item], region: str, service: str, denied: list[Item]) -> list[Item]:
    # collect a whole service at once, so a denial halfway through doesn't leave half a region behind
    try:
        return list(scanner)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code not in DENIED:
            raise
        denied.append({"region": region, "service": service, "operation": exc.operation_name, "error": code})
        return []


def scan(session: Session, regions: list[str] | None = None) -> Item:
    home = (regions or [session.region_name or "eu-west-1"])[0]
    account = session.client("sts", region_name=home).get_caller_identity()["Account"]
    if not regions:
        ec2 = session.client("ec2", region_name=home)
        regions = [entry["RegionName"] for entry in ec2.describe_regions(AllRegions=False)["Regions"]]
    regions = sorted(set(regions))
    resources: list[Item] = []
    denied: list[Item] = []
    for region in regions:
        resources.extend(guarded(scan_ec2(session.client("ec2", region_name=region), region), region, "ec2", denied))
        resources.extend(guarded(scan_elb(session.client("elbv2", region_name=region), region), region, "elbv2", denied))
        resources.extend(guarded(scan_rds(session.client("rds", region_name=region), region), region, "rds", denied))
    # global services go through a region that answered, the first one asked for may be the denied one
    blocked = {entry["region"] for entry in denied if entry["service"] == "ec2"}
    home = next((region for region in [home, *regions] if region not in blocked), home)
    resources.extend(guarded(scan_s3(session, home, regions), "global", "s3", denied))
    resources.extend(guarded(scan_route53(session.client("route53", region_name=home), resources), "global", "route53", denied))
    return {
        "source": "aws",
        "account_id": account,
        "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "regions": regions,
        "denied": denied,
        "resources": sorted(resources, key=lambda item: (item["region"], item["type"], item["id"])),
    }
