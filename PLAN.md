# PLAN.md: sovereign-shift

Hackathon Portugal 2026 (Leaseweb + Velv), Lisbon, 20 Nov 2026. Theme: "InfraHack: AI for Cloud Infrastructure". Feature freeze 15:00, pitches from 15:45, 5 minutes max.

## Why
Leaseweb told us customers with Terraform are easy to migrate. Customers who built AWS by clicking in the console ("ClickOps") are hard to migrate, because nobody has a full picture of what exists or how it connects.

Pitch: "Existing tools turn your ClickOps into AWS Terraform. That keeps you on AWS. We turn it into Leaseweb Terraform."

Business case for Leaseweb: a free self-service assessment turns hard-to-migrate AWS customers into qualified leads with an estimated contract value, and leaves them with infrastructure as code.

## Product
Input: read-only AWS credentials. Output, in one folder:
- `out/terraform/*.tf`: Leaseweb Terraform (provider `leaseweb/leaseweb`).
- `out/finalize.json`: the Leaseweb API calls Terraform can't make (security groups, firewall rules, load balancer targets). `sovereign-shift finalize` runs them after `terraform apply`.
- `out/graph.json`: dependency graph.
- `out/runbook.json`: AI-personalised data migration runbook.
- `out/report.json` and `out/report.md`: the report. It holds the graph (Mermaid), cost comparison (AWS vs Leaseweb), automatic vs manual work, security findings and the runbook. The `.md` renders on GitHub and in any Markdown viewer. The `.json` feeds the website we build later.

The source cloud stays pluggable. The IR is provider-neutral, and only the scanner is AWS-specific. Azure and GCP are the roadmap.

## Pipeline
Each step reads the previous step's JSON, so steps run in order but any step can be rerun on its own.
1. **Scan** (`sovereign_shift/scanner/`): own boto3 `describe_*` / `list_*` calls, read-only. Output `inventory.json`.
2. **Graph** (`sovereign_shift/graph/`): resolve relationships from IDs, run the security checks. Output `graph.json` and `findings.json`.
3. **Translate** (`sovereign_shift/translator/`): rules pick the Leaseweb equivalent where one exists. AI proposes an open-source alternative for the rest. Output `mapping.json`.
4. **Generate** (`sovereign_shift/generator/`): Jinja2 templates render Terraform from `mapping.json`. The same step writes `finalize.json` (security groups and LB targets). Output `out/terraform/*.tf`, `out/finalize.json`.
5. **Finalize** (`sovereign_shift/finalize/`), after `terraform apply`: reads `terraform output -json` for the new instance and target group ids, looks up private IPs, then calls the Leaseweb API from `finalize.json`. `--dry-run` (the default without `LEASEWEB_TOKEN`) prints the calls instead of making them.
6. **Runbook** (`sovereign_shift/runbook/`): AI picks and fills steps from the template library. Output `runbook.json`.
7. **Report** (`sovereign_shift/report/`): `report.json` plus `report.md`.

Data contracts are in `docs/contracts.md`. Agree on them first and keep them stable. Then the people working on later steps can start from hand-written fixture files instead of waiting for the earlier steps.

## MVP scope
Driven by what Leaseweb can express. The Terraform provider (v1.32.1, `docs/research/leaseweb-terraform.md`) has no security groups, firewall, networks, volumes, object storage or LB target membership. The Public Cloud REST API has security groups, firewall rules and target registration (`docs/research/leaseweb-api.md`), so finalize uses the API for those.

| AWS | Leaseweb target | How | Status |
|---|---|---|---|
| EC2 instance + root EBS | `leaseweb_public_cloud_instance` | Terraform | auto |
| SSH key pair | inside the cloud-init `user_data` (`ssh_key` and `user_data` can't both be set) | Terraform | auto |
| Security group | native Leaseweb security group + firewall rules, attached to the instance | finalize (API) | auto |
| SG-to-SG rule (e.g. web -> db on 5432) | one rule per source instance, its private IP as a /32 | finalize (API), after apply | auto |
| ALB/NLB + listeners + target groups | `leaseweb_public_cloud_load_balancer`, `_listener`, `_target_group` | Terraform | auto |
| Target group members | `POST /targetGroups/{id}/registerTargets`. Backends need `has_private_network = true` | finalize (API) | auto |
| HTTPS listener certificate | ACM certs can't be exported, a new cert is needed | report | manual |
| Route 53 records | `leaseweb_dns_resource_record_set` (domain must be at Leaseweb). Alias records become A records to the new IP | Terraform | partial |
| Route 53 zone | domain transfer or NS change | report | manual |
| Elastic IP | none. `leaseweb_public_cloud_ip` only sets reverse DNS. The IP changes, so DNS needs updating | report | manual |
| Extra EBS volumes | none (no volume resource). Bigger root disk plus a data copy in the runbook | Terraform + runbook | partial |
| S3 bucket | Leaseweb Object Storage (S3-compatible, not in Terraform since 1.32.1). `rclone` in the runbook | runbook | partial |
| RDS | self-hosted Postgres/MySQL on a Leaseweb instance, dump/restore in the runbook | runbook | manual (AI) |
| Lambda, SQS, DynamoDB, ECS/EKS, others | AI proposes an open-source alternative and effort estimate | report | manual (AI) |

Fallback if finalize can't run (no token, API problem): the security groups go into the report as manual work, and finalize's dry-run output shows the exact calls. An nftables cloud-init firewall is a possible later addition, not MVP.

Traps:
- Leaseweb `eu-west-3` is Amsterdam, AWS `eu-west-3` is Paris. Map regions through `mappings/regions.yaml`, never copy the string.
- `user_data` goes as plain text, not base64.
- The private network interface isn't up by default. The KB calls it `eth1` (old platform), but our team VM on the new platform has `enp3s0`. The cloud-init brings up every non-primary interface with DHCP, by match, never by a hard-coded name.
- Every Leaseweb instance gets a public IPv4. A DB that was in a private AWS subnet must be closed by its security group.
- The default Leaseweb security group allows everything. Finalize attaches ours.

## Data migration runbook
Terraform rebuilds infrastructure. It does not move disks, bucket objects or database rows. The runbook covers that gap, and the pitch says so before a judge asks.

**How it's made:**
- `runbook/templates/*.yaml` is a library of allowed steps per resource type. Each step has an id, a command template with named placeholders, its inputs (from inventory or from the customer) and a verification command.
- The runbook agent gets one mapped resource, the templates for its type and the target Leaseweb values. It returns JSON only: step ids in order, input values, short notes for this customer, and `not_capable` entries with a reason. It never returns a command.
- Our code renders the commands from the templates. The validator only checks that every step id exists in the library and that every input is filled from inventory or marked `<CUSTOMER: ...>`. Anything else is dropped.
- AI can only claim a resource is runbook-capable if a template exists. Everything else goes to the report's manual section with prose only.
- If the AI fails or is off (`--no-ai`), the template's default steps are used, marked "not personalised".
- Secrets never appear. The runbook shows placeholders, and the customer fills in keys at execution time.
- Output is cached by input hash, so the demo is repeatable.

**First template library (in order):** RDS PostgreSQL dump/restore, S3 bucket sync (rclone), EC2 application data copy (rsync), EBS volume copy, RDS MySQL dump/restore, Route 53 cutover (lower TTL, switch record, verify).

## AI use
| Job | Agent | Input | Output | Fallback |
|---|---|---|---|---|
| Alternatives for unmappable services | translator | one resource + neighbours + Leaseweb schema subset | `{alternative, justification, effort, manual_steps, confidence}` | "manual, no suggestion" |
| Personalised runbook | runbook | one resource + its templates + target values | step ids, inputs, notes, `not_capable` | template default steps |
| Firewall review | reviewer | translated Leaseweb rules + the AWS SG source | `{ok, issues[]}`, shown in the report | rules still applied, flagged "unreviewed" |
| Summary | explainer | `report.json` | short paragraph on the architecture and the migration | omitted (cut first if time runs short) |

The LLM never writes HCL, firewall rules or commands. Its output is JSON, validated with pydantic. Every AI choice carries a `justification` and an `ai-suggested` mark in the output.

Demo moment for the AI: show the validator rejecting a bad AI answer (an unknown step id, or a suggestion for a resource with no template). This shows "AI with guardrails", which is also the security angle.

Backend: OpenAI-compatible client with configurable base URL. Default: OpenRouter global host with `provider: {only: ["mistral"], allow_fallbacks: false, data_collection: "deny"}`, models `mistral-small-2603` (translator, explainer) and `mistral-medium-3-5` (runbook, reviewer). See `docs/research/environment.md`.

Redaction before every call: no keys, passwords, tokens, `user_data` contents, account IDs or host IP addresses. CIDRs in security group rules are kept, because the reviewer needs them (`0.0.0.0/0` is the point).

## Architecture
Python 3.11+. Packages: boto3, pydantic, networkx, typer, jinja2, openai SDK, httpx (Leaseweb API), pytest, moto. No Textual, no FastAPI in the MVP.

```
scanner (boto3) -> inventory.json
  -> graph (networkx + security checks) -> graph.json, findings.json
  -> translator (rules, then AI) -> mapping.json
  -> generator (Jinja2) -> out/terraform/*.tf, finalize.json
  -> [terraform apply] -> finalize (Leaseweb API)
  -> runbook (AI + template library) -> runbook.json
  -> report -> report.json, report.md
```

- CLI (typer): `sovereign-shift scan|graph|translate|generate|finalize|runbook|report|all`. `all` runs everything except finalize, which needs `terraform apply` first.
- `--no-ai` and `--from-snapshot <inventory.json>` must both work offline.
- Former2, aws2tf, Terraformer and terracognita are not dependencies (`docs/research/aws-scanning.md`).
- Report: Mermaid `flowchart` for the graph and Markdown tables for cost, work and findings. Mermaid renders on GitHub and in the website later (mermaid.js). A cost chart (Mermaid `xychart-beta` or a PNG) only if there's time.
- Leaseweb catalog: `scripts/fetch_leaseweb_catalog.py` (maintainers, with the token) snapshots `GET /instanceTypes` and `GET /regions` into `data/leaseweb_catalog.json`, which is committed. End users need no token: the translator reads the snapshot, or a customer's own file via `SOVEREIGN_LEASEWEB_CATALOG`. Details in `docs/research/leaseweb-api.md`.

Repo layout is in `AGENTS.md`. Files in `mappings/`, `data/` and `docs/` are reference data and must be validated on load.

## Timeline (today)
The steps depend on each other, so this mostly runs in order. Fixture files written from the contracts let later steps start early.
1. First: contracts frozen. Package skeleton, CLI and `pyproject.toml`. Real `inventory.json` from our AWS accounts becomes the fixture. Leaseweb token: fetch the catalog and regions, run `terraform init` and `plan`.
2. Scanner + graph + findings on the real account.
3. Translator rules + generator for EC2, ALB, DNS. `terraform validate` passes.
4. Finalize (SGs, targets), tested for real with the token.
5. Report (`report.md`, `report.json`).
6. Runbook templates + agent + validator. Other AI agents.
7. 14:30: AI answers cached, `--no-ai` tested, demo rehearsed twice. Feature freeze 15:00. 15:00-15:45: pitch rehearsal.

Priority if time runs short, in order: EC2 + SGs (finalize) > report with cost and security > ALB with targets > runbook for RDS/S3 > DNS > explainer.

## Demo script (5 minutes)
1. Screenshot of the AWS console: "all of this was made by clicking" (0:30).
2. `sovereign-shift all` on the demo account (or the snapshot). The graph shows a forgotten link, such as web SG to DB SG (1:00).
3. Generated Terraform, `terraform plan` on Leaseweb. Finalize creates the security groups and registers the LB targets, the parts the Terraform provider can't do yet (1:15).
4. Report: AWS vs Leaseweb monthly cost (with traffic), automatic vs manual list, security findings fixed by the migration (1:00).
5. Runbook: personalised steps for the RDS and S3, placeholders visible, nothing secret. The validator rejects a bad AI answer (1:00).
6. Close: "Built for AWS today, Azure and GCP next. Every report is a qualified lead for Leaseweb." (0:15).

## Verification
- pytest: scanner with moto, graph edges, rule mapping, Jinja2 output golden files, finalize dry-run output, runbook validator, security rules.
- `terraform init && terraform validate` on every generated folder.
- `--no-ai` end to end from the snapshot, offline.
- Runbook validator test: an unknown step id, a missing input, or a real-looking secret must be rejected.
- Demo dry run, twice, before 15:00.

## Open questions
- Leaseweb API token: we have one (repo secret `LEASEWEB_TOKEN`), used only to refresh the price snapshot. Still untested: `terraform plan`/`apply` and a live finalize.
- Can the default Leaseweb security group be detached from an instance? Test with the token.
- Load balancer prices: not in `GET /instanceTypes`, so still left out of the cost total. Ask Leaseweb.

## Resolved
- AI: OpenRouter global host pinned to Mistral (`eu.openrouter.ai` needs a Business plan). Details in `docs/research/environment.md`.
- AWS demo account: read-only key confirmed, only `eu-north-1` is allowed, account empty so far (build list in `docs/research/environment.md`).
- AWS demo setup (team chat, 2026-11-20): the team reported an empty AWS account and created the IAM user `sovereign-shift-agents` to provision demo resources. Effective permissions and account contents still need verification. The scanner uses its read-only profile.
- License: Apache-2.0.
- Terraform (not OpenTofu).
- Target: the `leaseweb/leaseweb` provider plus the Public Cloud REST API. The provider has no OpenStack code. The OpenStack-based new platform is roadmap.
- Security groups and LB targets: Leaseweb API in finalize, not nftables.
- Report: Markdown + JSON, website later.
- AWS demo account: free for us, so use realistic instance types (`t3.large`, `m5.large`), not `t3.micro` (the smallest Leaseweb type is 2 vCPU, so tiny instances make the comparison unfair).
