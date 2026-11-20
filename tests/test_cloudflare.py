import json
from pathlib import Path

import httpx
from typer.testing import CliRunner

from sovereign_shift.cli import app
from sovereign_shift.scanner.cloudflare import scan_account
from sovereign_shift.translator.translate import AIAnswer, translate

DEMO = Path(__file__).resolve().parents[1] / "examples/cloudflare-worker"
ACCOUNT = "a" * 32


def demo_response(request: httpx.Request) -> httpx.Response:
    assert request.method == "GET"
    path = request.url.path.removeprefix(f"/accounts/{ACCOUNT}/")
    settings = {
        "bindings": [
            {"type": "d1", "name": "DB", "database_id": "demo-db"},
            {"type": "r2_bucket", "name": "FILES", "bucket_name": "shift-demo-assets"},
            {"type": "queue", "name": "EVENTS", "queue_name": "shift-demo-events"},
            {"type": "kv_namespace", "name": "SETTINGS", "namespace_id": "demo-kv"},
            {"type": "workflow", "name": "AUDIT", "workflow_name": "shift-demo-audit"},
            {"type": "durable_object_namespace", "name": "DEPOT", "class_name": "Depot"},
            {"type": "assets", "name": "ASSETS"},
        ]
    }
    data = {
        "storage/kv/namespaces": [{"id": "demo-kv", "title": "shift-demo-settings"}],
        "d1/database": [{"uuid": "demo-db", "name": "shift-demo-catalog"}],
        "queues": [{"queue_name": "shift-demo-events", "consumers": [{"script_name": "shift-demo"}]}],
        "workflows": [{"name": "shift-demo-audit", "script_name": "shift-demo"}],
        "workers/durable_objects/namespaces": [{"id": "demo-depot", "name": "Depot", "class": "Depot", "script": "shift-demo"}],
        "r2/buckets": {"buckets": [{"name": "shift-demo-assets"}]},
        "workers/scripts": [{"id": "shift-demo"}],
        "workers/scripts/shift-demo/settings": settings,
        "workers/scripts/shift-demo/schedules": {"schedules": [{"cron": "0 9 * * *"}]},
        "/zones": [{"id": "demo-zone", "name": "example.test"}],
        "/zones/demo-zone/dns_records": [
            {"name": "stock.example.test", "type": "A", "ttl": 300, "content": "192.0.2.23"},
            {"name": "stock.example.test", "type": "A", "ttl": 300, "content": "192.0.2.24"},
            {"name": "edge.example.test", "type": "A", "ttl": 1, "proxied": True, "content": "hidden-origin"},
        ],
    }
    return httpx.Response(200, json={"result": data[path], "success": True})


def test_demo_scan_and_pipeline(tmp_path):
    with httpx.Client(base_url="https://example.test", transport=httpx.MockTransport(demo_response)) as client:
        snapshot = scan_account(ACCOUNT, client)
    expected = json.loads((DEMO / "sample_snapshot.json").read_text())
    assert snapshot["resources"] == expected["resources"]
    assert "hidden-origin" not in json.dumps(snapshot)
    result = CliRunner().invoke(app, ["all", "--from-snapshot", str(DEMO / "sample_snapshot.json"),
                                      "--no-ai", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.exception
    terraform = (tmp_path / "terraform/main.tf").read_text()
    assert 'resource "leaseweb_dns_resource_record_set"' in terraform
    assert "192.0.2.24" in terraform and "edge.example.test" not in terraform
    assert "r2:shift-demo-assets" in (tmp_path / "runbook.json").read_text()
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["source"]["cloud"] == "cloudflare"
    assert report["cost"]["cloudflare_monthly_eur"] is None
    assert len(report["work"]) == len(snapshot["resources"])


def test_live_cli_uses_cloudflare(tmp_path, monkeypatch):
    snapshot = json.loads((DEMO / "sample_snapshot.json").read_text())
    monkeypatch.setattr("sovereign_shift.cli.cloudflare.scan", lambda: snapshot)
    result = CliRunner().invoke(app, ["all", "--source", "cloudflare", "--no-ai", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.exception
    assert json.loads((tmp_path / "inventory.json").read_text()) == snapshot


def test_fallback_asks_only_for_unmapped():
    class FakeAI:
        enabled = True

        def info(self):
            return {}

        def complete(self, system, user, model):
            assert "hidden-origin" not in user and ACCOUNT not in user
            assert json.loads(user)["resource"]["type"] != "cloudflare_r2_bucket"
            return AIAnswer(alternative="Self-hosted service", justification="Requires manual configuration.",
                            effort="medium", confidence=0.6)

    snapshot = json.loads((DEMO / "sample_snapshot.json").read_text())
    result = translate(snapshot, ai=FakeAI())
    by_name = {entry.source_name: entry for entry in result.entries}
    assert by_name["shift-demo"].ai_suggested
    assert by_name["shift-demo-assets"].via == "runbook"
    assert not by_name["stock.example.test"].ai_suggested


def test_pagination_denials_and_private_bindings():
    def response(request):
        if request.url.path.endswith("/settings"):
            return httpx.Response(200, json={"success": True, "result": {"bindings": [
                {"type": "secret_text", "name": "KEY", "text": "never-store"},
                {"type": "future", "name": "NEXT", "value": "never-store"}]}})
        if request.url.path.endswith("/r2/buckets"):
            second = request.url.params.get("cursor") == "next"
            return httpx.Response(200, json={"success": True, "result": {"buckets": [
                {"name": "second" if second else "first"}]}, "result_info": {} if second else {"cursor": "next"}})
        if request.url.path.endswith("/zones"):
            return httpx.Response(403)
        return demo_response(request)

    with httpx.Client(base_url="https://example.test", transport=httpx.MockTransport(response)) as client:
        snapshot = scan_account(ACCOUNT, client)
    assert snapshot["denied"][0]["operation"] == "/zones"
    assert "never-store" not in json.dumps(snapshot)
    assert {"first", "second", "NEXT"} <= {r["name"] for r in snapshot["resources"]}
