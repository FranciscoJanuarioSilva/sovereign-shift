> Superseded by `PLAN.md` and `AGENTS.md`. Kept as the original brief.

# sovereign-shift: project brief

## Context

We are building this at Hackathon Portugal 2026 (Leaseweb + Velv, Lisbon, 20 November 2026).
Theme: "InfraHack: AI for Cloud Infrastructure". We have about 6 hours of coding time with AI agent use.

Hard rules from the organizers:
- All code is written from scratch today. Open-source libraries and tools are allowed as dependencies.
- Public Git repo with an open license that allows commercial reuse. Use **Apache-2.0**.
- The repo needs a concise `README.md` (goal, structure, how to build and run) and clear setup instructions.
- Common languages preferred. Use **Python 3.11+**.
- Final pitch is 5 minutes max. A live demo is scored, so it must be reliable.
- Each team gets one Linux VM, deleted after the event.

Judging (equal weight, 1 to 5 each): innovation, applicability, technical complexity (use of AI and cloud infra), presentation.

## Problem

A Leaseweb employee told us: customers who already use Terraform are easy to migrate to Leaseweb.
Customers who built their AWS infrastructure by clicking in the console ("ClickOps") are very hard
to migrate, because nobody has a full picture of what exists or how it is connected.

## Product

**sovereign-shift** scans an AWS account with read-only credentials, rebuilds the dependency graph of
everything that was created by hand, translates it to Leaseweb equivalents with an LLM, and outputs
Terraform for the Leaseweb provider plus a migration report.

Built for AWS today. The design must keep the source cloud pluggable (Azure and GCP are the roadmap).

Business case for Leaseweb: a free self-service assessment that turns hard-to-migrate AWS customers
into qualified leads with an estimated contract value, and leaves them with infrastructure as code.

## Pipeline

1. **Scan** (`scanner/`): read-only boto3 `describe_*` and `list_*` calls. Output: `inventory.json`.
2. **Graph** (`graph/`): resolve relationships between resources. Output: `graph.json` plus a visual.
3. **Translate** (`translator/`): LLM maps each resource to a Leaseweb equivalent or an open-source
   alternative hosted on Leaseweb, with a short justification. Output: `mapping.json`.
4. **Generate** (`generator/`): render Terraform files for the Leaseweb provider from `mapping.json`.
   Output: `out/terraform/*.tf`.
5. **Report** (`report/`): web page with the graph, cost comparison (AWS vs Leaseweb), what migrates
   automatically, what needs manual work, and security findings found during the scan.

## MVP scope (today)

What the Leaseweb Terraform provider can actually express (checked against
`leaseweb/terraform-provider-leaseweb` v1.32.1, Oct 2026) drives the scope. It has **no** firewall,
security group, private network, Kubernetes or object storage resources (object storage was added in
1.32.0 and reverted in 1.32.1). Mapping table:

| AWS | Leaseweb target | Status |
|---|---|---|
| EC2 instance + root EBS | `leaseweb_public_cloud_instance` (`type`, `region`, `image.id`, `root_disk_size`, `root_disk_storage_type`, `contract`) | auto |
| Security group | no TF resource: LLM translates rules to an nftables `user_data` cloud-init script on the instance | auto (AI) |
| ALB/NLB + listeners + target groups | `leaseweb_public_cloud_load_balancer`, `_listener`, `_target_group` | auto |
| Elastic IP | `leaseweb_public_cloud_ip` (verify semantics) | auto / manual |
| Route 53 records | `leaseweb_dns_resource_record_set` (domain must be at Leaseweb) | auto |
| S3 bucket | Leaseweb Object Storage (S3-compatible, not in TF yet): generated `rclone` sync script | semi-auto |
| RDS | PostgreSQL/MySQL on a Leaseweb instance + `pg_dump` runbook | manual |
| Lambda, SQS, DynamoDB, anything else | LLM suggests open-source alternative + effort estimate | manual |

Note: `ssh_key` and `user_data` are mutually exclusive on the instance, so the SSH key goes inside the
cloud-init script. Leaseweb region names look like AWS ones (`eu-west-3`, `eu-central-1`) but are
different places: never copy the AWS region, map it.

Data (disk contents, bucket objects, DB rows) is not migrated by the Terraform. The report gives a
per-resource data migration runbook instead. Say this in the pitch before a judge asks.

Anything without a direct Leaseweb equivalent goes in the report as "manual work" with a suggested
open-source alternative (for example RDS -> PostgreSQL on a Leaseweb instance).

Security findings to flag during the scan:
- Security group rules open to `0.0.0.0/0` on non-web ports (e.g. 22, 3306, 5432)
- Public S3 buckets
- Unencrypted EBS volumes

## Data contract

All modules communicate through JSON files so team members can work in parallel.
Agree on this first and keep it stable.

`inventory.json`:

```json
{
  "source": "aws",
  "account_id": "123456789012",
  "scanned_at": "2026-11-20T10:00:00Z",
  "regions": ["eu-west-1"],
  "resources": [
    {
      "id": "i-0abc123",
      "type": "ec2_instance",
      "region": "eu-west-1",
      "name": "web-1",
      "properties": {
        "instance_type": "t3.medium",
        "vcpu": 2,
        "memory_gib": 4,
        "os": "ubuntu-22.04",
        "volumes": [{"id": "vol-1", "size_gib": 30, "encrypted": false}]
      },
      "tags": {"env": "prod"},
      "relations": [
        {"type": "in_subnet", "target": "subnet-1"},
        {"type": "uses_security_group", "target": "sg-1"}
      ]
    }
  ]
}
```

`mapping.json` (one entry per source resource):

```json
{
  "source_id": "i-0abc123",
  "source_type": "ec2_instance",
  "status": "auto | manual | unsupported",
  "target": {
    "provider": "leaseweb",
    "kind": "public_cloud_instance",
    "region": "<leaseweb region>",
    "instance_type": "<leaseweb instance type>"
  },
  "alternative": null,
  "justification": "Closest match on vCPU and RAM in an EU region.",
  "monthly_cost_eur": {"aws": 30.4, "leaseweb": 0.0}
}
```

## Build vs. depend for the scanner (decision)

Existing "AWS to Terraform" tools (aws2tf, Former2, Terraformer, terracognita, `terraform plan
-generate-config-out`) all output **AWS-provider** Terraform. That is the opposite of what we need:
it codifies the lock-in. The hard and novel part is the cross-provider translation, and no tool does
it. So we write our own boto3 scanner for the 6-8 types above (small, and we control `relations`),
and do not take any of these as a dependency. Terraformer is archived (Mar 2026); terracognita is
pinned to an old AWS provider; Former2 is browser-only; aws2tf needs Terraform 1.12, AWS CLI v2 and jq
and emits HCL, not an inventory.

Optional, if time allows: call the CloudFormation IaC generator resource scan (`start_resource_scan`,
`list_resource_scan_resources`, boto3) to count *everything* in the account, so the report can say
"we found 143 resources; 38 migrate automatically; here are the other 105". It gives types and IDs
only, no attributes, and takes minutes, so run it before the demo.

Pitch line: "Existing tools turn your ClickOps into AWS Terraform. That keeps you on AWS. We turn it
into Leaseweb Terraform."

## Leaseweb integration

- Official Terraform provider: https://github.com/leaseweb/terraform-provider-leaseweb (source
  `leaseweb/leaseweb`, latest 1.32.1, no longer beta). Token from `LEASEWEB_TOKEN`. The docs example
  pins `~> 1.2.0`, which is stale: pin `~> 1.32`. The instance doc example uses `private_network`, but
  the schema attribute is `has_private_network`. Copy names from the schema, not the example.
- Unknown: whether `terraform plan` works with a dummy token. Test it in the first 15 minutes.
  `terraform validate` works offline in any case.
- Developer API: https://developer.leaseweb.com/docs/ (auth header `X-LSW-Auth`).
  Public Cloud endpoints include regions and instance types.
- If we have no API key, use a static catalog in `data/leaseweb_catalog.json`
  (regions, instance types, vCPU, RAM, monthly price) and say so in the README and pitch.
- Same for AWS prices: static `data/aws_prices.json` for the supported instance types is fine.

## Where the AI does real work (not just a lookup table)

Instance sizing is a nearest-match problem; rules do it fine. The LLM earns its place on what rules
cannot do:
1. Security group -> nftables cloud-init (no Leaseweb TF equivalent exists).
2. AMI / OS detection -> Leaseweb `image.id` (e.g. `UBUNTU_22_04_64BIT`).
3. Unsupported services -> open-source alternative, migration steps, effort estimate.
4. Architecture summary of the graph ("3-tier web app, single AZ, DB exposed to the internet").
5. **Validate-and-repair loop**: run `terraform validate` on the output; on error, feed the message
   back to the LLM to fix the generated snippet (max 3 tries, then fall back to the template).

## LLM

- The translator must work with a pluggable backend: a local model through Ollama (preferred, fits
  the sovereignty story) or an API model via an environment variable.
- Use structured output (JSON schema) and validate every response. Fall back to a rule-based mapping
  (nearest vCPU/RAM match) if the LLM fails, so the demo never breaks.
- Keep prompts in `translator/prompts/` as plain files.

## Security requirements

- AWS access must be read-only. Document the IAM policy (AWS managed `ReadOnlyAccess` or a minimal
  custom policy listing only the calls we make) in `docs/iam-policy.json`.
- Never log or write credentials. Read them from the standard AWS environment/profile.
- Do not send credentials or account secrets to the LLM; send only resource metadata.

## Suggested repo layout

```
sovereign-shift/
  README.md
  LICENSE                 # Apache-2.0
  pyproject.toml
  docker-compose.yml      # app + optional Ollama
  sovereign-shift/
    cli.py                # `sovereign-shift scan|graph|translate|generate|report|all`
    scanner/aws.py
    graph/build.py
    translator/
      llm.py
      rules.py            # deterministic fallback
      prompts/
    generator/
      templates/          # Jinja2 templates for .tf files
      render.py
    report/
      app.py              # small web UI (FastAPI or Flask) with the graph and cost table
  data/
    leaseweb_catalog.json
    aws_prices.json
  docs/
    iam-policy.json
  examples/
    sample_inventory.json # lets the demo run offline if AWS is unreachable
  tests/
```

## CLI

```
sovereign-shift all --profile demo --region eu-west-1 --out out/
```

Each step can also run on its own and read the previous step's JSON, so the demo can resume from any
point and work offline from `examples/sample_inventory.json`.

## Demo script (5 minutes)

1. Screenshot of the AWS console: "all of this was created by clicking".
2. Run the scan live. Show the dependency graph in the web UI.
3. Show the generated Leaseweb Terraform and run `terraform plan` (real if we have an API key).
4. Show the report: AWS vs Leaseweb monthly cost, manual-work list, security findings.
5. Close: "Built for AWS today, Azure and GCP next. Every report is a qualified lead for Leaseweb."

## First 30 minutes (before writing code)

- Ask the organizers: a Leaseweb API token or test account (turns the demo into a real
  `terraform apply`), and whether a real AWS account on stage is OK.
- Check the VM: CPU/RAM/GPU. Without a GPU, an 8B model on Ollama takes ~10-30 s per call: cache all
  LLM answers and pre-run the demo. Fallback: an API model via env var (Mistral is an EU option that
  fits the story).
- Build the demo AWS account by clicking in the console, now: 2 EC2 (web + db), 1 ALB, security
  groups with one bad rule (22 or 5432 open to the world), 1 public S3 bucket, 1 unencrypted EBS,
  Route 53 records if a domain is available. Free tier where possible; delete it all at the end.
- `terraform init` with the Leaseweb provider on the VM; try `plan` with a dummy token.

## Priorities

1. Scan -> graph -> translate -> generate working end to end for EC2 + security groups (as
   nftables cloud-init) + ALB. S3 as rclone script.
2. Report page with cost comparison.
3. Security findings.
4. Load balancers, then RDS and Route 53.
5. Polish the README and the demo. Feature freeze at 15:00, pitches start at 15:45.