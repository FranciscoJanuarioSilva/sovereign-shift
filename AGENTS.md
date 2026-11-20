# AGENTS.md

Guide for AI coding agents and humans working on sovereign-shift. Read `PLAN.md` first.

## What this is
sovereign-shift scans a "ClickOps" AWS account (built in the console, no IaC) with read-only credentials. It rebuilds the dependency graph, translates to Leaseweb, and writes:
- Leaseweb Terraform,
- a graph,
- an AI-personalised data migration runbook,
- one HTML report with cost, manual work and security findings.

Built for a 5-hour hackathon build. Scope and priorities are in `PLAN.md`.

## Read before working
- `PLAN.md`: scope, pipeline, runbook design, AI use, timeline.
- `docs/contracts.md`: JSON shapes for `inventory.json`, `graph.json`, `mapping.json`, `runbook.json`. Keep them stable.
- `docs/research/README.md`: index of facts about AWS and Leaseweb. Check it before guessing.
- `docs/schemas/*.json`: exact provider schemas. Never emit an attribute that isn't in them.

## Layout
```
sovereign_shift/
  scanner/      # boto3 describe/list calls -> inventory
  graph/        # relationships from IDs (networkx)
  translator/   # rules from mappings/, then AI for unmappable resources
  generator/    # Jinja2 templates -> Terraform, nftables cloud-init
  runbook/      # template library + runbook agent + validator
  ai/           # OpenAI-compatible client, redaction, agent prompts
  report/       # static HTML report
  cli.py        # typer
  prompts/      # plain-text prompt files, one per agent
mappings/       # YAML: instance types, regions, services, security rules
runbook/templates/  # YAML: allowed runbook steps per resource type
docs/           # research, contracts, schemas
scripts/        # fetch-corpus.sh, extract_schemas.py
testdata/       # fixture inventory and golden outputs
examples/       # sample_inventory.json for offline demo
corpus/         # reference repos, gitignored
```

## Stack
Python 3.11+, boto3, pydantic, networkx, typer, jinja2, openai SDK (custom `base_url`), pytest, moto. No Textual, no FastAPI in the MVP.

## Commands
```bash
./scripts/fetch-corpus.sh                       # reference repos (optional)
pytest
sovereign-shift scan --profile readonly --region eu-west-1
sovereign-shift all --from-snapshot examples/sample_inventory.json --no-ai --out out/
```
Terraform isn't installed on this machine. Run it through the container:
`podman run --rm -v "$PWD/out/terraform":/w:Z -w /w docker.io/hashicorp/terraform:1.9.8 validate`

## Rules
- **Deterministic first.** Rules and templates produce the Terraform, the firewall config and the cost table. AI only handles resources with no Leaseweb equivalent, the runbook personalisation, and summaries.
- **AI never writes HCL or firewall rules.** It returns JSON, validated with pydantic. The generator writes the files.
- **Runbook commands come only from `runbook/templates/`.** The runbook agent may choose steps, order them, fill placeholders and add notes. It may not write commands. The validator rejects any step id not in the library, any command that differs from its template, and any placeholder it can't source.
- **AI can claim a capability only when a template exists.** Resources without a template go to the manual section, with prose only.
- **Every AI output is marked** `ai-suggested` in the generated files and report, with its justification.
- **Everything generated must pass `terraform validate`.** Nothing is silently dropped. Anything unmapped goes into the report.
- **`--no-ai` must always work**, offline, from a snapshot.
- **AWS access is read-only.** Never write to the customer's account. Never store or log credentials.
- **No secrets to the LLM.** Redact keys, passwords, tokens, `user_data` secrets and account IDs before every call. Runbooks show `<CUSTOMER: ...>` placeholders, never values.
- **Default AI endpoint:** OpenRouter EU (`https://eu.openrouter.ai/api/v1`). Keep the base URL configurable.
- **Region trap:** Leaseweb `eu-west-3` is Amsterdam, AWS `eu-west-3` is Paris. Always map through `mappings/regions.yaml`.
- **Elastic IPs are manual.** `leaseweb_public_cloud_ip` doesn't reserve addresses.
- **Facts in docs need a source URL and a date.** Mark unverified things "verify".

## Code style
- Type hints, small functions, no agent-orchestration framework.
- Comments: short and casual, lowercase is fine, one sentence per line, never split a sentence across lines. No markdown emphasis in comments.

## Git
- Plain commit messages. No `Co-Authored-By` trailers, and no mention of Anthropic or Claude in commits or PRs.
- Don't commit `corpus/`, `out/`, `*.tfvars`, `*.tfstate*`, real `raw.json` or `inventory.json`, or `.env`.
- License: pending. See the open question in `PLAN.md`.
