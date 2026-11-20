# Usage reference

Everything the [README](../README.md) leaves out: each command, its inputs, prices and CI. The JSON shapes between steps are in [contracts.md](contracts.md).

The CLI loads `.env` from the current directory. Exported environment variables take precedence. Copy `.env.example` to start.

## Scan an AWS account

```bash
sovereign-shift scan --profile sovereign-readonly --region eu-north-1 --out out/
```

- Use a configured AWS profile with the [scanner IAM policy](iam-policy.json), or omit `--profile` to use the standard boto3 credential chain.
- Repeat `--region` to select several regions, or omit it to scan every enabled region. Explicit `--region` options take precedence over `AWS_REGION`.
- Route 53 is global and is scanned once. S3 inventory is limited to buckets in the selected regions.
- A region or service denied by IAM or an SCP is listed under `denied` in the inventory and printed as a warning, and the scan carries on.
- Calls are read-only. EC2 user data and S3 objects are never retrieved. Route 53 TXT and other free-form record values are marked `values_omitted: true`, because they can contain tokens.
- Keep `inventory.json` local: it holds infrastructure metadata, including the AWS account ID and tags.

## Scan a Cloudflare account

Set `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` in the environment or `.env`. Use account-scoped read permissions for Workers Scripts, Workers KV Storage, D1, Workers R2 Storage, Queues and Workflows, plus Zone Read and DNS Read for the account's zones. Denied operations appear in the inventory and assessment.

```bash
sovereign-shift scan --source cloudflare --out out/cloudflare
sovereign-shift all --source cloudflare --out out/cloudflare
sovereign-shift all --from-snapshot examples/cloudflare-worker/sample_snapshot.json --no-ai --out out/cloudflare-demo
```

The scanner inventories Workers, bindings, cron triggers, Durable Object namespaces, Workflows, Queues, D1 databases, KV namespaces, default-jurisdiction R2 buckets, and DNS zones and records. It reads metadata only.
- DNS-only A, AAAA and ordinary CNAME records use the Leaseweb DNS generator. Proxied, flattened and other record types go through the alternative assessment.
- R2 uses the object-storage mapping and a runbook that expects configured `r2:` and `leaseweb:` rclone remotes.
- Other Worker services and unfamiliar bindings use the AI fallback. With `--no-ai`, every discovered resource still appears in the report.
- Cloudflare usage costs are unpriced.

The [seeded demo Worker](../examples/cloudflare-worker/README.md) can run locally.

## Scan an Azure subscription

Not verified against a live subscription yet: the mapping is tested with an SDK-shaped sample (`testdata/azure_sdk_sample.json`) and mocks. See [azure.md](azure.md).

```bash
pip install -e '.[azure]'                     # the Azure SDK, only for live scans
export AZURE_SUBSCRIPTION_ID=...              # plus Reader credentials for DefaultAzureCredential
sovereign-shift all --source azure --out out/azure
sovereign-shift all --from-snapshot testdata/azure_inventory.json --no-ai --out out/azure-sample   # offline sample
python scripts/fetch_azure_prices.py --inventory out/azure/inventory.json   # real VM prices, public API, no key
```

## Scan a Google Cloud project

Not verified against a live project yet: the scanner is tested by replaying made-up REST responses (`testdata/gcp_api_responses.json`). See [gcp.md](gcp.md).

```bash
pip install -e '.[gcp]'                       # google-auth, for application default credentials
gcloud auth application-default login --impersonate-service-account=<viewer sa>
sovereign-shift all --source gcp --project <project-id> --out out/gcp
sovereign-shift all --from-snapshot testdata/gcp_inventory.json --no-ai --out out/gcp-sample   # offline sample
```

Instead of google-auth, `GCP_ACCESS_TOKEN=$(gcloud auth print-access-token --impersonate-service-account=<viewer sa>)` works too. The project id can also come from `GCP_PROJECT_ID`. The scan covers every region of the project. Use a service account with the Viewer role only. Disabled APIs and missing permissions show up under "Scan coverage" in the report. Google list prices aren't fetched, so the source cost column is unknown.

## Run the steps one by one

```bash
sovereign-shift graph out/inventory.json --out out/
sovereign-shift translate out/inventory.json --out out/
sovereign-shift generate --out out/
sovereign-shift assess --out out/
sovereign-shift runbook --out out/ --no-ai
sovereign-shift report --out out/
```

`all` runs them in order. Pass `--mapping FILE` to replay an existing translation. `all` ends with `publish`, which copies the shareable files to `out/<dir>/public/` with the AWS account id masked. Share only that folder. `inventory.json` is never copied there. Use a dedicated output directory for each assessment.

### graph
Writes `graph.json`, a standalone `graph.html` (inline SVG and a relationship table) and `findings.json` (deterministic security checks, see [research/security-rules.md](research/security-rules.md)).
- Explicit inventory relations are preserved. Missing targets appear as unresolved nodes with findings.
- Database connections are inferred from `uses_security_group` relations and ingress rules that allow the database port from an instance's group. These edges describe permitted ingress and carry `inferred: true`. Routing and egress still need checking.
- Security group properties accept `ingress` rules with `protocol`, `from_port`, `to_port` and `source_groups` (a list of group IDs), or boto3 `IpPermissions`. Database properties use `port` or `endpoint.port` / `endpoint.Port`, with engine defaults for PostgreSQL and MySQL-compatible engines.

### translate
Rules map every resource to a Leaseweb target. The AI is only asked about resources no rule covers. Details: [translator.md](translator.md).

### generate
Reads the inventory, graph and mapping, and writes `terraform/main.tf` and `finalize.json`.
- Instance targets supply `instance_type`, `image_id` and `root_disk_size`. Load balancers supply `instance_type`. Listeners and target groups supply `protocol` and `port`. Listener edges point to a load balancer and a target group. Target group edges point to backend instances. DNS targets supply `domain_name`, `name`, `type`, `ttl` and `content`, or a relation to the new address owner.
- A self-hosted database (from RDS) gets its own instance, with cloud-init installing the same major engine version (PostgreSQL from the PGDG repository). Its data moves with the runbook.
- Every instance's cloud-init brings up the private network NIC with DHCP whatever its name, and waits for it, because the provider attaches it after launch.

### finalize (after `terraform apply`)
Security groups and load balancer targets go through the Leaseweb API, because the provider has no resources for them ([research/leaseweb-api.md](research/leaseweb-api.md)).

```bash
terraform -chdir=out/terraform output -json > out/outputs.json
sovereign-shift finalize --out out/ --outputs out/outputs.json --dry-run
```

For live finalization, set `LEASEWEB_TOKEN`, omit `--dry-run`, and supply `--admin-cidr` when referenced. `--private-network-cidr` supplies the private network range used by load balancer rules. Check the effective default security group after attachment, and review the manual items in the report before deployment.

### assess
Writes `assessment.json`: security posture (scores before and after the migration, internet exposure), the risk register with a readiness verdict, performance and scaling. Rules only, no AI, so `--no-ai` gives the full result. How each score works: [assessment.md](assessment.md) and the `skills/assess-*` files.

### runbook and report
Runbook defaults are offline. For AI notes and the report's summary and firewall review, omit `--no-ai` and set `SOVEREIGN_AI_API_KEY`, `SOVEREIGN_AI_MODEL` and optionally `SOVEREIGN_AI_BASE_URL`. On OpenRouter the client pins inference to Mistral with data collection denied (`SOVEREIGN_AI_PROVIDER_ONLY` changes the provider).

## Prices

`data/leaseweb_catalog.json` is a committed snapshot of the Leaseweb Public Cloud catalog: all regions, and every instance type with its real vCPU, RAM, supported disk kinds and price. The translator reads it, so **an assessment needs no Leaseweb token**.
- Prices are in EUR for EUR regions (Amsterdam, Frankfurt). Regions that Leaseweb bills in another currency (London in GBP, ...) show `unknown` instead of a guessed conversion.
- Your own prices: point `SOVEREIGN_LEASEWEB_CATALOG` at a file in the same format, and it replaces the snapshot.
- Refreshing the snapshot (needs a token): `LEASEWEB_TOKEN=... python scripts/fetch_leaseweb_catalog.py`, then commit the file.
- No snapshot at all: the translator falls back to `data/leaseweb_public_prices.json` (public website prices, proxies marked `*`) and estimates.
- AWS prices: `python scripts/fetch_aws_prices.py --profile sovereign-readonly --region eu-north-1 --inventory out/live/inventory.json` stores real on-demand prices for the scanned region (read-only Pricing API). Without them the report uses approximate prices and marks them with a star. Worked numbers: [cost-assessment.md](cost-assessment.md).
- The report states which source it used and how old the snapshot is. The total is a compute subtotal: storage, traffic, public IPs and load balancers are not included.
- Many newer types (the `5a` and `6a` generations) only offer local NVMe disks. The translator picks the disk kind each type supports and notes it in the report.

## Local dashboard

With the project installed in the virtual environment, run from the repository root:

```bash
.venv/bin/python frontend/serve.py --port 8001
```

Open <http://127.0.0.1:8001>. The dashboard starts empty. **Upload JSON** accepts an AWS `inventory.json` from the scanner or an existing Sovereign Shift `report.json`. Inventories are analysed by the local server without AI or cloud API calls. Existing reports are read directly in the browser. **View demo** opens the example. Use **Back to report** or **Back to upload** to leave the demo.

After analysing an inventory or opening the demo, use **Terraform** to inspect and download the generated files and the post-apply `finalize.json`. **Validate Terraform** runs `terraform init -backend=false` and `terraform validate` against those files in a temporary directory. The first step downloads the provider and needs access to the Terraform registry. Use Terraform on `PATH` or pass `--terraform /path/to/terraform` to the server.

## GitHub Actions

Open **Actions → Run migration assessment → Run workflow**. The default run uses the synthetic inventory, runs the real translator offline, validates the generated Terraform, and publishes the assessment as a downloadable artifact. Enable AI to use the configured OpenRouter settings.

For a live scan, select **aws**, set the repository variable `AWS_REGION`, and configure the Actions secrets `AWS_READONLY_ACCESS_KEY_ID` and `AWS_READONLY_SECRET_ACCESS_KEY` for the scanner user or role (and `AWS_READONLY_SESSION_TOKEN` for temporary credentials). For Azure, select **azure** and set the repository variables `AZURE_SUBSCRIPTION_ID`, `AZURE_TENANT_ID` and `AZURE_CLIENT_ID` and the secret `AZURE_READER_CLIENT_SECRET` for a service principal with the Reader role only (not verified against a live subscription yet). For Cloudflare, select **cloudflare-demo** (the synthetic Worker snapshot) or **cloudflare**, with the repository variable `CLOUDFLARE_ACCOUNT_ID` and the secret `CLOUDFLARE_API_TOKEN`. Enable publication of live results only when repository readers may see the infrastructure details. Deployment and finalization are separate from the assessment.

The manual workflow "Verify environment configuration" checks the repository secret and four variables without printing their values.
