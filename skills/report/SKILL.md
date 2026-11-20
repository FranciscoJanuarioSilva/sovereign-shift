---
name: report
description: Builds report.md and report.json, covering the executive summary, dependencies, security posture, risk, cost, performance, scaling, migration work, findings and runbook, plus masked copies for sharing. Use it when changing what the report shows or how.
---

# Report

Part of: sovereign-shift. Code: `sovereign_shift/report/build.py`, `sovereign_shift/report/sections.py`, `sovereign_shift/publish.py`.

## Rules
- Section order: executive summary, dependencies, security posture, risk assessment, cost, performance, scaling, migration work, finalize, findings, AI summary and firewall review, runbook, Terraform files.
- Names, never raw ARNs. The account id is masked in the report, and `publish` writes masked copies of every shareable file to `out/<dir>/public/` (`inventory.json` is never shared).
- Every AI sentence is marked `ai-suggested`. Re-read AI text before it goes on a slide: it has contradicted itself before.
- Tables must start after a blank line or GitHub won't render them (`join_markdown`).
- Say what was not assessed and what the cost total excludes.
