import json

import pytest
from typer.testing import CliRunner

from sovereign_shift.cli import app
from sovereign_shift.graph import build_graph, render_html


def resource(identifier, kind, groups=(), **properties):
    return {
        "id": identifier, "type": kind, "properties": properties,
        "relations": [{"type": "uses_security_group", "target": group} for group in groups],
    }


@pytest.mark.parametrize("raw", [False, True])
def test_database_inference(raw):
    rule = (
        {"IpProtocol": "tcp", "FromPort": 5432, "ToPort": 5432,
         "UserIdGroupPairs": [{"GroupId": "web-sg"}]}
        if raw else
        {"protocol": "tcp", "from_port": 5432, "to_port": 5432,
         "security_groups": ["web-sg"]}
    )
    inventory = {"resources": [
        resource("web", "ec2_instance", ["web-sg"]),
        resource("other", "ec2_instance"),
        resource("db", "db_instance", ["db-sg"], engine="postgres"),
        resource("web-sg", "security_group"),
        resource("db-sg", "security_group", **{"IpPermissions" if raw else "ingress": [rule]}),
    ]}
    graph = build_graph(inventory)
    inferred = [edge for edge in graph["edges"] if edge.get("inferred")]
    assert inferred == [{"from": "web", "to": "db", "type": "talks_to", "inferred": True, "evidence": "db-sg allows web-sg on TCP/5432"}]
    rule["IpProtocol" if raw else "protocol"] = "udp"
    assert not any(edge.get("inferred") for edge in build_graph(inventory)["edges"])


def test_missing_targets_duplicates_and_cycles():
    a = resource("a", "ec2_instance", ["missing"])
    a["relations"] += [{"type": "depends_on", "target": "b"}] * 2
    b = resource("b", "ec2_instance")
    b["relations"] = [{"type": "depends_on", "target": "a"}]
    inventory = {"resources": [a, b]}
    graph = build_graph(inventory)
    assert len(graph["edges"]) == 3
    assert graph["findings"][0]["resource"] == "missing"
    assert graph == build_graph({"resources": [b, a]})
    assert "<svg" in render_html(graph)


def test_duplicate_ids_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        build_graph({"resources": [resource("a", "vpc"), resource("a", "subnet")]})


def test_empty_and_html_escaping():
    assert build_graph({"resources": []}) == {"nodes": [], "edges": [], "findings": []}
    assert "<svg" in render_html(build_graph({"resources": []}))
    graph = build_graph({"resources": [resource("<script>alert(1)</script>", "vpc")]})
    html = render_html(graph)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_cli(tmp_path):
    inventory = tmp_path / "snapshot.json"
    inventory.write_text(json.dumps({"resources": [resource("web", "ec2_instance")]}))
    output = tmp_path / "output"
    result = CliRunner().invoke(app, ["graph", str(inventory), "--out", str(output)])
    assert result.exit_code == 0, result.output
    assert json.loads((output / "graph.json").read_text())["nodes"][0]["id"] == "web"
    assert "<svg" in (output / "graph.html").read_text()
    inventory.write_text('{"resources": null}')
    assert CliRunner().invoke(app, ["graph", str(inventory)]).exit_code != 0
