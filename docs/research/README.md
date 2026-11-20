# Research index

Facts about both sides of the migration. Fetched 2026-11-20. Facts carry source URLs. "inferred" or "verify" means not confirmed yet.

Start with `../../PLAN.md` for the product, and `../contracts.md` for the data shapes.

| File | What's in it |
|---|---|
| [leaseweb-terraform.md](leaseweb-terraform.md) | Leaseweb provider v1.32.1: resources, attributes, gaps, plan/validate behaviour |
| [leaseweb-api.md](leaseweb-api.md) | Public Cloud REST API: security groups, firewall rules, target registration, instance types with prices. What finalize calls |
| [leaseweb-platform.md](leaseweb-platform.md) | public cloud platforms, instance families, LB, object storage (S3), VPC, k8s, DCs, compliance, open questions |
| [aws-scanning.md](aws-scanning.md) | read-only credentials, boto3 calls and dependency edges (the scanner we build). Former2 as reference only. |
| [aws-terraform.md](aws-terraform.md) | AWS HCL format, in-scope resources and fields |
| [service-equivalence.md](service-equivalence.md) | AWS -> Leaseweb table, instance/AMI/RDS mapping rules |
| [regions-and-locations.md](regions-and-locations.md) | region codes (watch the eu-west-3 trap), recommended location per AWS region |
| [security-rules.md](security-rules.md) | checks for the report |
| [environment.md](environment.md) | our AWS demo account (read-only, eu-north-1 only), the AI setup that works, the team VM |
| [ai-providers.md](ai-providers.md) | provider options, client design, the four agents, caching and redaction |

## Machine-readable
- `../schemas/leaseweb.json`: full Leaseweb provider schema (v1.32.1).
- `../schemas/aws-subset.json`: in-scope AWS resources (v6.73.0).
- `../schemas/openstack-subset.json`: in-scope OpenStack resources (v3.4.0). Roadmap reference only.

Regenerate (from the repo root):
```bash
./scripts/fetch-corpus.sh
mkdir -p corpus/schemas/tf && cp scripts/schema-dump/main.tf corpus/schemas/tf/
cd corpus/schemas/tf && podman run --rm -v "$PWD":/w:Z -w /w docker.io/hashicorp/terraform:1.9.8 init
podman run --rm -v "$PWD":/w:Z -w /w docker.io/hashicorp/terraform:1.9.8 providers schema -json > ../providers-schema.json
cd ../../.. && python3 -I scripts/extract_schemas.py corpus/schemas/providers-schema.json docs/schemas
```
Docker needs root on this machine, podman works rootless.

## Corpus (`corpus/`, gitignored)
| Path | Use |
|---|---|
| `leaseweb/terraform-provider-leaseweb` | `docs/`, `examples/`: ground truth and few-shot examples for the translator |
| `leaseweb/remerge-terraform-modules` | only real-world Leaseweb usage found on GitHub |
| `aws/terraform-provider-aws` | sparse: `examples/` + docs for in-scope resources |
| `aws/learn-terraform-{resources,rds,import}` | small tutorial stacks |
| `aws/futurice-terraform-examples` | varied examples |
| `aws/terraform-aws-{vpc,ec2-instance,security-group,alb,rds,s3-bucket}` | popular modules |
| `tools/former2` | reference for raw data shape only (not a dependency) |

## Not yet read
- https://developer.leaseweb.com/api-docs/publiccloud_v1.html: human API reference, too large for the fetcher. `leaseweb-api.md` was built from the SDK instead.
- AWS price data: static `data/aws_prices.json` for the supported types is enough for the MVP.
