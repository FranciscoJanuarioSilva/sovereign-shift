# sovereign-shift

**From a ClickOps AWS account to a Leaseweb migration plan.**

Infrastructure built by clicking in the AWS console is hard to move: nobody has the full picture of what exists or how it connects. Existing tools turn that into *AWS* Terraform, which keeps you on AWS. sovereign-shift reads the account with read-only credentials and produces what a team needs to move it to Leaseweb, a European provider:

- **Leaseweb Terraform** (`leaseweb/leaseweb` provider), plus the Leaseweb API calls the provider can't make yet (security groups, load balancer targets),
- a **dependency graph**, including links nobody wrote down (which servers can reach the database),
- **security findings** (SSH or database open to the internet, public buckets, unencrypted disks), the network ones fixed by the generated setup,
- a **data migration runbook** (pg_dump, rclone, rsync) personalised by AI, with commands that only come from vetted templates,
- a **report** (Markdown + JSON) with the monthly cost on both sides, and what migrates automatically and what doesn't.

AWS is the main source. Cloudflare Workers accounts are supported too, and Google Cloud projects and Azure subscriptions map to the same pipeline (tested with mocked APIs only, see [docs/gcp.md](docs/gcp.md) and [docs/azure.md](docs/azure.md)).

## How it works

```
AWS account (read-only)
  -> scan       inventory.json        boto3 describe/list calls only
  -> graph      graph.json, findings  relationships + security checks
  -> translate  mapping.json          rules first, AI for what rules can't map
  -> generate   terraform/, finalize  Jinja2 templates, validated with terraform validate
  -> runbook    runbook.json          AI picks and fills steps from templates/
  -> report     report.md, .json      cost, work list, findings, runbook
  -> finalize   (after apply)         Leaseweb API: security groups, LB targets
```

Every step reads the previous step's JSON ([contracts](docs/contracts.md)), so any step can be rerun on its own.

AI (Mistral, through OpenRouter pinned to Mistral with data collection denied) never writes Terraform, firewall rules or shell commands. It returns JSON that is validated, and every AI suggestion is marked in the output. `--no-ai` runs everything offline.

## Quick start

Python 3.11 or later. Terraform is only needed to validate or apply the output.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'

# offline, from our demo AWS account (identifiers replaced)
sovereign-shift all --from-snapshot examples/aws_demo_inventory.json --no-ai --out out/demo

# check the generated Terraform (validate needs no Leaseweb token)
terraform -chdir=out/demo/terraform init && terraform -chdir=out/demo/terraform validate
```

Open `out/demo/report.md` and `out/demo/graph.html`, or browse the same assessment in the local dashboard:

```bash
.venv/bin/python frontend/serve.py --port 8001   # then open http://127.0.0.1:8001
```

On a real account, use read-only credentials ([IAM policy](docs/iam-policy.json)) and copy `.env.example` to `.env` for the AI settings:

```bash
sovereign-shift all --profile <read-only-profile> --region eu-north-1 --out out/live
```

Share only `out/live/public/`, where the account id is masked. Every command and option: [docs/usage.md](docs/usage.md).

## Repository structure

| Path | What |
|---|---|
| `sovereign_shift/scanner/` | read-only AWS and Cloudflare scanners |
| `sovereign_shift/graph/` | dependency graph, inferred links, security checks |
| `sovereign_shift/translator/` | AWS -> Leaseweb rules, instance sizing, prices |
| `sovereign_shift/generator/` | Terraform and cloud-init templates, `finalize.json` |
| `sovereign_shift/finalize/` | Leaseweb API calls after `terraform apply` |
| `sovereign_shift/runbook/`, `runbook/templates/` | data migration steps and their allowed commands |
| `sovereign_shift/report/` | report and AI summary |
| `sovereign_shift/ai/`, `sovereign_shift/prompts/` | LLM client, redaction, prompts |
| `frontend/` | local dashboard: upload an inventory or report, browse and validate the Terraform |
| `data/`, `mappings/` | Leaseweb catalog and prices, AWS instance types, region and image maps |
| `examples/`, `testdata/` | demo account inventory, Cloudflare demo, synthetic fixtures |
| `docs/` | [usage](docs/usage.md), [contracts](docs/contracts.md), [research](docs/research/README.md) with sources, [plan](PLAN.md) |
| `tests/` | `pytest` |

## Limits

- Terraform rebuilds infrastructure, not data. Disks, buckets and databases move with the runbook.
- Leaseweb has no managed database: RDS becomes PostgreSQL or MySQL on its own instance.
- The cost total covers compute only. Storage, traffic, public IPs and load balancers aren't priced yet.
- `terraform apply` and live `finalize` haven't been run against Leaseweb yet. `validate` and `plan` pass.

## License

[Apache-2.0](LICENSE).
