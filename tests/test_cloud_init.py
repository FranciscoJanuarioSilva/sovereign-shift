import subprocess

import yaml

from sovereign_shift.generator.build import cloud_init


def parse(text: str) -> dict:
    assert text.startswith("#cloud-config\n")
    return yaml.safe_load(text.split("\n", 1)[1])


def test_private_network_script_is_not_tied_to_a_nic_name() -> None:
    config = parse(cloud_init(["ssh-ed25519 AAAA example"]))
    script = config["write_files"][0]["content"]
    assert "eth1" not in script
    assert subprocess.run(["sh", "-n"], input=script, text=True).returncode == 0
    assert config["ssh_authorized_keys"] == ["ssh-ed25519 AAAA example"]


def test_postgres_keeps_the_aws_major_version() -> None:
    config = parse(cloud_init([], {"engine": "postgres", "engine_version": "18.3"}))
    # ubuntu ships an older postgres, and pg_restore can't load a newer dump
    assert config["packages"] == ["postgresql-18"]
    assert "apt.postgresql.org" in config["apt"]["sources"]["pgdg"]["source"]
    assert "ssh_authorized_keys" not in config


def test_mysql_engine() -> None:
    assert parse(cloud_init([], {"engine": "mysql", "engine_version": "8.0.36"}))["packages"] == ["mysql-server"]
