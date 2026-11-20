# Our environment (checked 2026-11-20, 11:10)

No secrets in this file. Credentials live in `~/.aws/credentials` (profile `sovereign-readonly`) and in `.env` (gitignored, template in `.env.example`). Install the secret check before committing: `ln -sf ../../scripts/check-secrets.sh .git/hooks/pre-commit`.

## AWS demo account
Two profiles in `~/.aws`:
- `sovereign-readonly` (user `sovereign-scanner-ro`): the only one the scanner may use.
- `sovereign-admin` (user `sovereign-shift-agents`, write access): only for `scripts/demo-account/demo_account.py`. Never in product code. It can't read IAM.

Read-only user details:
- IAM user `sovereign-scanner-ro` with only the managed policy `ReadOnlyAccess`. No inline policies, no groups, no permissions boundary.
- Writes are refused: `ec2:CreateSecurityGroup` with `DryRun` gives `UnauthorizedOperation`, and `iam:SimulatePrincipalPolicy` denies `RunInstances`, `PutObject`, `DeleteBucket`, `CreateAccessKey`, `DeleteDBInstance`.
- **The account is in an AWS Organization whose SCP only allows `eu-north-1` (Stockholm).** Every regional call elsewhere fails with `UnauthorizedOperation`. Global calls work (`s3:ListAllMyBuckets`, IAM, `ce:GetCostAndUsage`, `pricing:GetProducts`).
  - Scanner rule: catch `UnauthorizedOperation` / `AccessDenied` per region and per service, record the region as "denied" in `inventory.json`, keep going. `--all-regions` must not crash.
  - Region mapping for the demo: AWS `eu-north-1` (Stockholm) -> Leaseweb `eu-west-3` (Amsterdam).
- **The account is on the AWS free plan.** Only free-tier instance types launch. Others fail with `InvalidParameterCombination: The specified instance type is not eligible for Free Tier`, and only on a real launch (`DryRun` says it would succeed). `t3.large` fails, `t3.micro` and `m7i-flex.large` work.

### Demo setup (built 2026-11-20 ~11:30 by `scripts/demo-account/demo_account.py up`)
Everything tagged `sovereign-shift-demo=true`, `env=prod`, in the default VPC (`172.31.0.0/16`) of `eu-north-1`. Teardown: `demo_account.py down`. Resource ids are in `scripts/demo-account/state.json` (gitignored). The SSH key is at `~/.ssh/sovereign-demo-ops-key.pem`.

| Resource | Details | Finding on purpose |
|---|---|---|
| `web-1` | `t3.micro` (2 vCPU / 1 GiB), Ubuntu 22.04, nginx via `user_data`, IMDSv1 allowed, Elastic IP `web-1-ip` | EC2-001; maps to an over-provisioned `lsw.*.large` |
| `web-2` | `m7i-flex.large` (2 vCPU / 8 GiB), same setup, no EIP | EC2-001 |
| `web-1-uploads` | extra 20 GiB gp3 EBS on `web-1`, unencrypted | EC2-002, extra volume (no Leaseweb volume resource) |
| root volumes | 30 GiB gp3, unencrypted | EC2-002 |
| `web-sg` | 80, 443 and **22 from 0.0.0.0/0** | SG-001 |
| `db-sg` | 5432 from `web-sg` (SG-to-SG edge) **and 5432 from 0.0.0.0/0** | SG-002 |
| `alb-sg` | 80 from 0.0.0.0/0 | |
| `web-alb` | internet-facing ALB, HTTP:80 listener (no HTTPS), target group `web-tg` with both web instances, both healthy | ELB-001 |
| `orders-db` | RDS PostgreSQL 18.3, `db.t4g.micro`, 20 GiB, database `orders`, **public, unencrypted, no backups**. Master password managed by AWS in Secrets Manager | RDS-001, RDS-002, RDS-003 |
| `orders-shop-assets-<random>` | S3 bucket with a public-read policy, public access block removed, one `index.html` | S3-001, S3-002 |
| `ops-key` | ed25519 key pair | |

Mixed instance sizes behind one ALB are realistic for ClickOps and exercise both mapping rules (tiny -> over-provisioned, normal -> same size).

Scanner gotchas found while building:
- `describe_addresses` also returns **AWS-managed Elastic IPs** (2 for the ALB, 1 for the public RDS), marked `ServiceManaged: alb|rds`. Skip them: only addresses without `ServiceManaged` are customer EIPs.
- Leave the RDS-managed secret in Secrets Manager out of scope (it's created by RDS, not by the customer).

## AI
- OpenRouter key works on the global host: limit USD 100, usage 0.
- **`eu.openrouter.ai` is refused for completions**: "Regional routing requires a Business or Enterprise plan" (HTTP 403). Listing keys and models works there, which is misleading.
- Working setup: `https://openrouter.ai/api/v1` with provider routing pinned to Mistral:
  ```json
  "provider": {"only": ["mistral"], "allow_fallbacks": false, "data_collection": "deny"}
  ```
  Tested with strict `json_schema` output: `mistralai/mistral-small-2603` 0.8 s, USD 0.000015 per call; `mistralai/mistral-medium-3-5` 0.8 s, USD 0.00018. Both returned valid JSON.
- Pitch wording, honestly: "inference runs at Mistral, a European company; requests are routed through OpenRouter". Not "data never leaves the EU", since OpenRouter itself is a US service.
- Models: `mistral-small-2603` for translator and explainer, `mistral-medium-3-5` for the runbook agent and the reviewer.

## Team VM (Leaseweb)
- Hosted by Leaseweb Netherlands (AS60781). Ubuntu 26.04.1 LTS, 32 vCPU, 125 GiB RAM, 86 GB free disk, no GPU.
- Installed: Python 3.14, git, curl. **Missing: Terraform, Docker, Podman.** Install Terraform from the HashiCorp apt repo or the release zip.
- Network: one interface `enp3s0` with a private `192.168.1.x/24` address, MAC prefix `fa:16:3e` (OpenStack). So this VM is on the **new OpenStack-based Leaseweb platform**: private IP by default, public IP via NAT/floating IP. The KB's `eth1` private network instructions are for the old platform.
- Ollama would work on CPU here (32 cores, 125 GiB) as an offline fallback, but OpenRouter is the default.

## Still missing
- **A Leaseweb API token** (the VM login is not one). Without it: no `GET /instanceTypes` prices, no `terraform apply`, finalize only in `--dry-run`.
