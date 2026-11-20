---
name: translate-leaseweb
description: Maps every inventory resource to a Leaseweb target (type, region, image, disk kind, prices, firewall rules) and writes mapping.json, with AI only for services Leaseweb has no equivalent for. Use it when changing how anything maps to Leaseweb.
---

# Translate to Leaseweb

Part of: sovereign-shift. Code: `sovereign_shift/translator/`. Handover: `docs/translator.md`. Table: `docs/research/service-equivalence.md`.

## Rules
- One entry per resource, nothing silently dropped. Status `auto | partial | manual | unsupported`, `via terraform | finalize | runbook | report`.
- Sizing: smallest Leaseweb type with at least the same vCPU and RAM, same family where possible, newest generation. Databases prefer types with central storage.
- `root_disk_storage_type` must be a kind the chosen type supports (many newer types are local-NVMe only).
- Regions through `mappings/regions.yaml`, only to regions the provider accepts.
- Security group rules: 22/3389 from the internet become `var:admin_cidr`, database ports from the internet become the app servers' private IPs. Write "(fixes SG-001)" style markers in the notes, they become the entry's `fixes`.
- AI: only for `unsupported` resources, JSON validated, redacted input, marked `ai-suggested`.

## Pitfalls
- Elastic IPs are manual: Leaseweb can't reserve an IP.
- Object storage isn't in the provider (reverted in 1.32.1): buckets go to the runbook.
