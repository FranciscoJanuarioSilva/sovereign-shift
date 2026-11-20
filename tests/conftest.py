from pathlib import Path

import pytest

from sovereign_shift.translator import catalog

SMALL = Path(__file__).resolve().parents[1] / "testdata" / "leaseweb_catalog_small.json"


@pytest.fixture(autouse=True)
def fixed_catalog(monkeypatch):
    """Every test runs on a small fixed catalog, so refreshing data/leaseweb_catalog.json can't break them."""
    monkeypatch.delenv("SOVEREIGN_LEASEWEB_CATALOG", raising=False)
    monkeypatch.setattr(catalog, "CATALOG", SMALL)
    catalog.leaseweb_types.cache_clear()
    yield
    catalog.leaseweb_types.cache_clear()
