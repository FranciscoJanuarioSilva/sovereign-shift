# Translator (pipeline step 3)

Handover notes for other agents and humans. State as of 2026-11-20, not committed yet.

## What it does
Reads `inventory.json` (plus `graph.json` if present) and writes `mapping.json`: one entry per inventory resource, with a status, how it migrates, the Leaseweb target, a justification, cost and notes.

```bash
sovereign-shift translate out/inventory.json --out out            # rules + ai for unsupported services
sovereign-shift translate out/inventory.json --out out --no-ai    # rules only, offline
sovereign-shift translate out/inventory.json --out out --target-region eu-central-1
```
If `--graph` isn't given, it uses `out/graph.json` when it exists, else rebuilds the graph itself.
`out/mapping.json` is what `generate`, `runbook` and `report` read.

Rules do almost everything. The AI only runs for resources the rules mark `unsupported` (Lambda, SQS, DynamoDB, unknown DB engines, anything with `type: "other"`).

## Files
| Path | What |
|---|---|
| `sovereign_shift/translator/translate.py` | orchestration: terraform names, region mapping, db clients, ai step, `translate()`, `main_files()` |
| `sovereign_shift/translator/rules.py` | one function per resource type, `RULES` dict at the bottom |
| `sovereign_shift/translator/catalog.py` | loads reference data: Leaseweb types, AWS specs and prices, regions, images |
| `sovereign_shift/translator/models.py` | pydantic models for what the translator writes (`Mapping`, `MappingEntry`, `Cost`, `Alternative`) |
| `sovereign_shift/ai/client.py` | OpenAI-compatible JSON client with disk cache, reads `.env`. Reusable by other agents |
| `sovereign_shift/ai/redact.py` | strips secret-looking keys, account ids, ARNs and host IPs. Keeps CIDRs |
| `sovereign_shift/prompts/translator.txt` | translator system prompt |
| `mappings/regions.yaml` | AWS region -> Leaseweb region, Leaseweb locations, object storage endpoints |
| `mappings/images.yaml` | AMI name / OS string -> Leaseweb image id (regex, first match wins) |
| `data/aws_instance_types.json` | AWS vCPU / RAM / hourly USD per type (approximate list prices) |
| `testdata/clickops_inventory.json` | 19-resource fixture shaped like the real scanner output |
| `tests/test_translator.py` | tests, including one with scanner-shaped fields and fake-AI tests |

Not to be confused with `sovereign_shift/models.py`: that one holds the strict file contracts the downstream stages validate against. The translator's output passes it.

## Rules per resource type
| AWS type | Result | Notes |
|---|---|---|
| `ec2_instance` | `public_cloud_instance`, via terraform | type, region, image, disk, `has_private_network: true` |
| `security_group` | `security_group`, via finalize | translated rules + `attach_to`. Unused or LB-only groups aren't recreated (via report) |
| `db_instance` | `self_hosted_db`, manual, via runbook | Postgres/MySQL/MariaDB on a VM sized from `instance_class`. Other engines are unsupported, so AI |
| `lb` | `load_balancer`, via terraform | smallest m-family type. Internal and NLB flagged |
| `lb_listener` | `lb_listener`, via terraform | HTTPS is partial (new cert needed). TLS becomes TCP. UDP unsupported |
| `target_group` | `target_group`, via terraform | health check from flat scanner keys. `members` for finalize |
| `route53_record` | `dns_record`, partial, via terraform | TTL rounded to an allowed value. Alias becomes an A record (`alias_of`). Apex NS/SOA skipped |
| `route53_zone` | manual, via report | domain transfer or NS change |
| `s3_bucket` | `object_storage_bucket`, partial, via runbook | endpoint by country (`nl.object-storage.io`, ...) |
| `ebs_volume` | root disks: via report. Extra disks: merged into the instance root disk, data via runbook. Unattached: manual | |
| `elastic_ip` | attached: manual (IP changes). Unattached: nothing to do | |
| `key_pair`, `vpc`, `subnet` | via report | key goes into instance cloud-init, network collapses into the private network |
| anything else | unsupported, then AI | |

Things with no Terraform resource of their own use `via: report` on purpose. The generator lists every `via: terraform` entry without a Terraform kind as manual work, so `via: terraform` there would add noise.

### Instance sizing
1. vCPU/RAM come from the inventory, else from `data/aws_instance_types.json`.
2. Family: `c` stays c, `m` stays m, `r/x/z/u` become r. Burstable `t*` are picked by RAM per vCPU (≤2 c, ≤4 m, else r).
3. Choose the smallest Leaseweb type with at least that vCPU and RAM, sorted by vCPU, then newest generation (`6a` first), then RAM, then price.
4. Flags: nano/micro/small/medium are over-provisioned (Leaseweb starts at 2 vCPU). Graviton is ARM → x86 (not flagged for DBs). GPU types need review.

Examples on the fixture: `t3.large` -> `lsw.m6a.large`, `m6g.large` -> `lsw.m6a.large` (+ ARM note), `db.t3.medium` -> `lsw.c6a.large`.

### Security group rules (`target.rules`)
- 22/3389 from `0.0.0.0/0` or `::/0` become `{"cidr": "var:admin_cidr"}` (fixes SG-001).
- DB ports (1433, 3306, 5432, 6379, 9200, 27017) from the internet become `{"private_ip_of": <tf_name>}` for each app instance that uses the DB. If none is known, `var:admin_cidr` (fixes SG-002).
- A rule from another group becomes one `private_ip_of` rule per instance in that group. A rule from an LB-only group becomes `{"cidr": "var:private_network_cidr"}`.
- Protocol `-1` expands to TCP 1-65535, UDP 1-65535 and ICMP.
- Egress isn't translated (Leaseweb rules are inbound only, verify).
- DB clients come from the graph's `connects_to` edges plus the translator's own check of the DB's group rules, so it doesn't depend on graph field names.

### Region and image
- Regions: always through `mappings/regions.yaml`. Leaseweb `eu-west-3` is Amsterdam, AWS `eu-west-3` is Paris. Only `eu-west-3` and `eu-central-1` are confirmed. `eu-north-1` (our demo account) maps to `eu-west-3`. `--target-region` is checked against the provider's region list.
- Images: regex on the AMI name (`ubuntu-noble-24.04`, `al2023-ami`, ...). Amazon Linux becomes AlmaLinux 9 (partial). Ids not seen in the provider docs carry a "verify" note. Unknown OSes fall back to Ubuntu 24.04 (partial).

### Terraform names (`tf_name`)
Slug of the AWS name, unique across the inventory. Nameless listeners become `lb_listener_<port>`. DNS records get the record type appended. The current generator makes its own hashed labels and doesn't use `tf_name` yet, so `private_ip_of` and `attach_to` values in `target.rules` refer to `tf_name`s.

## Output fields
The full table per `target.kind` is in `docs/contracts.md`, section "As implemented". Extras beyond the original contract:
- top level: `generated_at`, `catalog_source`, and `ai` (`{used, base_url, model, asked, answered, disabled_reason}`)
- per entry: `source_name`, `tf_name`
- `monthly_cost_eur`: `{aws, leaseweb, aws_estimated, leaseweb_estimated}`
- `alternative` (AI only): `{name, effort, manual_steps, confidence}`

## AI step
- Config in env or `.env`: `SOVEREIGN_AI_API_KEY`, `SOVEREIGN_AI_MODEL` (required to enable), and `SOVEREIGN_AI_BASE_URL` (default `https://openrouter.ai/api/v1`). Per-agent overrides: `SOVEREIGN_AI_TRANSLATOR_MODEL` / `_BASE_URL`.
- Input: the resource (redacted), its neighbours' types, and a list of what Leaseweb can host, so it doesn't invent managed services.
- Output: JSON validated by `AIAnswer` (`alternative`, `justification`, `effort`, `manual_steps` ≤ 8, `confidence`). The entry becomes `status: manual`, `ai_suggested: true`, with a note "ai-suggested, review".
- If the answer is invalid, it retries once. If it fails again, or there's a network error, the entry stays `unsupported` with a note. No exception reaches the pipeline.
- Cache: `out/.cache/translator/<hash>.json`, keyed by model and prompt. Run once before the demo and the demo replays it offline.
- Current state: `.env` has a key but no model, so AI is off and the CLI says so. Nobody has run it against a real model yet.

## Prices
- Leaseweb: `data/leaseweb_catalog.json`, a committed snapshot of the real Public Cloud API (10 regions, 84 types each, vCPU, RAM, supported disk kinds, prices). End users need no token. Refresh it with `LEASEWEB_TOKEN=... python scripts/fetch_leaseweb_catalog.py`, or point `SOVEREIGN_LEASEWEB_CATALOG` at the customer's own file. Only EUR regions get EUR prices (Amsterdam, Frankfurt), other regions show `unknown`. Without a snapshot it falls back to `data/leaseweb_public_prices.json` and estimates (`leaseweb_estimated`).
- Disk kind: many newer types (`5a`, `6a`) are local-NVMe only, so `root_disk_storage_type` follows the chosen type (`LOCAL` or `CENTRAL`) and the report notes local disks. Databases prefer central-capable types.
- AWS: real on-demand prices for the resource's own region when `data/aws_instance_types.json` has them (`regional`, filled by `scripts/fetch_aws_prices.py` from the AWS Pricing API, read-only), × 730 h × 0.92. Otherwise approximate us-east-1 prices, flagged `aws_estimated` (starred in the report). Multi-AZ RDS counts double.
- Over-provisioned flag: raised when the chosen Leaseweb type has more vCPU than AWS, or at least twice the RAM. It compares capacity, not the size name.
- LB prices are unknown and left out of totals.

## Verified
- `pytest`: 20 tests pass (translator + graph + downstream).
- Real AWS account (read-only profile `sovereign-readonly`, `eu-north-1`): scan, then translate works. The account has no EC2 instances yet.
- On the fixture, graph → translate → generate → runbook → report all run, and `terraform validate` passes with `leaseweb/leaseweb` v1.32.1 (in podman).

## Known gaps / for other owners
1. ~~Generator ignores `target.rules`~~: fixed in `ceba5dc`. ~~Account id in Terraform labels~~: fixed, labels are now the `tf_name` (hash fallback, never the raw id), and `publish` writes masked copies of every shareable file to `out/public/`. CI uploads only that folder.
2. Generator: listener build raises if a listener forwards to more than one target group (ALB rules). The translator keeps only the default target group and flags path/host rules.
3. ~~Report noise~~: fixed. Costs list priced rows only, by name, with AWS/Leaseweb types and an over-provisioned flag. AI alternatives are rendered as text. The runbook skips resources with nothing to move (including root disks) and lists them in one line.
4. AI model and base URL to be chosen and put in `.env`.
5. Real Leaseweb prices need a token and a catalog fetch script.
6. Leaseweb region codes other than `eu-west-3` / `eu-central-1`, and image ids marked `verified: false`, still need checking against the API.
