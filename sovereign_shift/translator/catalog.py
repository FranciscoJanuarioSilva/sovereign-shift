"""Reference data the translator needs: leaseweb instance types, aws specs and prices, regions, images."""

import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "docs" / "schemas" / "leaseweb.json"
CATALOG = ROOT / "data" / "leaseweb_catalog.json"
AWS_TYPES = ROOT / "data" / "aws_instance_types.json"
REGIONS = ROOT / "mappings" / "regions.yaml"
IMAGES = ROOT / "mappings" / "images.yaml"

SIZE_VCPU = {
    "large": 2, "xlarge": 4, "2xlarge": 8, "4xlarge": 16, "8xlarge": 32,
    "9xlarge": 36, "12xlarge": 48, "16xlarge": 64, "18xlarge": 72, "24xlarge": 96,
}
# kb ratios: compute 1:2, general 1:4, memory 1:8 (gib per vcpu)
RATIO = {"c": 2, "m": 4, "r": 8, "g": 4, "gr": 8}
# only real price found is lsw.c6a.large at 34.39 eur/month (docs/research/leaseweb-api.md)
# the m and r rates are guesses scaled from it, marked as estimates everywhere
EUR_PER_VCPU = {"c": 34.39 / 2, "m": 34.39 / 2 * 1.15, "r": 34.39 / 2 * 1.4, "g": 60.0, "gr": 80.0}
KNOWN_PRICES = {"lsw.c6a.large": 34.39, "lsw.m3.large": 29.44}
KNOWN_MEMORY = {"lsw.m3.large": 7}
GEN_RANK = {"6a": 6, "6": 6, "5a": 5, "5": 4, "4": 3, "3": 2}
NAME_RE = re.compile(r"^lsw\.([a-z]+?)(\d+[a-z]?)\.(\w+)$")


@dataclass(frozen=True)
class LswType:
    name: str
    family: str
    generation: str
    vcpu: int
    memory_gib: float
    price_monthly_eur: float | None
    price_estimated: bool
    region: str | None  # none means every region

    @property
    def rank(self) -> int:
        return GEN_RANK.get(self.generation, 0)


def parse_name(name: str) -> tuple[str, str, str] | None:
    match = NAME_RE.match(name)
    return match.groups() if match else None


def _enum_from_description(description: str) -> list[str]:
    # the provider lists valid values in the description as "- *value*"
    return re.findall(r"\*([^*\s]+)\*", description)


@cache
def schema_enums() -> dict[str, list[str]]:
    attrs = json.loads(SCHEMA.read_text())["resource_schemas"]["leaseweb_public_cloud_instance"]["block"]["attributes"]
    return {
        "type": _enum_from_description(attrs["type"]["description"]),
        "region": [r for r in _enum_from_description(attrs["region"]["description"]) if "-" in r],
    }


def _fallback_types() -> list[LswType]:
    out = []
    for name in schema_enums()["type"]:
        parsed = parse_name(name)
        if not parsed or parsed[2] not in SIZE_VCPU:
            continue
        family, generation, size = parsed
        vcpu = SIZE_VCPU[size]
        price = KNOWN_PRICES.get(name)
        out.append(LswType(
            name=name, family=family, generation=generation, vcpu=vcpu,
            memory_gib=KNOWN_MEMORY.get(name, vcpu * RATIO.get(family, 4)),
            price_monthly_eur=price if price is not None else round(vcpu * EUR_PER_VCPU.get(family, 20.0), 2),
            price_estimated=price is None, region=None,
        ))
    return out


def _api_types(data: dict) -> list[LswType]:
    out = []
    for item in data.get("instance_types", []):
        parsed = parse_name(item["name"])
        if not parsed:
            continue
        price = item.get("price_monthly_eur")
        if price is None and item.get("price_hourly_eur") is not None:
            price = round(float(item["price_hourly_eur"]) * 730, 2)
        out.append(LswType(
            name=item["name"], family=parsed[0], generation=parsed[1],
            vcpu=int(item["vcpu"]), memory_gib=float(item["memory_gib"]),
            price_monthly_eur=price, price_estimated=price is None, region=item.get("region"),
        ))
    return out


@cache
def leaseweb_types() -> tuple[tuple[LswType, ...], str]:
    """Real catalog from data/leaseweb_catalog.json if a token fetched it, else built from the provider schema."""
    if CATALOG.exists():
        data = json.loads(CATALOG.read_text())
        types = _api_types(data)
        if types:
            return tuple(types), f"catalog:{data.get('source', 'api')}:{data.get('fetched_at', '?')}"
    return tuple(_fallback_types()), "fallback:provider-schema+estimated-prices"


@cache
def aws_types() -> dict:
    return json.loads(AWS_TYPES.read_text())


@cache
def regions() -> dict:
    return yaml.safe_load(REGIONS.read_text())


@cache
def images() -> dict:
    return yaml.safe_load(IMAGES.read_text())
