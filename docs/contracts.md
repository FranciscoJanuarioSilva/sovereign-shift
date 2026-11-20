# Data contracts

Every module reads and writes JSON files, so people can work in parallel from fixture files and any step can be rerun from the previous file. Shapes below are the MVP contract. Keep field names stable. Add fields, don't rename them. Each file is a pydantic model in `sovereign_shift/models.py`, and each step validates what it reads.

| File | Written by | Read by |
|---|---|---|
| `inventory.json` | scan | graph, translate, generate, runbook, report |
| `graph.json` | graph | translate, generate, report |
| `findings.json` | graph | report, reviewer agent |
| `mapping.json` | translate | generate, runbook, report |
| `out/terraform/*.tf` | generate | terraform |
| `finalize.json` | generate | finalize, report |
| `runbook.json` | runbook | report |
| `report.json`, `report.md` | report | website (later), humans |

## inventory.json (scan)
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
        "instance_type": "t3.large",
        "vcpu": 2,
        "memory_gib": 8,
        "os": "ubuntu-22.04",
        "volumes": [{"id": "vol-1", "size_gib": 30, "encrypted": false, "root": true}],
        "key_name": "ops-key",
        "public_ip": true
      },
      "tags": {"env": "prod"},
      "relations": [
        {"type": "in_subnet", "target": "subnet-1"},
        {"type": "uses_security_group", "target": "sg-1"}
      ]
    },
    {
      "id": "sg-1",
      "type": "security_group",
      "region": "eu-west-1",
      "name": "web-sg",
      "properties": {
        "ingress": [
          {"protocol": "tcp", "from_port": 22, "to_port": 22, "cidrs": ["0.0.0.0/0"], "source_groups": []},
          {"protocol": "tcp", "from_port": 443, "to_port": 443, "cidrs": ["0.0.0.0/0"], "source_groups": []}
        ],
        "egress": [{"protocol": "-1", "from_port": null, "to_port": null, "cidrs": ["0.0.0.0/0"], "source_groups": []}]
      },
      "tags": {},
      "relations": []
    }
  ]
}
```
Resource types in the MVP: `ec2_instance`, `ebs_volume`, `elastic_ip`, `key_pair`, `vpc`, `subnet`, `security_group`, `lb`, `target_group`, `lb_listener`, `db_instance`, `s3_bucket`, `route53_zone`, `route53_record`. Anything else the scanner sees goes in with `"type": "other"` and `properties.aws_type`, so the report can list it.

Secrets are never stored. `user_data` is stored only as a hash and a length. Public keys from `describe_key_pairs(IncludePublicKey=True)` are fine to store (they're public).

## graph.json (graph)
```json
{
  "nodes": [{"id": "i-0abc123", "type": "ec2_instance", "name": "web-1"}],
  "edges": [
    {"from": "i-0abc123", "to": "sg-1", "type": "uses_security_group", "inferred": false},
    {"from": "i-0abc123", "to": "db-orders", "type": "talks_to", "inferred": true, "evidence": "sg-db allows sg-1 on 5432"}
  ]
}
```
Inferred edges (for example `ec2_instance -> db_instance` when the DB's SG allows the instance's SG on 5432 or 3306) have `"inferred": true` and an `evidence` string.

## findings.json (graph)
```json
{
  "findings": [
    {
      "id": "SG-001",
      "severity": "critical",
      "resource": "sg-1",
      "title": "SSH open to the internet",
      "evidence": "tcp/22 from 0.0.0.0/0",
      "fixed_by_migration": true,
      "fix": "Leaseweb security group only allows 22 from admin_cidr"
    }
  ]
}
```
Check ids and severities are in `docs/research/security-rules.md`.

## mapping.json (translate)
```json
{
  "target_region": "eu-west-3",
  "entries": [
    {
      "source_id": "i-0abc123",
      "source_type": "ec2_instance",
      "status": "auto",
      "via": "terraform",
      "target": {
        "kind": "public_cloud_instance",
        "region": "eu-west-3",
        "instance_type": "lsw.m6a.large",
        "image_id": "UBUNTU_22_04_64BIT",
        "root_disk_size": 30,
        "has_private_network": true
      },
      "alternative": null,
      "justification": "Same vCPU and RAM, Amsterdam is the closest EU location.",
      "ai_suggested": false,
      "monthly_cost_eur": {"aws": 61.0, "leaseweb": 34.4},
      "notes": []
    }
  ]
}
```
- `status`: `auto | partial | manual | unsupported`.
- `via`: `terraform | finalize | runbook | report`.
- `target.kind` values: `public_cloud_instance`, `security_group`, `load_balancer`, `lb_listener`, `target_group`, `dns_record`, `object_storage_bucket`, `self_hosted_db`, or null for `manual`.
- When `ai_suggested` is true, `alternative` and `justification` come from the translator agent, and `status` is `manual`.
- Resources that have no target of their own (VPC, subnet, key pair) still get an entry, with a note on where they went (for example "key in web-1 cloud-init").

## finalize.json (generate)
API calls Terraform can't make, in order. Ids that only exist after `terraform apply` are references into `terraform output -json`. Private IPs are looked up with `GET /instances/{id}/ips`.
```json
{
  "api": "https://api.leaseweb.com/publicCloud/v1",
  "security_groups": [
    {
      "source_id": "sg-db",
      "name": "db-sg",
      "rules": [
        {"protocol": "TCP", "start_port": 5432, "end_port": 5432, "source": {"private_ip_of": "web_1"}},
        {"protocol": "TCP", "start_port": 22, "end_port": 22, "source": {"cidr": "var:admin_cidr"}}
      ],
      "attach_to": ["db_1"]
    }
  ],
  "target_registrations": [
    {"target_group": "tg_web", "instances": ["web_1", "web_2"]}
  ]
}
```
`web_1`, `db_1` and `tg_web` are Terraform resource names. The generator writes one `output` per instance and target group so finalize can resolve them. `finalize --dry-run` prints the resolved calls without sending them.

## runbook.json (runbook)
```json
{
  "generated_by": "ai | template-default",
  "model": "model-id-or-null",
  "entries": [
    {
      "source_id": "db-orders",
      "source_type": "db_instance",
      "personalised": true,
      "not_capable": [],
      "steps": [
        {
          "id": "pg-dump-source",
          "title": "Dump the source database",
          "command": "pg_dump --format=custom --file=orders.dump \"host=<CUSTOMER: source host> dbname=orders\"",
          "inputs": {"dump_file": "inventory", "source_host": "customer", "db_name": "inventory"},
          "verify": "pg_restore --list orders.dump | head",
          "notes": ["Run during a low-traffic window."]
        }
      ]
    }
  ]
}
```
`command` and `verify` are rendered by our code from the template. Real secrets are never in this file.

What the runbook agent returns (validated with pydantic, never contains commands):
```json
{
  "steps": [{"id": "pg-dump-source", "inputs": {"dump_file": "orders.dump"}}],
  "notes": {"pg-dump-source": ["Run during a low-traffic window."]},
  "not_capable": [{"what": "point-in-time recovery", "reason": "no PITR on self-hosted Postgres without extra setup"}]
}
```

## Template file (runbook/templates/*.yaml)
```yaml
resource_type: db_instance
engine: postgres
steps:
  - id: pg-dump-source
    title: Dump the source database
    command: "pg_dump --format=custom --file={dump_file} \"host={source_host} dbname={db_name}\""
    inputs:
      dump_file: {source: inventory, default: "{name}.dump"}
      source_host: {source: customer}
      db_name: {source: inventory, field: name}
    verify: "pg_restore --list {dump_file} | head"
```
The validator drops any step id not in the template and any input that isn't declared in it. Customer inputs always render as `<CUSTOMER: ...>`, whatever the agent sent.

## report.json (report)
Everything the website needs, so it never has to read the other files.
```json
{
  "generated_at": "2026-11-20T14:00:00Z",
  "source": {"cloud": "aws", "account_id": "****9012", "regions": ["eu-west-1"]},
  "target": {"cloud": "leaseweb", "region": "eu-west-3"},
  "summary": {"resources": 23, "auto": 14, "partial": 4, "manual": 5, "ai_text": "..."},
  "cost": {"aws_monthly_eur": 210.0, "leaseweb_monthly_eur": 120.0, "lines": [{"source_id": "i-0abc123", "aws": 61.0, "leaseweb": 34.4}], "assumptions": ["prices from data/leaseweb_catalog.json, fetched 2026-11-20"]},
  "graph": {"mermaid": "flowchart LR\n  ...", "nodes": [], "edges": []},
  "work": [{"source_id": "db-orders", "status": "manual", "via": "runbook", "what": "..."}],
  "findings": [],
  "runbook": {},
  "terraform_files": ["main.tf", "instances.tf"]
}
```
`report.md` is rendered from `report.json`. The account id is masked in both.

## mappings/regions.yaml
```yaml
# verify codes with GET /regions before the demo
aws_to_leaseweb:
  eu-west-1: eu-west-3      # Dublin -> Amsterdam
  eu-central-1: eu-central-1
  eu-west-2: eu-west-3      # London -> Amsterdam by default
leaseweb_codes:
  eu-west-3: Amsterdam
  eu-central-1: Frankfurt
```

## data/leaseweb_catalog.json
Written by `scripts/fetch_leaseweb_catalog.py` from `GET /instanceTypes?region=...` and `GET /regions`.
```json
{
  "fetched_at": "2026-11-20T09:30:00Z",
  "source": "api | fallback",
  "regions": [{"code": "eu-west-3", "location": "Amsterdam"}],
  "instance_types": [
    {"name": "lsw.c6a.large", "region": "eu-west-3", "vcpu": 2, "memory_gib": 4, "price_hourly_eur": null, "price_monthly_eur": 34.39}
  ],
  "traffic": {"included_tb": 1, "overage_eur_per_tb": 2.20}
}
```
