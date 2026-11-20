import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from sovereign_shift.cli import app
from sovereign_shift.finalize.apply import finalize
from sovereign_shift.generator.build import API
from sovereign_shift.runbook.build import Selection, validate_selection


def test_runbook_rejects_untrusted_inputs():
    template = [{"id": "copy", "inputs": {"host": {"source": "customer"}}}]
    for identifier, inputs in [
        ("invented", {}),
        ("copy", {}),
        ("copy", {"host": "secret-value"}),
    ]:
        choice = Selection(
            steps=[dict(id=identifier, inputs=inputs)],
            notes={},
            justification="resource-type migration",
        )
        with pytest.raises(ValueError):
            validate_selection(choice, template)


def test_finalize_resolves_private_addresses_and_reuses_groups():
    routes = {
        "/instances/1/ips": {"ips": [dict(networkType="INTERNAL", ip="10.0.1.1")]},
        "/securityGroups": {"securityGroups": [dict(id="22", name="db")]},
        "/securityGroups/22/firewallRules": {"firewallRules": []},
        "/instances/2/securityGroups": {"securityGroups": []},
    }

    def handle(request):
        path = request.url.path.removeprefix("/publicCloud/v1")
        assert request.headers["X-LSW-Auth"] == "test"
        if request.method == "GET":
            return httpx.Response(200, json=routes[path])
        return httpx.Response(204)

    plan = dict(
        api=API,
        security_groups=[
            dict(
                name="db",
                attach_to=["db"],
                rules=[
                    dict(
                        protocol="TCP",
                        start_port=5432,
                        end_port=5432,
                        source={"private_ip_of": "web"},
                    )
                ],
            )
        ],
        target_registrations=[],
    )
    outputs = {"web": {"value": "1"}, "db": {"value": "2"}}
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        calls = finalize(plan, outputs, None, "test", client)
    posts = [c for c in calls if c["method"] == "POST"]
    assert posts[0]["body"]["rules"][0]["source"] == "10.0.1.1/32"
    assert posts[1]["body"] == {"securityGroupIds": ["22"]}


def test_offline_commands(tmp_path: Path):
    inventory = dict(
        account_id="123456789012",
        resources=[
            dict(
                id="bucket",
                type="s3_bucket",
                name="demo-bucket",
                properties={"public": True},
            ),
            dict(id="unsupported", type="other", name="demo-other"),
        ],
    )
    entries = [
        dict(
            source_id=r["id"],
            source_type=r["type"],
            status="partial" if r["id"] == "bucket" else "unsupported",
            via="runbook" if r["id"] == "bucket" else "report",
            target=None,
            monthly_cost_eur={"aws": None, "leaseweb": None},
        )
        for r in inventory["resources"]
    ]
    (tmp_path / "inventory.json").write_text(json.dumps(inventory))
    (tmp_path / "mapping.json").write_text(
        json.dumps(dict(target_region="eu-west-3", entries=entries))
    )
    runner = CliRunner()
    for args in [
        ["graph", str(tmp_path / "inventory.json")],
        ["generate"],
        ["runbook", "--no-ai"],
        ["report"],
    ]:
        result = runner.invoke(app, [*args, "--out", str(tmp_path)])
        assert result.exit_code == 0, result.exception
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["findings"][0]["id"] == "S3-001"
    assert report["runbook"]["entries"][1]["not_capable"]
    assert "rclone copy" in (tmp_path / "report.md").read_text()
    assert "123456789012" not in json.dumps(report)


def test_offline_demo(tmp_path: Path):
    examples = Path(__file__).resolve().parents[1] / "examples"
    result = CliRunner().invoke(app, [
        "all", "--from-snapshot", str(examples / "sample_inventory.json"),
        "--mapping", str(examples / "sample_mapping.json"), "--no-ai", "--out", str(tmp_path),
    ])
    assert result.exit_code == 0, result.exception
    assessment = json.loads((tmp_path / "report.json").read_text())
    assert any(e["type"] == "talks_to" and e["inferred"] for e in assessment["graph"]["edges"])
    assert any(f["id"] == "SG-001" for f in assessment["findings"])
    assert assessment["finalize"]["target_registrations"]
    assert assessment["runbook"]["generated_by"] == "template-default"
