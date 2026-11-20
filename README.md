# sovereign-shift

Scan a ClickOps AWS account with read-only credentials and get:

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
sovereign-shift scan --profile readonly --region eu-west-1 --out out/
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
