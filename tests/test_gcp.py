import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from sovereign_shift.cli import app
from sovereign_shift.scanner import gcp
from sovereign_shift.translator.rules import gcp_family
from sovereign_shift.translator.translate import region_mapper, translate

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "testdata/gcp_api_responses.json").read_text())
GOLDEN = ROOT / "testdata/gcp_inventory.json"


def fake_api(calls: list[str]):
    # serves the recorded responses, a "__status" key turns one into an error
    def handler(request: httpx.Request) -> httpx.Response:
        key = ("POST " if request.method == "POST" else "") + str(request.url)
        calls.append(request.method + " " + str(request.url))
        body = FIXTURE["responses"].get(key)
        if body is None:
            return httpx.Response(404, json={"error": {"code": 404}})
        return httpx.Response(body.get("__status", 200), json={k: v for k, v in body.items() if k != "__status"})
    return handler


def scan_fixture(calls: list[str] | None = None) -> dict:
    calls = [] if calls is None else calls
    with httpx.Client(transport=httpx.MockTransport(fake_api(calls))) as client:
        raw = gcp.collect(FIXTURE["project"], client)
    inventory = gcp.build_inventory(raw)
    inventory["scanned_at"] = "2026-11-20T12:00:00Z"
    return inventory


def test_scan_matches_golden_inventory_and_keeps_secrets_out():
    calls: list[str] = []
    inventory = scan_fixture(calls)
    assert inventory == json.loads(GOLDEN.read_text())
    text = json.dumps(inventory)
    # startup script, cloud run env vars and txt values never reach the inventory
    for secret in ("do-not-store", "DB_PASSWORD", "secretish"):
        assert secret not in text
    # ids and names don't carry the project, only account_id does
    assert text.count(FIXTURE["project"]) == 1
    # read-only: gets, plus the one list call google only offers as a post
    assert all(c.startswith("GET ") or (c.startswith("POST ") and c.endswith("/listInstances")) for c in calls)


def test_disabled_api_is_recorded_not_fatal():
    inventory = scan_fixture()
    assert inventory["denied"] == [{"service": "cloudfunctions", "region": "global",
                                    "operation": "locations/-/functions", "error": "ServiceDisabled"}]


def test_reader_refuses_writes():
    reader = gcp.Reader(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))), "demo-shop-4821")
    with pytest.raises(gcp.ScanError):
        reader.call("https://compute.googleapis.com/compute/v1/projects/demo-shop-4821/zones/z/instances/vm/stop", "compute", "POST")


def test_firewalls_become_groups_per_target():
    by_name = {r["name"]: r for r in scan_fixture()["resources"]}
    web = by_name["web-1"]
    groups = {rel["target"] for rel in web["relations"] if rel["type"] == "uses_security_group"}
    assert groups == {"gcp:global/networks/default/firewall/all/all", "gcp:global/networks/default/firewall/tag/http-server"}
    worker_rules = by_name["default-worker"]["properties"]["ingress"]
    # sourceTags resolve to the tagged instances
    assert worker_rules[0]["source_instances"] == ["gcp:zones/europe-west4-a/instances/web-1", "gcp:zones/europe-west4-a/instances/web-2"]
    assert by_name["default-all"]["properties"]["deny_rules"] == ["deny-telnet"]
    assert "old-rule" not in json.dumps(by_name["default-all"])


def test_pipeline_writes_valid_plan(tmp_path):
    result = CliRunner().invoke(app, ["all", "--from-snapshot", str(GOLDEN), "--no-ai", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    terraform = (tmp_path / "terraform/main.tf").read_text()
    assert terraform.count('resource "leaseweb_public_cloud_instance"') == 3
    assert 'resource "leaseweb_public_cloud_load_balancer"' in terraform
    assert 'region = "eu-west-3"' in terraform  # europe-west4, not the leaseweb code with the same look

    plan = json.loads((tmp_path / "finalize.json").read_text())
    rules = {g["name"]: g["rules"] for g in plan["security_groups"]}
    # ssh from the world became the admin cidr, the db only takes the app instances
    assert {"protocol": "TCP", "source": {"cidr": "var:admin_cidr"}, "start_port": 22, "end_port": 22} in rules["default_all"]
    assert all("private_ip_of" in r["source"] for r in rules["shop_db_access"])
    # google health checkers become the private network the leaseweb lb uses
    assert {"protocol": "TCP", "source": {"cidr": "var:private_network_cidr"}, "start_port": 80, "end_port": 80} in rules["default_http_server"]
    assert plan["target_registrations"] == [{"target_group": "web_backend", "instances": ["web_1", "web_2"]}]

    runbook = json.loads((tmp_path / "runbook.json").read_text())
    commands = [s["command"] for e in runbook["entries"] for s in e["steps"]]
    assert 'rclone copy "gcs:shop-assets-4821" "leaseweb:<CUSTOMER: target bucket>"' in commands

    report = (tmp_path / "report.md").read_text()
    assert "| Resource | Google Cloud type | Google Cloud |" in report
    assert "demo-shop-4821" not in (tmp_path / "public/report.md").read_text()


def test_sizing_and_regions():
    assert gcp.machine_spec("db-custom-2-7680") == (2, 7.5)
    assert gcp.machine_spec("db-n1-standard-2") == (2, 7.5)
    assert gcp_family("n2-highmem-4", 4, 32)[0] == "r"
    assert gcp_family("c3-standard-8", 8, 32)[0] == "c"
    family, notes, partial = gcp_family("t2a-standard-2", 2, 8)
    assert partial and "arm" in notes[0]
    assert gcp_family("m5.large", 2, 8) is None
    region_for = region_mapper(None, "gcp")
    assert region_for("europe-west3") == "eu-central-1"
    assert region_for("europe-west4") == "eu-west-3"


def test_translate_handles_other_services():
    inventory = json.loads(GOLDEN.read_text())
    entries = {e.source_name: e for e in translate(inventory).entries}
    assert entries["analytics"].target["kind"] == "managed_kubernetes"
    assert entries["orders"].status == "unsupported"
    assert "pubsub.googleapis.com/Topic" in entries["orders"].justification


def test_project_flag_only_for_gcp(tmp_path):
    result = CliRunner().invoke(app, ["scan", "--project", "demo-shop-4821", "--out", str(tmp_path)])
    assert result.exit_code != 0
