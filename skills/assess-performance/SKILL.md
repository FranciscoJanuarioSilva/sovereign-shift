---
name: assess-performance
description: Compares capacity before and after the move and lists the platform differences that change performance (burstable CPU, ARM to x86, shared vCPU, disk kinds, region move). Use it to compute, change or explain the "Performance" section.
---

# Assess performance

Part of: sovereign-shift. Code: `sovereign_shift/assess/performance.py`. Facts: `docs/research/leaseweb-platform.md`, `docs/research/leaseweb-api.md`.

## Inputs
`inventory.json` (types, vCPU, RAM, volume IOPS), `mapping.json` (chosen Leaseweb type and disk kind), the Leaseweb catalog (`data/leaseweb_catalog.json`).

## Rules
- One row per server and database: AWS type and capacity next to the Leaseweb type and capacity.
- Notes per row, each with a severity:
  - AWS `t*` types: burstable credits become steady vCPU (info).
  - Graviton (ARM) to x86: re-run benchmarks after the rebuild (warning).
  - Leaseweb generations other than 7a have shared vCPU (info).
  - Disk `LOCAL`: local NVMe, fast, not replicated. `CENTRAL`: replicated, Value tier 8K IOPS, Performance tier 30K. Warn when the AWS volume had more than 8000 IOPS.
  - Over-provisioned: more capacity than today.
- General: the region move changes network paths, so measure latency before cutover. Never quote latency numbers we didn't measure. Load balancers balance within one zone and have no path or host routing.

## Not assessed
Real utilisation (CPU, memory, network over time) isn't scanned, so sizing matches capacity, not load. Say so in the report.

## Output
`assessment.json` -> `performance`: `rows`, `general`, `not_assessed`.
