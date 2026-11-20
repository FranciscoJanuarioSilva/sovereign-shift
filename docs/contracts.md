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


Cloudflare inventories use `source: cloudflare`, `regions: ["global"]`, the same relation shape, and resource types prefixed with `cloudflare_`. IDs begin with `cf:` and include the resource kind. Worker bindings retain their name and type through graph relations and resource nodes. Binding values, source code and stored application data are excluded. DNS record sets are grouped by zone, name and type. Account-level Cloudflare cost fields in the report use the `cloudflare_` prefix and the monthly total is null when billing is unknown.

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
- `target.kind` values: `public_cloud_instance`, `security_group`, `load_balancer`, `lb_listener`, `target_group`, `dns_record`, `object_storage_bucket`, `self_hosted_db`, `ssh_key`, `merged_into_instance`, or `target: null` when nothing is created.
- When `ai_suggested` is true, `alternative` and `justification` come from the translator agent, and `status` is `manual`.
- Resources that have no target of their own (VPC, subnet, key pair) still get an entry, with a note on where they went (for example "key in web-1 cloud-init").

### As implemented (`sovereign_shift/models.py`, `sovereign_shift/translator/`)
Top level also has `generated_at`, `catalog_source` (`catalog:api:<date>` or `fallback:provider-schema+estimated-prices`) and `ai` (`{used, base_url, model, asked, answered, disabled_reason}`).

Every entry also has:
- `source_name`: the AWS name.
- `tf_name`: terraform-safe, unique name. Use it as the resource name in `.tf` and in `finalize.json` (`private_ip_of`, `attach_to`, `members` all use it).
- `monthly_cost_eur`: `{aws, leaseweb, aws_estimated, leaseweb_estimated}`. Without a Leaseweb token, prices are estimates except `lsw.c6a.large`.
- `alternative` (only when `ai_suggested`): `{name, effort: low|medium|high, manual_steps[], confidence}`.

`target` per kind (fields the generator needs):
| kind | fields |
|---|---|
| `public_cloud_instance` | `region, instance_type, image_id, root_disk_size, root_disk_storage_type, has_private_network, contract{type, billing_frequency, term}, ssh_key_name` |
| `self_hosted_db` | same as instance, plus `engine` (postgres/mysql/mariadb), `engine_version`, `port`. `via: runbook`, but the generator may create the VM |
| `security_group` | `name, rules[{protocol TCP/UDP/ICMP, start_port, end_port, source}], attach_to[tf_name]`. `source` is `{"cidr": "1.2.3.0/24"}`, `{"cidr": "var:admin_cidr"}`, `{"cidr": "var:private_network_cidr"}` or `{"private_ip_of": tf_name}` |
| `load_balancer` | `region, type, reference, contract` |
| `lb_listener` | `protocol HTTP/HTTPS/TCP, port, load_balancer, default_target_group` (tf_names), `certificate` (`var:tls_certificate` or null) |
| `target_group` | `name, protocol, port, region, health_check{protocol, port, uri, method}, members[tf_name]` (members go to finalize) |
| `dns_record` | `domain_name, name (trailing dot), type, ttl (allowed value), content[], alias_of` (tf_name whose IP fills `content` after apply) |
| `object_storage_bucket` | `bucket, endpoint` |
| `ssh_key` | `public_key_from` (`inventory` or `var:ssh_public_key`) |
| `merged_into_instance` | `instance` (tf_name) |

Security fixes the translator already applies: 22/3389 from the internet become `var:admin_cidr` (SG-001). DB ports from the internet become the private IPs of the instances that use the DB, or `var:admin_cidr` if none are known (SG-002). SG-to-SG rules become `private_ip_of` rules. Groups only used by an LB, or unused, aren't recreated.

Translator inputs: `inventory.json` (required), `graph.json` (optional, rebuilt if missing), `data/leaseweb_catalog.json` (optional, real prices), `data/aws_instance_types.json`, `mappings/regions.yaml`, `mappings/images.yaml`.

Every entry also carries `fixes`: the finding ids (for example `SG-001`, `RDS-001`) the translation removes. The posture section uses it for the "after migration" score.

## assessment.json (assess)
Written by `sovereign-shift assess`, read by the report. Rules only. The rubrics are the `skills/assess-*` files, explained in `docs/assessment.md`.
```json
{
  "posture": {"overall": {"before": 41, "after": 69, "grade_before": "D", "grade_after": "C"},
              "domains": [{"id": "network", "title": "Network exposure", "assessed": true, "before": 0, "after": 84, "findings": 6, "fixed": 3}],
              "not_assessed": ["Access and identity"], "findings": [], "exposure": {"before": [], "after": []}},
  "risk": {"overall": {"current": "critical", "after_migration": "high", "migration": "high", "readiness": "ready with conditions",
                       "resolved_by_migration": 3, "counts": {}},
           "heatmap": [[0, 0, 0, 0, 0]], "top_today": [], "top_after_migration": [],
           "register": [{"id": "R-RDS-001-0", "title": "...", "category": "security", "likelihood": 5, "impact": 5, "score": 25,
                         "rating": "critical", "score_after": null, "rating_after": "resolved", "phase": "lasting",
                         "resources": [], "evidence": "...", "mitigation": "...", "mitigated_by_migration": true}]},
  "performance": {"rows": [], "general": [], "not_assessed": []},
  "scaling": {"tiers": [], "single_points_of_failure": [], "scale_up": [], "scale_out": [], "limits": []}
}
```
With AI on, `risk.narrative` and `scaling.narrative` hold `{text, justification, ai_suggested}`.

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
A committed snapshot of the Leaseweb Public Cloud catalog, so end users need no token. Written by `scripts/fetch_leaseweb_catalog.py` (maintainers, needs `LEASEWEB_TOKEN`) from `GET /regions` and `GET /instanceTypes?region=...`. A customer can supply their own copy with `SOVEREIGN_LEASEWEB_CATALOG`. One instance type per line in the file.
```json
{
  "fetched_at": "2026-11-20T13:24:00Z",
  "source": "api",
  "note": "...",
  "regions": [{"code": "eu-west-3", "location": "Amsterdam", "currency": "EUR", "storage_types": ["central", "local"]}],
  "instance_types": [
    {"name": "lsw.m6a.large", "region": "eu-west-3", "vcpu": 2, "memory_gib": 8.0, "gpu": 0, "currency": "EUR",
     "price_hourly_local": 0.0528, "price_monthly_local": 37.38, "price_hourly_eur": 0.0528, "price_monthly_eur": 37.38,
     "storage_types": ["local"], "min_disk_gib": 5}
  ]
}
```
- Each region is billed in its own currency. `price_*_eur` is filled only when the region is billed in EUR, otherwise `null` (the report then shows `unknown`). The `*_local` fields always hold the API number in `currency`.
- `storage_types` is what the type supports as root disk in that region. The translator writes `root_disk_storage_type` from it (`CENTRAL` only when `central` is listed).
- The translator reads `name`, `region`, `vcpu`, `memory_gib`, `price_monthly_eur`, `currency`, `storage_types`.
