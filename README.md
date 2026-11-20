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

## Dependency graph

The dependency graph stage is implemented. Install Python 3.11+ and run:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
sovereign-shift graph path/to/inventory.json --out out/
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
defaults for PostgreSQL and MySQL-compatible engines. Security findings beyond
unresolved dependencies belong to subsequent implementation work.

License: [Apache-2.0](LICENSE).
