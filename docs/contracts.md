# Data contracts

Every module reads and writes JSON files, so people can work in parallel and any step can resume from the previous file. Shapes below are the MVP contract. Keep field names stable. Add fields, don't rename them.

## inventory.json (scanner output)
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
        "volumes": [{"id": "vol-1", "size_gib": 30, "encrypted": false}],
        "key_name": "ops-key"
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
Resource types in the MVP: `ec2_instance`, `ebs_volume`, `elastic_ip`, `key_pair`, `vpc`, `subnet`, `security_group`, `lb`, `target_group`, `lb_listener`, `db_instance`, `s3_bucket`, `route53_zone`, `route53_record`.

Secrets are never stored in `inventory.json`. `user_data` is stored only as a hash and a length.

## graph.json (graph output)
```json
{
  "nodes": [{"id": "i-0abc123", "type": "ec2_instance", "name": "web-1"}],
  "edges": [{"from": "i-0abc123", "to": "sg-1", "type": "uses_security_group"}],
  "findings": [{"id": "SG-001", "resource": "sg-1", "severity": "critical"}]
}
```
Edges can be inferred, for example `ec2_instance -> db_instance` when a DB security group allows the instance's SG on 5432 or 3306. Mark inferred edges with `"inferred": true`.

## mapping.json (translator output, one entry per resource)
```json
{
  "source_id": "i-0abc123",
  "source_type": "ec2_instance",
  "status": "auto | partial | manual | unsupported",
  "target": {
    "provider": "leaseweb",
    "kind": "public_cloud_instance",
    "region": "eu-west-3",
    "instance_type": "lsw.m6a.large",
    "image_id": "UBUNTU_22_04_64BIT"
  },
  "alternative": null,
  "justification": "Closest match on vCPU and RAM in Amsterdam.",
  "ai_suggested": false,
  "monthly_cost_eur": {"aws": 30.4, "leaseweb": 0.0},
  "notes": []
}
```
When `ai_suggested` is true, `alternative` and `justification` come from the translator agent. `status` is `manual` when no target is set and the alternative is advisory.

## runbook.json (runbook output)
```json
{
  "generated_by": "ai | template-default",
  "model": "eu-model-id-or-null",
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
          "inputs": {"source host": "customer"},
          "verify": "pg_restore --list orders.dump | head",
          "notes": ["Run during a low-traffic window."]
        }
      ]
    }
  ]
}
```
Commands must match a template in `runbook/templates/`. Placeholders are either filled from inventory (`"inputs": {"...": "inventory"}`) or marked `<CUSTOMER: ...>`. Real secrets are never in this file.

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
The validator rejects any step id not in the template, any command that doesn't match `command` after placeholder substitution, and any input with an unknown source.

## mappings/regions.yaml
```yaml
# verify codes against the regions API before the demo
aws_to_leaseweb:
  eu-west-1: eu-west-3      # Dublin -> Amsterdam
  eu-central-1: eu-central-1
  eu-west-2: eu-west-3      # London -> Amsterdam by default
leaseweb_codes:
  eu-west-3: Amsterdam
  eu-central-1: Frankfurt
```
