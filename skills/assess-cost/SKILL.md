---
name: assess-cost
description: Explains and maintains the monthly compute cost comparison, with real list prices on both sides, how to refresh them and what is excluded. Use it when touching prices, the cost table or cost claims in the pitch.
---

# Assess cost

Part of: sovereign-shift. Code: `sovereign_shift/translator/catalog.py`, `sovereign_shift/translator/rules.py` (`aws_specs`, `aws_monthly_eur`), report: `sovereign_shift/report/build.py`. Worked numbers: `docs/cost-assessment.md`.

## Sources
- Leaseweb: `data/leaseweb_catalog.json`, a committed snapshot of the Public Cloud API (refresh: `LEASEWEB_TOKEN=... python scripts/fetch_leaseweb_catalog.py`). A customer can supply their own file with `SOVEREIGN_LEASEWEB_CATALOG`.
- AWS: `data/aws_instance_types.json`. The `regional` block holds real on-demand prices per region (refresh: `python scripts/fetch_aws_prices.py --profile sovereign-readonly --region <r> --inventory <inventory.json>`). Types without a regional price use approximate us-east-1 prices and are starred.

## Rules
- Compute only (servers and databases). Storage, traffic, public IPs, load balancers, taxes and discounts are excluded, and the report says so.
- Only EUR regions get a Leaseweb price. Other currencies show "unknown", never a converted guess.
- USD is converted at 0.92 and 730 hours per month.
- Tiny AWS instances map to a bigger Leaseweb type (smallest is 2 vCPU), so they are flagged over-provisioned and the comparison is on capacity.

## Pitfalls
- Never present the live demo account (free-tier micro sizes) as a saving. Use the sample store for the headline.
- Traffic is where Leaseweb wins (1 TB included), but it isn't in the totals. Quote it separately, with sources.
