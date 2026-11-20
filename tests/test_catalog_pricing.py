"""Leaseweb catalog: real prices from a committed snapshot, storage rules, currencies, the fetch script."""

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from sovereign_shift.translator import catalog, translate

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = json.loads((ROOT / "testdata" / "clickops_inventory.json").read_text())


def entries(**kwargs):
    return {e.source_id: e for e in translate(INVENTORY, **kwargs).entries}


def test_instance_uses_real_price_and_matching_disk_kind():
    web1 = entries()["i-web1"]
    # m6a is local-nvme only in amsterdam, so a CENTRAL root disk would fail at apply
    assert web1.target["instance_type"] == "lsw.m6a.large"
    assert web1.target["root_disk_storage_type"] == "LOCAL"
    assert any("local NVMe" in n for n in web1.notes)
    assert web1.monthly_cost_eur.leaseweb == 37.38
    assert web1.monthly_cost_eur.leaseweb_estimated is False


def test_database_prefers_central_storage():
    db = entries()["db-orders"]
    chosen = next(t for t in catalog.leaseweb_types()[0] if t.name == db.target["instance_type"] and t.region == "eu-west-3")
    assert "central" in chosen.storage_types
    assert db.target["root_disk_storage_type"] == "CENTRAL"
    assert not any("local NVMe" in n for n in db.notes)


def test_non_euro_region_has_unknown_price_not_a_wrong_one():
    web1 = entries(target_region="eu-west-2")["i-web1"]
    assert web1.target["instance_type"] == "lsw.m6a.large"
    assert web1.monthly_cost_eur.leaseweb is None
    assert web1.monthly_cost_eur.leaseweb_estimated is False


def test_customer_can_use_their_own_catalog(tmp_path, monkeypatch):
    own = tmp_path / "my-prices.json"
    small = json.loads((ROOT / "testdata" / "leaseweb_catalog_small.json").read_text())
    for row in small["instance_types"]:
        if row["name"] == "lsw.m6a.large" and row["region"] == "eu-west-3":
            row["price_monthly_eur"] = 12.34
    small["fetched_at"] = "2030-02-03T00:00:00Z"
    own.write_text(json.dumps(small))
    monkeypatch.setenv("SOVEREIGN_LEASEWEB_CATALOG", str(own))
    catalog.leaseweb_types.cache_clear()
    mapping = translate(INVENTORY)
    assert mapping.catalog_source == "catalog:api:2030-02-03T00:00:00Z"
    assert {e.source_id: e for e in mapping.entries}["i-web1"].monthly_cost_eur.leaseweb == 12.34


def test_committed_snapshot_is_usable():
    data = json.loads((ROOT / "data" / "leaseweb_catalog.json").read_text())
    assert data["source"] == "api" and data["fetched_at"]
    currency = {r["code"]: r["currency"] for r in data["regions"]}
    # the provider only accepts these regions, so the snapshot has to cover them all
    assert set(catalog.schema_enums()["region"]) <= set(currency)
    assert currency["eu-west-3"] == currency["eu-central-1"] == "EUR"
    for row in data["instance_types"]:
        assert row["vcpu"] > 0 and row["memory_gib"] > 0 and row["storage_types"]
        if row["currency"] == "EUR":
            assert row["price_monthly_eur"] and row["price_monthly_eur"] > 0
        else:
            # never a GBP or JPY number in a field the report reads as EUR
            assert row["price_monthly_eur"] is None and row["price_hourly_eur"] is None
    names = {(r["region"], r["name"]) for r in data["instance_types"]}
    assert ("eu-west-3", "lsw.m6a.large") in names


def load_script():
    spec = importlib.util.spec_from_file_location("fetch_catalog", ROOT / "scripts" / "fetch_leaseweb_catalog.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def api_item(name, storage=("LOCAL",)):
    return {
        "name": name,
        "resources": {"cpu": {"value": 2}, "memory": {"value": 8}, "gpu": {"value": 0}},
        "prices": {"hourly": "0.0528", "monthly": "37.3800"},
        "storageTypes": list(storage), "minDiskSize": 5,
    }


def test_fetch_script_converts_by_currency():
    script = load_script()
    eur = script.convert("eu-west-3", "EUR", api_item("lsw.m6a.large"))
    assert eur["price_monthly_eur"] == 37.38 and eur["storage_types"] == ["local"] and eur["vcpu"] == 2
    gbp = script.convert("eu-west-2", "GBP", api_item("lsw.m6a.large"))
    assert gbp["price_monthly_eur"] is None and gbp["price_monthly_local"] == 37.38 and gbp["currency"] == "GBP"


def test_fetch_script_follows_pages_and_sends_the_token():
    script = load_script()
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.headers.get("X-LSW-Auth"), int(request.url.params["offset"])))
        offset = int(request.url.params["offset"])
        count = min(script.PAGE, 120 - offset)
        items = [api_item(f"lsw.m6a.t{offset + i}") for i in range(count)]
        return httpx.Response(200, json={"instanceTypes": items, "_metadata": {"totalCount": 120, "currency": "EUR"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        client.headers["X-LSW-Auth"] = "test-token"
        items, meta = script.paged(client, "/instanceTypes", "instanceTypes", region="eu-west-3")
    assert len(items) == 120 and meta["currency"] == "EUR"
    assert [offset for _, offset in seen] == [0, 50, 100]
    assert {token for token, _ in seen} == {"test-token"}


def test_fetch_script_stops_on_a_rejected_token():
    script = load_script()
    transport = httpx.MockTransport(lambda r: httpx.Response(401, json={}))
    with httpx.Client(transport=transport) as client, pytest.raises(SystemExit) as stop:
        script.get(client, "/regions")
    assert "401" in str(stop.value)


def test_fetch_script_never_writes_a_broken_file(tmp_path):
    script = load_script()
    target = tmp_path / "catalog.json"
    row = script.convert("eu-west-3", "EUR", api_item("lsw.m6a.large"))
    script.write(target, {"fetched_at": "2026-01-01T00:00:00Z", "source": "api"}, [row, row])
    data = json.loads(target.read_text())
    assert len(data["instance_types"]) == 2 and data["source"] == "api"
    assert not list(tmp_path.glob("*.tmp"))


def test_report_says_where_prices_come_from(tmp_path):
    from typer.testing import CliRunner

    from sovereign_shift.cli import app

    out = tmp_path / "out"
    result = CliRunner().invoke(app, ["all", "--from-snapshot", str(ROOT / "testdata" / "clickops_inventory.json"), "--out", str(out), "--no-ai"])
    assert result.exit_code == 0, result.output
    report = (out / "report.md").read_text()
    assert "Public Cloud API prices from a snapshot taken 2026-01-01" in report
    assert "OpenStack" not in report
    # a snapshot that old gets a refresh warning
    assert "days old, refresh it" in report


def test_every_mapped_region_is_accepted_by_the_provider():
    # a region the provider rejects would be silently swapped for the default, so the mapping must never produce one
    info = catalog.regions()
    accepted = set(catalog.schema_enums()["region"])
    assert set(info["aws_to_leaseweb"].values()) <= accepted
    assert info["default"] in accepted
    flagged = {code for code, row in info["leaseweb_codes"].items() if row.get("provider_accepts") is False}
    assert flagged == set(info["leaseweb_codes"]) - accepted


def test_real_regional_aws_price_wins_over_the_table():
    # t3.large in eu-north-1 has a real price in data/aws_instance_types.json, 0.0864 USD/h
    web1 = entries()["i-web1"]
    data = catalog.aws_types()
    expected = round(data["regional"]["eu-north-1"]["t3.large"] * data["hours_per_month"] * data["usd_to_eur"], 2)
    assert web1.monthly_cost_eur.aws == expected
    assert web1.monthly_cost_eur.aws_estimated is False
    # a type without a regional price still falls back to the approximate table and says so
    inventory = json.loads(json.dumps(INVENTORY))
    inventory["resources"][0]["region"] = "eu-west-1"
    for r in inventory["resources"]:
        if r["id"] == "i-web1":
            r["region"] = "eu-west-1"
    other = {e.source_id: e for e in translate(inventory).entries}["i-web1"]
    assert other.monthly_cost_eur.aws_estimated is True
