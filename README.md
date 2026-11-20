# sovereign-shift

Scan a ClickOps AWS account with read-only credentials and get:

- Leaseweb Terraform, plus the Leaseweb API calls Terraform can't make yet (security groups, load balancer targets),
- a dependency graph,
- an AI-personalised data migration runbook,
- a report (Markdown + JSON) with cost, manual work, security findings and the runbook.

Docs: [PLAN.md](PLAN.md) (product and plan), [AGENTS.md](AGENTS.md) (for coding agents), [docs/contracts.md](docs/contracts.md) (JSON shapes), [docs/research/](docs/research/README.md) (sourced facts).

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
`to_port`, and `security_groups` (a list of group IDs), or boto3 `IpPermissions`.
Database properties use `port` or `endpoint.port` / `endpoint.Port`, with engine
defaults for PostgreSQL and MySQL-compatible engines. Security findings beyond
unresolved dependencies belong to subsequent implementation work.

License: [Apache-2.0](LICENSE).
