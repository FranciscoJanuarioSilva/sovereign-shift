"""Azure source: SDK-shaped records -> neutral inventory -> full assessment. No live subscription involved."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sovereign_shift.cli import app
from sovereign_shift.scanner import azure
from sovereign_shift.translator import translate

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = json.loads((ROOT / "testdata" / "azure_sdk_sample.json").read_text())
INVENTORY = ROOT / "testdata" / "azure_inventory.json"


def by_name(inventory):
    return {r["name"]: r for r in inventory["resources"]}


def test_sample_maps_to_the_committed_inventory():
    # the committed fixture is exactly what the mapper produces, so the pipeline tests use real scanner output
    assert azure.build_inventory(SAMPLE) == json.loads(INVENTORY.read_text())


def test_vms_disks_keys_and_network():
    inv = by_name(azure.build_inventory(SAMPLE))
    web1 = inv["web-1"]
    assert web1["type"] == "ec2_instance" and web1["properties"]["cloud_type"] == "Microsoft.Compute/virtualMachines"
    assert web1["properties"]["vcpu"] == 2 and web1["properties"]["memory_gib"] == 8
    assert web1["properties"]["public_ip"] is True and inv["web-2"]["properties"]["public_ip"] is False
    assert web1["properties"]["key_name"] == "web-1-ssh" and inv["web-1-ssh"]["properties"]["public_key"].startswith("ssh-ed25519")
    assert {x["type"] for x in web1["relations"]} >= {"in_subnet", "uses_security_group", "uses_volume", "uses_elastic_ip"}
    assert inv["web-1-ip"]["relations"] == [{"type": "attached_to", "target": web1["id"]}]


def test_nsg_rules():
    rules = azure.nsg_rules([
        {"priority": 100, "direction": "Inbound", "access": "Allow", "protocol": "Tcp", "source_address_prefix": "Internet", "destination_port_range": "3389"},
        {"priority": 110, "direction": "Inbound", "access": "Allow", "protocol": "Tcp", "source_address_prefix": "*", "destination_port_range": "*"},
        {"priority": 120, "direction": "Inbound", "access": "Allow", "protocol": "*", "source_address_prefix": "VirtualNetwork", "destination_port_range": "*"},
        {"priority": 130, "direction": "Inbound", "access": "Allow", "protocol": "Udp", "source_address_prefix": "10.1.0.0/16", "destination_port_ranges": ["53", "1000-2000"]},
        {"priority": 140, "direction": "Outbound", "access": "Allow", "protocol": "Tcp", "source_address_prefix": "*", "destination_port_range": "443"},
    ])
    assert rules[0] == {"protocol": "tcp", "from_port": 3389, "to_port": 3389, "cidrs": ["0.0.0.0/0"], "source_groups": []}
    # "*" on tcp is every tcp port, not every protocol
    assert rules[1]["protocol"] == "tcp" and (rules[1]["from_port"], rules[1]["to_port"]) == (0, 65535)
    # service tags stay internal, outbound rules are ignored
    assert [(r["protocol"], r["from_port"], r["to_port"]) for r in rules[2:]] == [("udp", 53, 53), ("udp", 1000, 2000)]
    # a deny-everything rule with a lower priority number wins over later allows
    denied = azure.nsg_rules([
        {"priority": 100, "direction": "Inbound", "access": "Deny", "protocol": "*", "source_address_prefix": "*", "destination_port_range": "*"},
        {"priority": 200, "direction": "Inbound", "access": "Allow", "protocol": "Tcp", "source_address_prefix": "*", "destination_port_range": "22"},
    ])
    assert denied == []


def test_database_firewall_becomes_a_security_group():
    inv = by_name(azure.build_inventory(SAMPLE))
    db = inv["orders-pg"]
    assert db["type"] == "db_instance" and db["properties"]["publicly_accessible"] is True
    assert db["properties"]["vcpu"] == 2 and db["properties"]["multi_az"] is False
    fw = inv["orders-pg-firewall"]
    assert fw["properties"]["ingress"][0]["cidrs"] == ["0.0.0.0/0"] and fw["properties"]["ingress"][0]["from_port"] == 5432
    assert azure.firewall_cidrs([{"start_ip_address": "10.0.0.0", "end_ip_address": "10.0.0.255"}]) == ["10.0.0.0/24"]


def test_load_balancer_dns_and_unknown_services():
    inv = by_name(azure.build_inventory(SAMPLE))
    pool = inv["shop-lb-web-pool"]
    assert {t["id"].rsplit("/", 1)[-1] for t in pool["properties"]["targets"]} == {"web-1", "web-2"}
    assert pool["properties"]["health_check_path"] == "/health"
    record = inv["www.shop.example.com."]
    assert any(x["target"] == inv["shop-lb"]["id"] for x in record["relations"])
    assert inv["make-thumbnails"]["type"] == "other" and inv["make-thumbnails"]["properties"]["cloud_type"] == "Microsoft.Web/sites"


def test_translation_uses_azure_regions_and_sizes():
    inventory = json.loads(INVENTORY.read_text())
    mapping = translate(inventory)
    assert mapping.source == "azure" and mapping.target_region == "eu-west-3"
    e = {x.source_name: x for x in mapping.entries}
    assert e["web-1"].target["instance_type"] == "lsw.m6a.large"
    # B2s is burstable with 4 GiB, so it goes to the compute family by ram ratio
    assert e["web-2"].target["instance_type"] == "lsw.c6a.large"
    assert "SG-001" in e["web-nsg"].fixes and "RDS-001" in e["orders-pg"].fixes


def test_full_assessment_on_the_azure_sample(tmp_path):
    out = tmp_path / "out"
    run = CliRunner().invoke(app, ["all", "--from-snapshot", str(INVENTORY), "--out", str(out), "--no-ai"])
    assert run.exit_code == 0, run.output
    report = (out / "report.md").read_text()
    assert "| | Today on Azure | After moving to Leaseweb |" in report
    assessment = json.loads((out / "assessment.json").read_text())
    p = assessment["posture"]["overall"]
    assert p["after"] > p["before"]
    assert assessment["risk"]["overall"]["current"] == "critical"
    assert 'resource "leaseweb_public_cloud_instance" "web_1"' in (out / "terraform" / "main.tf").read_text()


def test_live_scan_needs_a_subscription(monkeypatch):
    monkeypatch.delenv("AZURE_SUBSCRIPTION_ID", raising=False)
    with pytest.raises(azure.ScanError):
        azure.scan()
