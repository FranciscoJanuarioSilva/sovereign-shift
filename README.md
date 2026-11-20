# sovereign-shift

Scan a ClickOps AWS or Cloudflare account with read-only credentials and get:

- Leaseweb Terraform, plus the Leaseweb API calls Terraform can't make yet (security groups, load balancer targets),
- a dependency graph,
- an AI-personalised data migration runbook,
- a report (Markdown + JSON) with cost, manual work, security findings and the runbook.

Docs: [PLAN.md](PLAN.md) (product and plan), [AGENTS.md](AGENTS.md) (for coding agents), [docs/contracts.md](docs/contracts.md) (JSON shapes), [docs/research/](docs/research/README.md) (sourced facts).

## AWS inventory

From the project directory, with Python 3.11 or later:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
sovereign-shift scan --profile sovereign-readonly --region eu-north-1 --out out/
```

Use a configured AWS profile with the [scanner IAM policy](docs/iam-policy.json),
or omit `--profile` to use the standard boto3 credential chain. Repeat `--region`
to select several regions or omit it to scan every enabled region. Route 53 is
global and is scanned once. S3 inventory is limited to buckets in the selected regions.

The scanner lives in `sovereign_shift/scanner/` and writes `out/inventory.json`
using the shared [inventory contract](docs/contracts.md). It uses read-only AWS
calls and fails if a required call is denied. EC2 user data and S3 objects are
never retrieved. Route 53 TXT and other free-form record values are marked with
`values_omitted: true` because they can contain tokens.
Keep the inventory local, as it contains infrastructure metadata including AWS
account IDs and resource tags.

## Cloudflare inventory

Set `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` in the environment or local `.env`. Use account-scoped read permissions for Workers Scripts, Workers KV Storage, D1, Workers R2 Storage, Queues and Workflows, plus Zone Read and DNS Read for the account's zones. Denied operations appear in the inventory and assessment.

```bash
sovereign-shift scan --source cloudflare --out out/cloudflare
sovereign-shift all --source cloudflare --out out/cloudflare
sovereign-shift all --from-snapshot examples/cloudflare-worker/sample_snapshot.json --no-ai --out out/cloudflare-demo
```

The scanner inventories Workers, bindings, cron triggers, Durable Object namespaces, Workflows, Queues, D1 databases, KV namespaces, default-jurisdiction R2 buckets, and DNS zones and records. It reads metadata only. DNS-only A, AAAA and ordinary CNAME records use the Leaseweb DNS generator. Proxied, flattened and other record types go through the alternative assessment. R2 uses the object-storage mapping and a runbook that expects configured `r2:` and `leaseweb:` rclone remotes. Other Worker services and unfamiliar bindings use the existing AI fallback. With `--no-ai`, every discovered resource still appears in the report. Cloudflare usage costs are unpriced.

Run the [seeded demo Worker](examples/cloudflare-worker/README.md) locally or assess its synthetic snapshot offline.

## Downstream pipeline
Install Python 3.11+ and run the downstream stages with scanner and translator artifacts in the same output directory.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
sovereign-shift graph out/inventory.json --out out/
sovereign-shift generate --out out/
sovereign-shift runbook --out out/ --no-ai
sovereign-shift report --out out/
pytest
```

The input follows `docs/contracts.md`. The command writes `graph.json` and
a standalone `graph.html` with inline SVG and a relationship table.
Explicit inventory relations are preserved. Missing targets appear as unresolved
nodes with findings. Database connections are inferred from `uses_security_group`
relations and ingress rules allowing the database port from an instance's group.
These edges describe permitted ingress, with `inferred: true`; routing and egress
still need verification.

Security group properties accept `ingress` rules with `protocol`, `from_port`,
`to_port`, and `source_groups` (a list of group IDs), or boto3 `IpPermissions`.
Database properties use `port` or `endpoint.port` / `endpoint.Port`, with engine
defaults for PostgreSQL and MySQL-compatible engines.
The graph command also writes deterministic security checks to `findings.json`.

Generate reads the inventory, graph and mapping. Instance targets supply
`instance_type`, `image_id` and `root_disk_size`. Load balancers supply
`instance_type`, listeners and target groups supply `protocol` and `port`.
Listener edges point to a load balancer and target group. Target group edges
point to backend instances. DNS targets supply `domain_name`, `name`, `type`,
`ttl` and `content` or a relation to the new address owner.

After applying Terraform, preview the finalization requests:

```bash
terraform -chdir=out/terraform output -json > out/outputs.json
sovereign-shift finalize --out out/ --outputs out/outputs.json --dry-run
```

For live finalization, set `LEASEWEB_TOKEN`, omit `--dry-run` and supply
`--admin-cidr` when referenced. Check the effective default security group after
attachment. Review manual items in the report before deployment.

Runbook defaults are offline. For optional AI notes, omit `--no-ai` and set
`SOVEREIGN_AI_API_KEY`, `SOVEREIGN_AI_MODEL` and optionally `SOVEREIGN_AI_BASE_URL`.

### Leaseweb prices (no API token needed)

`data/leaseweb_catalog.json` is a committed snapshot of the Leaseweb Public Cloud catalog:
all regions, every instance type with its real vCPU, RAM, supported disk kinds and price.
The translator reads it, so **you do not need a Leaseweb token to run an assessment**.
Prices are in EUR for EUR regions (Amsterdam, Frankfurt). Regions that Leaseweb bills in
another currency (London in GBP, ...) show `unknown` instead of a guessed conversion.

- **Your own prices:** if you have contract prices, point `SOVEREIGN_LEASEWEB_CATALOG` at a
  file in the same format and it replaces the snapshot.
- **Refreshing the snapshot (maintainers, needs a token):**
  `LEASEWEB_TOKEN=... python scripts/fetch_leaseweb_catalog.py`, then commit the file.
- **No snapshot at all:** the translator falls back to `data/leaseweb_public_prices.json`
  (public website prices, with proxies marked `*`) and estimates.
- AWS prices: `python scripts/fetch_aws_prices.py --profile sovereign-readonly --region eu-north-1 --inventory out/live/inventory.json` stores real on-demand prices for the scanned region (read-only Pricing API). Without them the report uses approximate prices and stars them. Worked numbers: `docs/cost-assessment.md`.
- The report states which source it used and how old the snapshot is. The total is a
  compute subtotal: storage, traffic, public IPs and load balancers are not included.
- Many newer types (the `5a` and `6a` generations) only offer local NVMe disks. The
  translator picks the disk kind each type supports and notes it in the report.

License: [Apache-2.0](LICENSE).

## Offline demo

Run the full assessment with the synthetic AWS snapshot and the translator:

```bash
sovereign-shift all --from-snapshot testdata/clickops_inventory.json --no-ai --out out/demo
```

Open `out/demo/report.md`. Follow the inferred connection from the VM to PostgreSQL,
the public SSH finding, and the database and bucket migration steps. Prices in the
example are illustrative. Use a dedicated output directory for each assessment.

For a live assessment, run `sovereign-shift all --profile sovereign-readonly --region eu-north-1 --out out/live`.
`all` ends with `publish`, which copies the shareable files to `out/<dir>/public/` with the AWS account id masked. Share only that folder. `inventory.json` is never copied there.
Pass `--mapping FILE` to replay an existing translation. With AI enabled, the report can include a
migration summary and a firewall review. Cost subtotals include only resources with a price.
For post-apply finalization, `--private-network-cidr` supplies the private network range used by load balancer rules.

The CLI loads `.env` from the current directory. Exported environment variables
take precedence. For scans, explicit `--region` options take precedence over
`AWS_REGION`; when both are absent the scanner discovers enabled regions.
The manual GitHub Actions workflow “Verify environment configuration” checks
the repository secret and four variables without printing their values.

### Run in GitHub Actions

Open **Actions → Run migration assessment → Run workflow**. The default demo
uses a synthetic inventory, runs the real translator offline, validates the
generated Terraform, and publishes the assessment as a downloadable artifact.
Enable AI to use the configured OpenRouter settings.

For a live scan, select **aws**, set the repository variable `AWS_REGION`
and configure Actions secrets `AWS_READONLY_ACCESS_KEY_ID` and
`AWS_READONLY_SECRET_ACCESS_KEY` for the scanner role or user. For temporary
credentials also set `AWS_READONLY_SESSION_TOKEN`. Enable publication of
live results only when repository readers may access the infrastructure details.
Deployment and post-apply finalization are separate from the assessment.

## Local dashboard

With the project installed in the virtual environment, run from the repository root:

```bash
.venv/bin/python frontend/serve.py --port 8001
```

Open <http://127.0.0.1:8001>. The dashboard starts empty. **Upload JSON** accepts
an AWS `inventory.json` from the scanner or an existing Sovereign Shift
`report.json`. Inventories are analysed by the local server without AI or cloud
API calls. Existing reports are read directly in the browser. **View demo**
opens the example. Use **Back to report** or **Back to upload** to leave the demo.

After analysing an inventory or opening the demo, use **Terraform** to inspect
and download the generated files and the post-apply `finalize.json`.
**Validate Terraform** runs `terraform init -backend=false` and
`terraform validate` against those files in a temporary directory. The first
step downloads the provider and needs access to the Terraform registry. Use
Terraform on `PATH` or pass `--terraform /path/to/terraform` to the server.
