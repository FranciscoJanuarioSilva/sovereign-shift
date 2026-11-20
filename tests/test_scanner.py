from typing import Any

import pytest
from botocore.exceptions import ClientError

from sovereign_shift.scanner import aws


def denied(operation: str, code: str = "UnauthorizedOperation") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "scp says no"}}, operation)


class FakeClient:
    # answers every describe/list call with an empty page, unless told otherwise
    def __init__(self, answers: dict[str, Any] | None = None, deny: bool = False) -> None:
        self.answers = answers or {}
        self.deny = deny

    def can_paginate(self, operation: str) -> bool:
        return False

    def __getattr__(self, operation: str):
        def call(**kwargs: Any) -> dict:
            if self.deny:
                raise denied(operation)
            return self.answers.get(operation, {})
        return call


class FakeSession:
    region_name = "eu-north-1"

    def __init__(self, denied_regions: set[str]) -> None:
        self.denied_regions = denied_regions

    def client(self, service: str, region_name: str | None = None) -> FakeClient:
        if service == "sts":
            return FakeClient({"get_caller_identity": {"Account": "123456789012"}})
        if service == "s3":
            return FakeClient({"list_buckets": {"Buckets": []}}, deny=region_name in self.denied_regions)
        if service == "route53":
            return FakeClient({"list_hosted_zones": {"HostedZones": []}}, deny=region_name in self.denied_regions)
        return FakeClient(deny=region_name in self.denied_regions)


def test_service_managed_elastic_ips_are_skipped() -> None:
    ec2 = FakeClient({"describe_addresses": {"Addresses": [
        {"AllocationId": "eipalloc-customer", "PublicIp": "198.51.100.1", "Domain": "vpc", "InstanceId": "i-1"},
        {"AllocationId": "eipalloc-alb", "PublicIp": "198.51.100.2", "Domain": "vpc", "ServiceManaged": "alb"},
        {"AllocationId": "eipalloc-rds", "PublicIp": "198.51.100.3", "Domain": "vpc", "ServiceManaged": "rds"},
    ]}})
    found = [item for item in aws.scan_ec2(ec2, "eu-north-1") if item["type"] == "elastic_ip"]
    assert [item["id"] for item in found] == ["eipalloc-customer"]


def test_denied_region_is_recorded_and_the_scan_goes_on() -> None:
    inventory = aws.scan(FakeSession({"eu-west-1"}), ["eu-west-1", "eu-north-1"])
    assert inventory["regions"] == ["eu-north-1", "eu-west-1"]
    assert {(entry["region"], entry["service"]) for entry in inventory["denied"]} == {
        ("eu-west-1", "ec2"), ("eu-west-1", "elbv2"), ("eu-west-1", "rds"),
    }
    # s3 and route53 went through the region that answered, so they aren't denied
    assert not [entry for entry in inventory["denied"] if entry["region"] == "global"]


def test_other_errors_still_fail_loudly() -> None:
    def broken():
        raise ClientError({"Error": {"Code": "Throttling", "Message": "slow down"}}, "DescribeVpcs")
        yield

    with pytest.raises(ClientError):
        aws.guarded(broken(), "eu-north-1", "ec2", [])
