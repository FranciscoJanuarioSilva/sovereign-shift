# sovereign-shift

Scan a ClickOps AWS account with read-only credentials and get:

- Leaseweb Terraform, plus the Leaseweb API calls Terraform can't make yet (security groups, load balancer targets),
- a dependency graph,
- an AI-personalised data migration runbook,
- a report (Markdown + JSON) with cost, manual work, security findings and the runbook.

Docs: [PLAN.md](PLAN.md) (product and plan), [AGENTS.md](AGENTS.md) (for coding agents), [docs/contracts.md](docs/contracts.md) (JSON shapes), [docs/research/](docs/research/README.md) (sourced facts).

Build and run instructions will go here once the package exists.

License: [Apache-2.0](LICENSE).
