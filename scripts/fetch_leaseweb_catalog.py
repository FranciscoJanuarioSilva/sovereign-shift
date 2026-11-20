#!/usr/bin/env python3
"""Snapshot the Leaseweb Public Cloud catalog (regions, instance types, prices) into data/leaseweb_catalog.json.

Maintainers run this with a Leaseweb API token and commit the result.
End users never need a token: the translator reads the committed snapshot.

    LEASEWEB_TOKEN=... python scripts/fetch_leaseweb_catalog.py
    python scripts/fetch_leaseweb_catalog.py --region eu-west-3 --out /tmp/catalog.json
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, UTC
from pathlib import Path

import httpx

from sovereign_shift.ai.client import load_env

API = "https://api.leaseweb.com/publicCloud/v1"
PAGE = 50
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "data" / "leaseweb_catalog.json"
NOTE = (
    "Prices as the Leaseweb Public Cloud API returned them for the account that owns the token, no taxes. "
    "Each region is billed in its own currency: only EUR regions fill price_*_eur. "
    "A customer with a contract can point SOVEREIGN_LEASEWEB_CATALOG at their own copy."
)


def get(client: httpx.Client, path: str, **params: object) -> dict:
    # small retry for rate limits and 5xx, anything else is a real error
    for attempt in range(4):
        response = client.get(f"{API}{path}", params=params)
        if response.status_code == 429 or response.status_code >= 500:
            time.sleep(1.5 * (attempt + 1))
            continue
        if response.status_code == 401:
            sys.exit("Leaseweb rejected the token (HTTP 401). Check LEASEWEB_TOKEN.")
        response.raise_for_status()
        return response.json()
    response.raise_for_status()
    return {}


def paged(client: httpx.Client, path: str, key: str, **params: object) -> tuple[list[dict], dict]:
    items: list[dict] = []
    meta: dict = {}
    offset = 0
    while True:
        data = get(client, path, limit=PAGE, offset=offset, **params)
        meta = data.get("_metadata", {})
        batch = data.get(key, [])
        items += batch
        offset += PAGE
        if not batch or offset >= meta.get("totalCount", 0):
            return items, meta


def convert(region: str, currency: str, item: dict) -> dict:
    res, prices = item["resources"], item["prices"]
    hourly = float(prices["hourly"]) if prices.get("hourly") else None
    monthly = float(prices["monthly"]) if prices.get("monthly") else None
    is_eur = currency == "EUR"
    return {
        "name": item["name"],
        "region": region,
        "vcpu": int(res["cpu"]["value"]),
        "memory_gib": float(res["memory"]["value"]),
        "gpu": int(res.get("gpu", {}).get("value", 0)),
        "currency": currency,
        "price_hourly_local": hourly,
        "price_monthly_local": monthly,
        # the report compares in EUR, so a GBP or JPY price is never copied into the EUR fields
        "price_hourly_eur": hourly if is_eur else None,
        "price_monthly_eur": monthly if is_eur else None,
        "storage_types": [s.lower() for s in item.get("storageTypes", [])],
        "min_disk_gib": item.get("minDiskSize"),
    }


def write(path: Path, header: dict, rows: list[dict]) -> None:
    # one instance type per line, so a price change shows up as a small diff
    lines = [json.dumps(row, separators=(", ", ": ")) for row in rows]
    body = json.dumps(header, indent=2)[:-2]  # drop the closing brace, we append the list ourselves
    text = body + ',\n  "instance_types": [\n    ' + ",\n    ".join(lines) + "\n  ]\n}\n"
    json.loads(text)  # never write a file we can't read back
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--region", action="append", help="only these regions (default: all)")
    args = parser.parse_args()

    load_env()
    token = os.environ.get("LEASEWEB_TOKEN")
    if not token:
        sys.exit("LEASEWEB_TOKEN is not set. Export it or put it in .env (never commit it).")

    with httpx.Client(headers={"X-LSW-Auth": token}, timeout=30) as client:
        regions, _ = paged(client, "/regions", "regions")
        wanted = [r for r in regions if not args.region or r["name"] in args.region]
        if not wanted:
            sys.exit(f"No matching region. The API has: {', '.join(r['name'] for r in regions)}")
        rows: list[dict] = []
        for region in sorted(wanted, key=lambda r: r["name"]):
            # a failed region aborts before anything is written, so a half snapshot never replaces a good one
            items, meta = paged(client, "/instanceTypes", "instanceTypes", region=region["name"])
            region["currency"] = meta.get("currency")
            if not region["currency"]:
                sys.exit(f"{region['name']}: the API gave no currency, not writing.")
            rows += [convert(region["name"], region["currency"], i) for i in items]
            print(f"{region['name']:15} {region['location']:14} {region['currency']}  {len(items):3} instance types")

    header = {
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": "api",
        "note": NOTE,
        "regions": [
            {"code": r["name"], "location": r["location"], "currency": r["currency"],
             "storage_types": [s.lower() for s in r.get("storageTypes", [])]}
            for r in sorted(wanted, key=lambda r: r["name"])
        ],
    }
    write(args.out, header, rows)
    print(f"Wrote {len(rows)} instance types for {len(wanted)} regions to {args.out}")


if __name__ == "__main__":
    main()
