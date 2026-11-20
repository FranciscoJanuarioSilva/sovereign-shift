#!/usr/bin/env python3
"""Fill data/aws_instance_types.json "regional" with real Azure VM prices from the public Azure Retail Prices API.

No key needed. Linux, pay-as-you-go (no spot, low priority or Windows), USD per hour.
The translator reads the regional block for any source cloud, keyed by that cloud's region name.

    python scripts/fetch_azure_prices.py --inventory testdata/azure_inventory.json
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import httpx

DATA = Path(__file__).resolve().parents[1] / "data" / "aws_instance_types.json"
API = "https://prices.azure.com/api/retail/prices"


def vm_price(region: str, size: str) -> float | None:
    query = (f"serviceName eq 'Virtual Machines' and armRegionName eq '{region}' "
             f"and armSkuName eq '{size}' and priceType eq 'Consumption'")
    items = httpx.get(API, params={"$filter": query}, timeout=30).json().get("Items", [])
    linux = [i for i in items if "Windows" not in i["productName"]
             and not re.search(r"Spot|Low Priority", i["skuName"]) and i["unitOfMeasure"] == "1 Hour"]
    return min((i["retailPrice"] for i in linux), default=None)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--inventory", nargs="+", type=Path, required=True)
    args = parser.parse_args()
    wanted: set[tuple[str, str]] = set()
    for path in args.inventory:
        inv = json.loads(path.read_text())
        if inv.get("source") != "azure":
            continue
        for r in inv["resources"]:
            if r["type"] == "ec2_instance":
                wanted.add((r["region"], r["properties"]["instance_type"]))
    data = json.loads(DATA.read_text())
    found = 0
    for region, size in sorted(wanted):
        usd = vm_price(region, size)
        print(f"{region:15} {size:18} {usd}")
        if usd:
            data.setdefault("regional", {}).setdefault(region, {})[size] = usd
            found += 1
    if not found:
        sys.exit("No prices found, not writing.")
    data["regional_azure_source"] = f"Azure Retail Prices API, Linux pay-as-you-go, USD per hour, fetched {date.today()}"
    text = json.dumps(data, indent=2)
    text = re.sub(r"\[\s+([^\[\]]+?)\s+\]", lambda m: "[" + ", ".join(x.strip() for x in m.group(1).split(",")) + "]", text)
    DATA.write_text(text + "\n")
    print(f"Wrote {found} Azure prices to {DATA}")


if __name__ == "__main__":
    main()
