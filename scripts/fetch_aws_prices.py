#!/usr/bin/env python3
"""Fill data/aws_instance_types.json with real on-demand prices for one AWS region, from the AWS Pricing API.

Read-only (pricing:GetProducts is part of ReadOnlyAccess). The translator prefers these regional prices
over its approximate us-east-1 table.

    python scripts/fetch_aws_prices.py --profile sovereign-readonly --region eu-north-1 \
        --inventory out/live/inventory.json testdata/clickops_inventory.json
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import boto3

DATA = Path(__file__).resolve().parents[1] / "data" / "aws_instance_types.json"
# the pricing api wants these names, not region codes
LOCATIONS = {
    "eu-north-1": "EU (Stockholm)", "eu-west-1": "EU (Ireland)", "eu-west-2": "EU (London)",
    "eu-west-3": "EU (Paris)", "eu-central-1": "EU (Frankfurt)", "eu-south-1": "EU (Milan)",
    "us-east-1": "US East (N. Virginia)", "us-east-2": "US East (Ohio)", "us-west-2": "US West (Oregon)",
    "ca-central-1": "Canada (Central)", "ap-southeast-1": "Asia Pacific (Singapore)",
}
ENGINES = {"postgres": "PostgreSQL", "aurora-postgresql": "PostgreSQL", "mysql": "MySQL", "mariadb": "MariaDB"}


def wanted(paths: list[Path], region: str) -> tuple[set[str], dict[str, str]]:
    ec2: set[str] = set()
    rds: dict[str, str] = {}
    for path in paths:
        for r in json.loads(path.read_text())["resources"]:
            if r.get("region") not in (region, None):
                continue
            p = r.get("properties", {})
            if r["type"] == "ec2_instance" and p.get("instance_type"):
                ec2.add(p["instance_type"])
            if r["type"] == "db_instance" and p.get("instance_class"):
                rds[p["instance_class"]] = ENGINES.get(str(p.get("engine", "")).lower(), "PostgreSQL")
    return ec2, rds


def hourly_usd(pricing, service: str, filters: dict) -> float | None:
    response = pricing.get_products(
        ServiceCode=service, MaxResults=10,
        Filters=[{"Type": "TERM_MATCH", "Field": k, "Value": v} for k, v in filters.items()],
    )
    for raw in response["PriceList"]:
        for term in json.loads(raw)["terms"].get("OnDemand", {}).values():
            for dim in term["priceDimensions"].values():
                if float(dim["pricePerUnit"]["USD"]) > 0:
                    return float(dim["pricePerUnit"]["USD"])
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--profile")
    parser.add_argument("--region", required=True)
    parser.add_argument("--inventory", nargs="+", type=Path, required=True)
    args = parser.parse_args()
    if args.region not in LOCATIONS:
        sys.exit(f"Add {args.region} to LOCATIONS first (the Pricing API needs its display name).")

    ec2_types, rds_classes = wanted(args.inventory, args.region)
    # pricing endpoint only lives in us-east-1, whatever region we price
    pricing = boto3.Session(profile_name=args.profile).client("pricing", region_name="us-east-1")
    location = LOCATIONS[args.region]
    prices: dict[str, float] = {}
    for t in sorted(ec2_types):
        usd = hourly_usd(pricing, "AmazonEC2", dict(
            location=location, instanceType=t, operatingSystem="Linux", tenancy="Shared",
            preInstalledSw="NA", capacitystatus="Used"))
        print(f"{t:18} {usd}")
        if usd:
            prices[t] = usd
    for c, engine in sorted(rds_classes.items()):
        usd = hourly_usd(pricing, "AmazonRDS", dict(
            location=location, instanceType=c, databaseEngine=engine, deploymentOption="Single-AZ"))
        print(f"{c:18} {usd}  ({engine}, single-az)")
        if usd:
            prices[c] = usd
    if not prices:
        sys.exit("No prices found, not writing.")

    data = json.loads(DATA.read_text())
    block = data.setdefault("regional", {}).setdefault(args.region, {})
    block.update(prices)
    data["regional_source"] = f"AWS Pricing API on-demand, USD per hour, Linux/shared and RDS single-AZ, fetched {date.today()}"
    # keep the one-triple-per-line look of the file
    text = json.dumps(data, indent=2)
    import re
    text = re.sub(r"\[\s+([^\[\]]+?)\s+\]", lambda m: "[" + ", ".join(x.strip() for x in m.group(1).split(",")) + "]", text)
    DATA.write_text(text + "\n")
    print(f"Wrote {len(prices)} prices for {args.region} to {DATA}")


if __name__ == "__main__":
    main()
