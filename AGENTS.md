# AGENTS.md

Guide for AI coding agents and humans working on sovereign-shift. Read `PLAN.md` first.

## What this is
sovereign-shift scans a "ClickOps" AWS account (built in the console, no IaC) with read-only credentials. It rebuilds the dependency graph, translates to Leaseweb, and writes:
- Leaseweb Terraform,
- `finalize.json`: Leaseweb API calls Terraform can't make (security groups, LB targets), run by `sovereign-shift finalize` after `terraform apply`,
- a graph,
- an AI-personalised data migration runbook,
- a report (`report.md` + `report.json`) with cost, manual work and security findings.

Built for a 5-hour hackathon build. Scope and priorities are in `PLAN.md`.

## Read before working
- `PLAN.md`: scope, pipeline, runbook design, AI use, timeline.
- `docs/contracts.md`: JSON shapes for every file between steps. Keep them stable.
- `docs/research/README.md`: index of facts about AWS and Leaseweb. Check it before guessing.
- `docs/research/environment.md`: our AWS account, AI setup and team VM.
- `docs/schemas/*.json`: exact provider schemas. Never emit an attribute that isn't in them.

## Layout
```
sovereign_shift/
  scanner/      # boto3 describe/list calls -> inventory
  graph/        # relationships from IDs (networkx) + security checks
  translator/   # rules from mappings/, then AI for unmappable resources
  generator/    # Jinja2 templates -> Terraform + cloud-init, and finalize.json
  finalize/     # Leaseweb REST API calls after terraform apply (SGs, LB targets)
  runbook/      # renders commands from templates + validator
  ai/           # OpenAI-compatible client, redaction, agent prompts
  report/       # report.json + report.md (Mermaid graph)
  cli.py        # typer
  prompts/      # plain-text prompt files, one per agent
mappings/       # YAML: instance types, regions, services, security rules
data/           # leaseweb_catalog.json (committed API snapshot, refresh with scripts/fetch_leaseweb_catalog.py), aws_instance_types.json
runbook/templates/  # YAML: allowed runbook steps per resource type
docs/           # research, contracts, schemas
scripts/        # fetch-corpus.sh, extract_schemas.py
testdata/       # synthetic fixtures: inventories, mappings, small catalog (tests and the pitch demo)
examples/       # aws_demo_inventory.json (our real demo account, identifiers replaced), cloudflare-worker/
corpus/         # reference repos, gitignored
```

## Stack
Python 3.11+, boto3, pydantic, networkx, typer, jinja2, openai SDK (custom `base_url`), httpx (Leaseweb API), pytest, moto. No Textual, no FastAPI in the MVP.

## Commands
```bash
./scripts/fetch-corpus.sh                       # reference repos (optional)
pytest
sovereign-shift scan --profile sovereign-readonly --region eu-north-1
sovereign-shift all --from-snapshot examples/aws_demo_inventory.json --no-ai --out out/demo
sovereign-shift finalize --out out/ --dry-run      # after terraform apply; drop --dry-run to call the API
```
Terraform isn't installed on this machine. Run it through the container:
`podman run --rm -v "$PWD/out/terraform":/w:Z -w /w docker.io/hashicorp/terraform:1.9.8 validate`

## Rules
- **Deterministic first.** Rules and templates produce the Terraform, the firewall config and the cost table. AI only handles resources with no Leaseweb equivalent, the runbook personalisation, and summaries.
- **AI never writes HCL, firewall rules or commands.** It returns JSON, validated with pydantic. Our code writes the files.
- **Runbook commands come only from `runbook/templates/`.** The runbook agent returns step ids, their order, input values and notes. Our code renders the commands from the templates. The validator rejects any step id not in the library and any input that isn't from inventory or marked `<CUSTOMER: ...>`.
- **AI can claim a capability only when a template exists.** Resources without a template go to the manual section, with prose only.
- **Every AI output is marked** `ai-suggested` in the generated files and report, with its justification.
- **Everything generated must pass `terraform validate`.** Nothing is silently dropped. Anything unmapped goes into the report.
- **`--no-ai` must always work**, offline, from a snapshot.
- **AWS access is read-only.** Never write to the customer's account. Never store or log credentials. The demo account's SCP only allows `eu-north-1`: treat `UnauthorizedOperation`/`AccessDenied` per region or service as "denied", record it and continue.
- **Product code only uses the `sovereign-readonly` profile.** The write profile `sovereign-admin` is only for `scripts/demo-account/`, which builds and tears down our test fixture account.
- **Secrets stay out of the repo.** Keys only in `~/.aws/` and `.env`. Install the hook: `ln -sf ../../scripts/check-secrets.sh .git/hooks/pre-commit`. Never paste credentials into docs, tests, fixtures or commit messages.
- **No secrets to the LLM.** Redact keys, passwords, tokens, `user_data` contents, account IDs and host IPs before every call. Keep CIDRs in security group rules (the reviewer needs `0.0.0.0/0`). Runbooks show `<CUSTOMER: ...>` placeholders, never values.
- **AI endpoint:** OpenAI-compatible, base URL, key and model from env vars (`.env`, see `.env.example`). Default is OpenRouter global with provider routing pinned to Mistral (`only: ["mistral"]`, `allow_fallbacks: false`, `data_collection: "deny"`). `eu.openrouter.ai` returns 403 on our plan.
- **Region trap:** Leaseweb `eu-west-3` is Amsterdam, AWS `eu-west-3` is Paris. Always map through `mappings/regions.yaml`.
- **Elastic IPs are manual.** `leaseweb_public_cloud_ip` doesn't reserve addresses.
- **Security groups and LB targets go through finalize**, never Terraform (the provider has no resources for them). Leaseweb firewall rules only take CIDRs, so SG-to-SG rules become /32 rules on the source instances' private IPs, resolved after apply. See `docs/research/leaseweb-api.md`.
- **`user_data` is plain text**, not base64. It always brings up the private network interface with DHCP, matched by "not the primary interface", never by name (`eth1` on the old platform, `enp3s0` on the new one) and carries the SSH key, since `ssh_key` and `user_data` can't both be set.
- **LB backends need `has_private_network = true`**, or they can't be registered as targets.
- **Facts in docs need a source URL and a date.** Mark unverified things "verify".

## Code style
- Type hints, small functions, no agent-orchestration framework.
- Comments: short and casual, lowercase is fine, one sentence per line, never split a sentence across lines. No markdown emphasis in comments.

## Git
- Plain commit messages. No `Co-Authored-By` trailers, and no mention of Anthropic or Claude in commits or PRs.
- Don't commit `corpus/`, `out/`, `*.tfvars`, `*.tfstate*`, real `raw.json` or `inventory.json`, or `.env`.
- License: Apache-2.0.
