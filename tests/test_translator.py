import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sovereign_shift.ai import redact
from sovereign_shift.ai.client import AIClient
from sovereign_shift.cli import app
from sovereign_shift.translator.models import Mapping
from sovereign_shift.translator import translate
from sovereign_shift.translator.translate import tf_names

FIXTURE = Path(__file__).resolve().parents[1] / "testdata" / "clickops_inventory.json"


@pytest.fixture
def inventory():
    return json.loads(FIXTURE.read_text())


def by_id(mapping: Mapping):
    return {e.source_id: e for e in mapping.entries}


def test_every_resource_gets_one_entry(inventory):
    mapping = translate(inventory)
    assert sorted(by_id(mapping)) == sorted(r["id"] for r in inventory["resources"])
    assert mapping.target_region == "eu-west-3"


def test_instance_sizing_region_image(inventory):
    e = by_id(translate(inventory))
    web1 = e["i-web1"]
    assert web1.target["instance_type"] == "lsw.m6a.large"
    assert web1.target["region"] == "eu-west-3"
    assert web1.target["image_id"] == "UBUNTU_22_04_64BIT"
    # root 30 + extra 100
    assert web1.target["root_disk_size"] == 130
    assert web1.target["has_private_network"] is True
    assert web1.status == "partial"
    web2 = e["i-web2"]
    assert web2.status == "partial"
    assert any("graviton" in n for n in web2.notes)
    assert web2.target["image_id"] == "ALMALINUX_9_64BIT"


def test_target_region_override_and_validation(inventory):
    mapping = translate(inventory, target_region="eu-central-1")
    assert by_id(mapping)["i-web1"].target["region"] == "eu-central-1"
    with pytest.raises(ValueError):
        translate(inventory, target_region="eu-north-1")


def test_security_groups_fix_findings(inventory):
    e = by_id(translate(inventory))
    names = tf_names(inventory["resources"])
    web = e["sg-web"]
    assert web.via == "finalize"
    assert {"protocol": "TCP", "start_port": 22, "end_port": 22, "source": {"cidr": "var:admin_cidr"}} in web.target["rules"]
    assert sorted(web.target["attach_to"]) == sorted([names["i-web1"], names["i-web2"]])
    # rule from the lb group becomes the private range
    assert any(r["source"] == {"cidr": "var:private_network_cidr"} for r in web.target["rules"])
    db = e["sg-db"]
    sources = [r["source"] for r in db.target["rules"]]
    assert {"private_ip_of": names["i-web1"]} in sources
    # 5432 from the internet must not survive, it goes to the known clients instead
    assert {"cidr": "0.0.0.0/0"} not in sources
    assert {"cidr": "var:admin_cidr"} not in sources
    assert any("app instances' private ips" in n for n in db.notes)
    assert db.target["attach_to"] == [names["db-orders"]]
    assert e["sg-old"].target is None and e["sg-lb"].target is None


def test_db_lb_dns_s3(inventory):
    e = by_id(translate(inventory))
    db = e["db-orders"]
    assert db.status == "manual" and db.via == "runbook"
    assert db.target["kind"] == "self_hosted_db" and db.target["engine"] == "postgres"
    assert db.target["root_disk_size"] >= 60
    assert e["lsn-1"].status == "partial" and e["lsn-1"].target["protocol"] == "HTTPS"
    names = tf_names(inventory["resources"])
    assert e["lsn-1"].target["default_target_group"] == names["tg-1"]
    assert e["lsn-1"].target["load_balancer"] == names["lb-1"]
    assert sorted(e["tg-1"].target["members"]) == sorted([names["i-web1"], names["i-web2"]])
    assert e["tg-1"].target["health_check"]["port"] == 80
    rec = e["rec-www"].target
    assert rec["type"] == "A" and rec["ttl"] == 60 and rec["alias_of"] == names["lb-1"]
    assert rec["domain_name"] == "shop.example.com"
    assert e["bucket-assets"].target["endpoint"] == "https://nl.object-storage.io"
    assert e["eip-1"].status == "manual"
    # newest generation wins over an older type with less ram
    assert e["lb-1"].target["type"] == "lsw.m6a.large"


def test_scanner_shaped_fields():
    # field names exactly as sovereign_shift/scanner/aws.py writes them
    inventory = {"regions": ["eu-north-1"], "resources": [
        {"id": "i-1", "type": "ec2_instance", "region": "eu-north-1", "name": "app",
         "properties": {"instance_type": "t3.large", "vcpu": 2, "memory_gib": 8.0,
                        "os": "ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-20240801",
                        "volumes": [{"id": "vol-1", "root": True, "size_gib": 8}]},
         "relations": [{"type": "uses_volume", "target": "vol-1"}]},
        {"id": "vol-1", "type": "ebs_volume", "region": "eu-north-1", "name": "vol-1", "properties": {"size_gib": 8}, "relations": []},
        {"id": "arn:aws:elasticloadbalancing:eu-north-1:1:targetgroup/tg/abc", "type": "target_group", "region": "eu-north-1", "name": "tg",
         "properties": {"port": 80, "protocol": "HTTP", "target_type": "instance", "health_check_path": "/up",
                        "health_check_protocol": "HTTP", "health_check_port": "traffic-port", "targets": [{"id": "i-1", "port": 80}]},
         "relations": [{"type": "targets", "target": "i-1"}]},
        {"id": "arn:aws:elasticloadbalancing:eu-north-1:1:listener/app/x/y/z", "type": "lb_listener", "region": "eu-north-1",
         "name": "arn:aws:elasticloadbalancing:eu-north-1:1:listener/app/x/y/z", "properties": {"port": 80, "protocol": "HTTP"},
         "relations": [{"type": "forwards_to", "target": "arn:aws:elasticloadbalancing:eu-north-1:1:targetgroup/tg/abc"}]},
        {"id": "db", "type": "db_instance", "region": "eu-north-1", "name": "db",
         "properties": {"engine": "postgres", "instance_class": "db.t4g.micro", "storage_gib": 100}, "relations": []},
        {"id": "Z1/example.com./NS", "type": "route53_record", "region": "global", "name": "example.com.",
         "properties": {"record_type": "NS", "ttl": 172800}, "relations": [{"type": "in_zone", "target": "Z1"}]},
        {"id": "Z1", "type": "route53_zone", "region": "global", "name": "example.com.", "properties": {}, "relations": []},
        {"id": "eipalloc-1", "type": "elastic_ip", "region": "eu-north-1", "name": "eipalloc-1", "properties": {}, "relations": []},
    ]}
    e = by_id(translate(inventory))
    assert e["i-1"].target["image_id"] == "UBUNTU_24_04_64BIT"
    tg = e["arn:aws:elasticloadbalancing:eu-north-1:1:targetgroup/tg/abc"].target
    assert tg["members"] == ["app"] and tg["health_check"] == {"protocol": "HTTP", "port": 80, "uri": "/up", "method": "GET"}
    assert e["arn:aws:elasticloadbalancing:eu-north-1:1:listener/app/x/y/z"].tf_name == "lb_listener_80"
    assert e["db"].target["root_disk_size"] == 130
    assert not any("graviton" in n for n in e["db"].notes)
    assert e["vol-1"].status == "auto"
    assert e["Z1/example.com./NS"].via == "report" and e["eipalloc-1"].status == "auto"


def test_unknown_service_without_ai(inventory):
    e = by_id(translate(inventory))["fn-thumbs"]
    assert e.status == "unsupported" and not e.ai_suggested


class FakeAI(AIClient):
    def __init__(self, tmp_path, answer):
        super().__init__(tmp_path)
        self.model, self.api_key, self.answer, self.prompts = "fake", "fake", answer, []

    def _call(self, system, user):
        self.prompts.append(user)
        return self.answer


def test_ai_fills_unsupported(inventory, tmp_path):
    answer = json.dumps({
        "alternative": "Python worker on a Leaseweb instance, triggered by object storage events via a cron poll",
        "justification": "Small python lambda reading from the bucket, a tiny worker does the same.",
        "effort": "Medium", "manual_steps": ["package the function", "run it as a systemd service"], "confidence": 0.7,
    })
    ai = FakeAI(tmp_path, answer)
    e = by_id(translate(inventory, ai=ai))["fn-thumbs"]
    assert e.ai_suggested and e.status == "manual" and e.alternative.effort == "medium"
    # the secret env var never reaches the model
    assert "hunter2" not in ai.prompts[0] and "123456789012" not in ai.prompts[0]
    # second run is served from the cache
    ai2 = FakeAI(tmp_path, "not json")
    assert by_id(translate(inventory, ai=ai2))["fn-thumbs"].ai_suggested
    assert ai2.prompts == []


def test_bad_ai_answer_falls_back(inventory, tmp_path):
    ai = FakeAI(tmp_path, '{"alternative": "x"}')
    e = by_id(translate(inventory, ai=ai))["fn-thumbs"]
    assert e.status == "unsupported" and not e.ai_suggested
    assert len(ai.prompts) == 2


def test_redact():
    data = {"password": "x", "note": "arn:aws:iam::123456789012:role/a on 10.0.0.5", "cidr": "0.0.0.0/0"}
    out = redact(data)
    assert "password" not in out
    assert "123456789012" not in out["note"] and "10.0.0.5" not in out["note"]
    assert out["cidr"] == "0.0.0.0/0"


def test_cli_translate(tmp_path):
    result = CliRunner().invoke(app, ["translate", str(FIXTURE), "--out", str(tmp_path), "--no-ai"])
    assert result.exit_code == 0, result.output
    data = json.loads((tmp_path / "mapping.json").read_text())
    Mapping.model_validate(data)
    assert "eu-west-3" in result.output
