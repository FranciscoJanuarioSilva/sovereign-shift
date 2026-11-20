---
name: sovereign-shift
description: Root skill for the sovereign-shift repo, which scans a ClickOps AWS (or Azure/Cloudflare) account read-only and produces Leaseweb Terraform, a migration runbook and a scored report. Use it before any other skill here.
---

# sovereign-shift

Children: scan-aws, scan-azure, translate-leaseweb, assess-security-posture, assess-risk, assess-performance, assess-scaling, assess-cost, generate-terraform, finalize-leaseweb, runbook, report.

## Pipeline
`scan -> graph (+ findings) -> translate -> generate -> assess -> runbook -> report -> publish`, each step reads the previous step's JSON in the output folder. `sovereign-shift all` runs them in order. Contracts: `docs/contracts.md`.

```bash
sovereign-shift all --from-snapshot testdata/clickops_inventory.json --no-ai --out out/store   # offline, no keys
sovereign-shift all --profile sovereign-readonly --region eu-north-1 --out out/live            # live AWS, read-only
pytest
```

## Rules every skill inherits
- Deterministic first: scores, prices, sizes, Terraform and firewall rules come from code and data files. AI only writes narrative or picks from allowed options, and its output is validated JSON marked `ai-suggested`.
- `--no-ai` must always produce a complete result.
- Cloud access is read-only. Never write to a customer's account.
- No secrets in files, prompts or logs. Redact before any AI call (`sovereign_shift/ai/redact.py`).
- No evidence, no claim: say "not assessed" instead of guessing.
- Leaseweb region codes look like AWS ones but are other places (`eu-west-3` is Amsterdam). Always map through `mappings/regions.yaml`.
- Facts live in `docs/research/`. Check them before stating anything about Leaseweb.
- Plain commit messages, no co-author or AI attribution lines.

## Pitfalls
- The provider has no security group, block volume, object storage or DB resources: those go through finalize, the runbook or the report.
- `ssh_key` and `user_data` can't both be set on an instance.
- Many newer Leaseweb types are local-NVMe only, so `root_disk_storage_type` must follow the type.
