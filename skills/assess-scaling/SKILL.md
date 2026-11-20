---
name: assess-scaling
description: Explains how the migrated setup scales on Leaseweb, with tiers, single points of failure, the next size up with its real price, a scale-out recipe and the platform limits. Use it to compute, change or explain the "Scaling" section.
---

# Assess scaling

Part of: sovereign-shift. Code: `sovereign_shift/assess/scaling.py`. Facts: `docs/research/leaseweb-terraform.md`, `docs/research/leaseweb-platform.md`.

## Inputs
`mapping.json` (target groups with members, instance types, disk sizes), the Leaseweb catalog for sizes and prices.

## Rules
- Tiers: each target group is a "web behind load balancer" tier. It scales out when it has 2 or more servers. Each database is a database tier (vertical only). Servers outside any target group are standalone.
- Single points of failure: a tier with one server, every database, any root disk above 70% of the 1000 GB maximum.
- Scale up: the next bigger type in the same family and generation from the catalog, with the extra EUR per month, and the largest size available.
- Scale out recipe: stateless servers, raise the instance count in Terraform, apply, re-run finalize to register the new servers.
- Limits: root disk at most 1000 GB, no block volumes, private network /27 by default (about 30 hosts), no auto scaling in the provider, load balancer backends in one zone, no managed database.

## Output
`assessment.json` -> `scaling`: `tiers`, `single_points_of_failure`, `scale_up`, `scale_out`, `limits`.

## Pitfalls
- Prices for the next size come from the catalog. If the region is billed in another currency the delta is unknown, don't convert.
