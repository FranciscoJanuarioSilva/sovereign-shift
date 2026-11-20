# PLAN.md: sovereign-shift

Hackathon Portugal 2026 (Leaseweb + Velv), Lisbon, 20 Nov 2026. Theme: "InfraHack: AI for Cloud Infrastructure". Feature freeze 15:00, pitches from 15:45, 5 minutes max.

## Why
Leaseweb told us customers with Terraform are easy to migrate. Customers who built AWS by clicking in the console ("ClickOps") are hard to migrate, because nobody has a full picture of what exists or how it connects.

Pitch: "Existing tools turn your ClickOps into AWS Terraform. That keeps you on AWS. We turn it into Leaseweb Terraform."

Business case for Leaseweb: a free self-service assessment turns hard-to-migrate AWS customers into qualified leads with an estimated contract value, and leaves them with infrastructure as code.

## Product
Input: read-only AWS credentials. Output, in one folder:
- `out/terraform/*.tf`: Leaseweb Terraform (provider `leaseweb/leaseweb`).
- `out/graph.json` and `out/graph.html`: dependency graph.
- `out/runbook.md` and `out/runbook.json`: AI-personalised data migration runbook.
- `out/report.html`: the single report page. It holds the graph, cost comparison (AWS vs Leaseweb), automatic vs manual work, security findings, and the runbook.

The source cloud stays pluggable. The IR is provider-neutral, and only the scanner is AWS-specific. Azure and GCP are the roadmap.

## Pipeline
1. **Scan** (`sovereign_shift/scanner/`): own boto3 `describe_*` / `list_*` calls, read-only. Output `inventory.json`.
2. **Graph** (`sovereign_shift/graph/`): resolve relationships from IDs. Output `graph.json` plus a visual.
3. **Translate** (`sovereign_shift/translator/`): rules pick the Leaseweb equivalent where one exists. AI proposes an open-source alternative for the rest. Output `mapping.json`.
4. **Generate** (`sovereign_shift/generator/`): render Terraform from `mapping.json`, with Jinja2 templates. Firewall rules come from a template too (see below). Output `out/terraform/*.tf`.
5. **Runbook** (`sovereign_shift/runbook/`): AI personalises a data migration runbook from the template library. Output `runbook.json` and `runbook.md`.
6. **Report** (`sovereign_shift/report/`): static HTML report. Includes the runbook.

Data contracts (JSON shapes for each file) are in `docs/contracts.md`. Keep them stable: team members build in parallel against them.

## MVP scope
Driven by what the Leaseweb provider can express (v1.32.1, verified in `docs/research/leaseweb-terraform.md`). It has no firewall, security group, private network, Kubernetes or object storage resources.

| AWS | Leaseweb target | Status |
|---|---|---|
| EC2 instance + root EBS | `leaseweb_public_cloud_instance` | auto |
| Security group | no TF resource. Template-generated nftables in `user_data` cloud-init. LLM reviews the rules, does not write them. | auto |
| SSH key pair | inside the cloud-init (`ssh_key` and `user_data` can't both be set) | auto |
| ALB/NLB + listeners + target groups | `leaseweb_public_cloud_load_balancer`, `_listener`, `_target_group` | auto (HTTPS certs manual) |
| Route 53 records | `leaseweb_dns_resource_record_set` (domain must be at Leaseweb) | auto |
| Elastic IP | none. `leaseweb_public_cloud_ip` only sets reverse DNS on an IP the instance already has, it doesn't reserve one. | manual (new IP, DNS update) |
| S3 bucket | Leaseweb Object Storage via S3-compatible endpoint, `rclone` in runbook. Not in Terraform (reverted in provider 1.32.1). | semi-auto |
| RDS | self-hosted Postgres/MySQL on a Leaseweb instance, dump/restore in runbook | manual (AI alternative) |
| Lambda, SQS, DynamoDB, ECS/EKS, others | AI proposes open-source alternative and effort estimate | manual (AI) |

Region trap: Leaseweb `eu-west-3` is Amsterdam, AWS `eu-west-3` is Paris. Map regions through `mappings/regions.yaml`, never copy the string.

## Data migration runbook
Terraform rebuilds infrastructure. It does not move disks, bucket objects or database rows. The runbook covers that gap, and the pitch says so before a judge asks.

**How it's made:**
- `runbook/templates/*.yaml` is a library of allowed steps per resource type. Each step has an id, a command template with named placeholders, the inputs it needs, which inputs the customer supplies, and a verification command.
- The runbook agent gets one mapped resource, the templates for its type, and the target Leaseweb values. It returns JSON: which steps to use, their order, filled placeholders, short notes for this customer, and `not_capable` entries with a reason.
- A validator checks every response. Step ids must exist in the library. Commands must match their template, with no free-form shell. Placeholders must be filled from inventory or marked as customer input `<CUSTOMER: ...>`. Anything that fails is dropped.
- AI can only claim a resource is runbook-capable if a template exists. Everything else goes to the report's manual section with prose only, no commands.
- If the AI fails or is off (`--no-ai`), the template's default steps are used, marked "not personalised".
- Secrets never appear. The runbook shows placeholders, and the customer fills in keys at execution time.
- Output is cached by input hash, so the demo is repeatable.

**First template library (in order):** S3 bucket sync, EBS volume copy, RDS PostgreSQL dump/restore, RDS MySQL dump/restore, EC2 application data copy (rsync), Route 53 cutover (lower TTL, switch record, verify).

## AI use
| Job | Agent | Input | Output | Fallback |
|---|---|---|---|---|
| Alternatives for unmappable services | translator | one resource + neighbours + Leaseweb schema subset | `{alternative, justification, effort, manual_steps, confidence}` | "manual, no suggestion" |
| Personalised runbook | runbook | one resource + its templates + target values | steps by id, placeholders, notes, `not_capable` | template default steps |
| Firewall review | reviewer | generated nftables rules + SG source | `{ok, issues[]}`; issues shown in report | rules still shipped, flagged "unreviewed" |
| Plain-language report summary | explainer | final report JSON | short text, English/Portuguese | no summary |
| Architecture summary | explainer | graph | one paragraph | omitted |

The LLM never writes HCL or firewall rules. Its output is JSON, validated with pydantic. Every AI choice carries a `justification` and an `ai-suggested` mark in the output.

Backend: OpenAI-compatible client with configurable base URL. Default is OpenRouter EU (`https://eu.openrouter.ai/api/v1`), with Ollama or Mistral as alternatives. Details and the open check on our key's plan are in `docs/research/ai-providers.md`.

Redaction before every call: no keys, passwords, tokens, `user_data` secrets or account IDs. The model gets resource metadata only.

## Architecture
Python 3.11+ (per the rules). Packages: boto3, pydantic, networkx, typer, jinja2, openai SDK, pytest, moto. No Textual, no FastAPI in the MVP.

```
scanner (boto3) -> inventory.json -> graph.json
  -> translator (rules, then AI) -> mapping.json
  -> generator (Jinja2 templates) -> out/terraform/*.tf
  -> runbook (AI + template library) -> runbook.json / runbook.md
  -> report (static HTML)
```

- CLI (typer): `sovereign-shift scan|graph|translate|generate|runbook|report|all`. Each step reads the previous JSON file, so the demo can resume at any step.
- `--no-ai` and `--from-snapshot examples/sample_inventory.json` must both work offline.
- Former2 is not a dependency. It's documented in `docs/research/aws-scanning.md` as a reference for what raw data looks like, and it's in `corpus/tools/former2` for reading only.
- Report: one self-contained HTML file. The graph is an inline SVG. Opening it in a browser is the demo. A web server can come later if there's time.

Repo layout is in `AGENTS.md`. Files in `mappings/`, `data/` and `docs/` are reference data and must be validated on load.

## Timeline (today)
- Now to ~11:00: organisers (Leaseweb token, AWS demo account decision), build the demo AWS account by hand in the console, ask the Leaseweb platform questions.
- Until ~13:00: scanner, graph, `inventory.json` and `graph.json` working on the sample. Template generator for EC2, SG (nftables), ALB, DNS.
- Until ~14:00: runbook templates and agent with the validator. Report HTML.
- 14:00 to 15:00: AI calls cached, `--no-ai` path tested, demo rehearsed twice, feature freeze at 15:00.
- Pitch prep: 5-minute script (below).

Priority if time runs short, in order: EC2 + SG (nftables) > report with cost and security > runbook for EBS/RDS > ALB > S3 runbook > Route 53.

## Demo script (5 minutes)
1. Screenshot of the AWS console: "all of this was made by clicking" (0:30).
2. `sovereign-shift all` on the demo account or the snapshot. The graph shows a forgotten link, such as web SG to DB SG (1:00).
3. Generated Terraform, `terraform validate` passes. Firewall rules come from the template, AI review flags a bad rule (1:30).
4. Report: AWS vs Leaseweb monthly cost, automatic vs manual list, security findings (1:00).
5. Runbook: personalised steps for the RDS and S3, placeholders visible, nothing secret (0:45).
6. Close: "Built for AWS today, Azure and GCP next. Every report is a qualified lead for Leaseweb." Mention the data-runbook gap before a judge asks (0:15).

## Verification
- pytest: scanner with moto, graph edges, rule mapping, Jinja2 output golden files, validator rejects bad runbook responses, security rules.
- `terraform init && terraform validate` through the container on every generated folder.
- `--no-ai` end to end from the snapshot, offline.
- Runbook validator test: a response with an unknown step id, a free-form command, or a real-looking secret must be rejected.
- Demo dry run from the snapshot, twice, before 15:00.

## Open questions
- **License:** the repo `LICENSE` is MIT (copyright "Francisco Silva"). The organisers require an open license allowing commercial reuse, and idea.md says Apache-2.0. Confirm which one, and who the copyright holder is. Not changed yet.
- Leaseweb API token and a test account, so the demo can run `terraform plan`.
- Is a real AWS account OK on stage, or only the snapshot?
- Does our OpenRouter key work on `eu.openrouter.ai`? If not, which fallback?
- Leaseweb platform: does the provider target the old platform (8 regions, EC2-compatible) or the new one (NL, OpenStack)? Keystone URL for the new one.
- Leaseweb object storage: ETA for the Terraform resources, and confirmation that the S3 endpoint accepts `rclone`.
