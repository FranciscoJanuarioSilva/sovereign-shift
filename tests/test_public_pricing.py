"""Pricing sources: official old Public Cloud versus different-platform proxies."""

import json

from sovereign_shift.translator import catalog


def test_public_fallback_distinguishes_legacy_prices_and_proxies(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "CATALOG", tmp_path / "missing-api.json")
    catalog.leaseweb_types.cache_clear()
    try:
        types, source = catalog.leaseweb_types()
        prices = {item.name: item for item in types}
        assert "openstack-proxies" in source
        assert prices["lsw.m6a.large"].price_monthly_eur == 34.68
        assert prices["lsw.m6a.large"].price_estimated is True
        assert prices["lsw.c6a.large"].price_monthly_eur == 30.35
        assert prices["lsw.c6a.large"].price_estimated is True
        assert prices["lsw.g6.xlarge"].price_monthly_eur == 253.40
        assert prices["lsw.g6.xlarge"].price_estimated is False
        # A third-party quote, not a confirmed API/account price.
        assert prices["lsw.m3.large"].price_estimated is True
    finally:
        catalog.leaseweb_types.cache_clear()


def test_authenticated_catalog_wins_over_public_snapshot(tmp_path, monkeypatch):
    source = tmp_path / "leaseweb_catalog.json"
    source.write_text(json.dumps({
        "source": "api", "fetched_at": "2026-11-20",
        "instance_types": [{
            "name": "lsw.m6a.large", "vcpu": 2, "memory_gib": 8,
            "region": "eu-west-3", "price_monthly_eur": 50.00,
        }],
    }))
    monkeypatch.setattr(catalog, "CATALOG", source)
    catalog.leaseweb_types.cache_clear()
    try:
        types, catalog_source = catalog.leaseweb_types()
        assert catalog_source == "catalog:api:2026-11-20"
        assert len(types) == 1
        assert types[0].price_monthly_eur == 50.0
        assert types[0].price_estimated is False
    finally:
        catalog.leaseweb_types.cache_clear()
