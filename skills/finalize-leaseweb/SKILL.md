---
name: finalize-leaseweb
description: Runs the Leaseweb API calls Terraform can't make after apply, creating security groups, adding firewall rules, attaching groups and registering load balancer targets. Use it before running or changing finalize, always with a dry run first.
---

# Finalize on Leaseweb

Part of: sovereign-shift. Code: `sovereign_shift/finalize/apply.py`. Facts: `docs/research/leaseweb-api.md`.

## Steps
1. `terraform apply` the generated folder (creates billed resources), then `terraform output -json > outputs.json`.
2. Dry run, no network: `sovereign-shift finalize --out out/x --outputs outputs.json --dry-run --admin-cidr <your ip>/32`.
3. Live: export `LEASEWEB_TOKEN` (finalize doesn't read `.env`), run without `--dry-run`.

## Rules
- Only creates and adds: it never deletes or changes existing rules. Safe to re-run, it only adds what's missing.
- Refuses to run live without `--admin-cidr`, refuses `0.0.0.0/0` as a restricted source, stops on ambiguous or default group names.

## Pitfalls
- Leaseweb's default security group allows everything. Whether it can be detached is unverified: check the effective rules after finalize.
- `terraform destroy` doesn't remove the groups finalize created. Delete them through the API after a test.
