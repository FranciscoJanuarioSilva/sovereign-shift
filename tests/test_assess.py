"""Assessment sections on the sample store: the story the report tells has to stay true."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sovereign_shift.assess import assess
from sovereign_shift.assess.common import grade
from sovereign_shift.assess.risk import rating
from sovereign_shift.cli import app
from sovereign_shift.graph import build_graph
from sovereign_shift.graph.security import findings
from sovereign_shift.translator import translate

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "testdata" / "clickops_inventory.json"


@pytest.fixture
def result():
    inventory = json.loads(STORE.read_text())
    graph = build_graph(inventory)
    mapping = json.loads(translate(inventory, graph).model_dump_json())
    return assess(inventory, graph, findings(inventory, graph), mapping)


def test_posture_improves_because_the_migration_fixes_findings(result):
    p = result["posture"]
    assert p["overall"]["after"] > p["overall"]["before"]
    fixed = {(f["id"], f["name"]) for f in p["findings"] if f["fixed_by_migration"]}
    assert {("SG-001", "web-sg"), ("SG-002", "db-sg"), ("RDS-001", "orders")} <= fixed
    # unencrypted storage is not something the move fixes
    assert not any(f["fixed_by_migration"] for f in p["findings"] if f["id"] == "RDS-002")
    network = next(d for d in p["domains"] if d["id"] == "network")
    assert network["after"] > network["before"]
    # no iam data in the fixture, so identity must say so instead of scoring 100
    assert "Access and identity" in p["not_assessed"]


def test_exposure_before_and_after(result):
    exposure = result["posture"]["exposure"]
    before = {x["name"]: x["ports"] for x in exposure["before"]}
    after = {x["name"] for x in exposure["after"]}
    assert before["orders"] == ["tcp/5432"] and before["web-1"] == ["tcp/22"]
    assert "orders" not in after and "web-1" not in after
    assert {"web-alb", "shop-assets"} <= after


def test_risk_drops_and_readiness_has_conditions(result):
    r = result["risk"]["overall"]
    assert r["current"] == "critical" and r["after_migration"] == "high"
    assert r["readiness"] == "ready with conditions"
    assert r["resolved_by_migration"] >= 3
    register = result["risk"]["register"]
    public_db = next(x for x in register if x["title"].startswith("Restrict database ingress"))
    assert public_db["rating"] == "critical" and public_db["rating_after"] == "resolved"
    # exposure must not make an availability risk more likely
    single_zone = next(x for x in register if x["title"].startswith("Run the database in more than one zone"))
    assert single_zone["category"] == "availability" and single_zone["likelihood"] == 2
    phases = {x["id"].split("-")[1]: x["phase"] for x in register if x["id"].startswith("M-")}
    assert phases["DATA"] == "cutover" and phases["DB"] == "lasting"
    assert sum(map(sum, result["risk"]["heatmap"])) == len(register)


def test_performance_rows_and_warnings(result):
    rows = {x["name"]: x for x in result["performance"]["rows"]}
    assert set(rows) == {"web-1", "web-2", "orders"}
    assert rows["web-1"]["leaseweb_type"] == "lsw.m6a.large" and rows["web-1"]["leaseweb_memory_gib"] == 8
    assert any(n["severity"] == "warning" and "ARM" in n["note"] for n in rows["web-2"]["notes"])
    assert result["performance"]["not_assessed"]


def test_scaling_tiers_spof_and_prices(result):
    s = result["scaling"]
    web = next(t for t in s["tiers"] if t["kind"] == "web behind load balancer")
    assert web["servers"] == 2 and web["horizontal"]
    assert any(x["what"] == "orders" for x in s["single_points_of_failure"])
    up = next(x for x in s["scale_up"] if x["resource"] == "web-1")
    # from the small fixed catalog: m6a.large 37.38 -> m6a.xlarge 74.77
    assert up["to"] == "lsw.m6a.xlarge" and up["extra_eur_month"] == 37.39


def test_grade_and_rating_bands():
    assert [grade(s) for s in (95, 80, 65, 45, 10)] == ["A", "B", "C", "D", "F"]
    assert [rating(s) for s in (25, 20, 12, 6, 5)] == ["critical", "critical", "high", "medium", "low"]


def test_report_has_every_section_without_ai(tmp_path):
    out = tmp_path / "out"
    run = CliRunner().invoke(app, ["all", "--from-snapshot", str(STORE), "--out", str(out), "--no-ai"])
    assert run.exit_code == 0, run.output
    report = (out / "report.md").read_text()
    for heading in ("## Executive summary", "## Security posture", "## Risk assessment", "## Performance", "## Scaling"):
        assert heading in report
    assert "| Security posture | D (41/100) | C (69/100) |" in report
    assert (out / "public" / "assessment.json").exists()
    # tables must start after a blank line or github won't render them
    assert "fixes.\n\n| Area" in report


def test_imdsv1_risk_ends_with_the_move():
    inventory = json.loads(STORE.read_text())
    for r in inventory["resources"]:
        if r["type"] == "ec2_instance":
            r["properties"]["http_tokens"] = "optional"
    graph = build_graph(inventory)
    mapping = json.loads(translate(inventory, graph).model_dump_json())
    result = assess(inventory, graph, findings(inventory, graph), mapping)
    imds = [f for f in result["posture"]["findings"] if f["id"] == "EC2-001"]
    assert imds and all(f["fixed_by_migration"] for f in imds)
