---
name: assess-risk
description: Builds the risk register (likelihood x impact) for the current infrastructure and for the migration, re-scores it after the move and gives a readiness verdict. Use it to compute, change or explain the "Risk assessment" section.
---

# Assess risk

Part of: sovereign-shift. Code: `sovereign_shift/assess/risk.py`. Depends on: assess-security-posture.

## Inputs
`graph.json` (blast radius), the posture result (findings, exposure), `mapping.json` (migration risks).

## Rubric
- Score = likelihood (1-5) x impact (1-5). Rating bands: critical 20+, high 12+, medium 6+, low below.
- Likelihood of a finding-based risk: critical 4, high 3, medium 2, low 1. Plus 1 when the resource is reachable from the internet, but only for security and data risks (exposure doesn't make an outage more likely).
- Impact: database 4, bucket, server, load balancer, target group and security group 3, anything else 2. Plus 1 when 2 or more resources depend on it, plus 1 more at 5 or more (blast radius = ancestors in the dependency graph).
- After migration: a risk the migration fixes is "resolved". Others are re-scored with the exposure after the move.

## Risk sources
- Security and data: every finding except info.
- Availability: a target group with one server (R-SPOF), a public server outside the load balancer.
- Migration, with a phase:
  - cutover (one-time): M-DATA (data copy), M-IP (public IP changes), M-TLS (certificate re-issue), M-DNS (zone move), M-ARM (ARM to x86), M-AI (AI-suggested replacement), M-UNS (no equivalent).
  - lasting: M-DB (self-managed database), M-NVME (non-replicated local disk), M-FW (Leaseweb default security group allows all until finalize).

## Verdicts
- Highest risk today: worst rating of the non-migration risks.
- Highest risk after the migration: worst `rating_after` of unresolved risks plus lasting migration risks. Cutover risks don't count, they end with the move.
- Readiness: "not ready" if any migration risk is critical, "ready with conditions" if any is high, else "ready".

## Output
`assessment.json` -> `risk`: `overall`, `heatmap` (rows likelihood 5 to 1, columns impact 1 to 5), `top_today`, `top_after_migration`, `register`.

## Pitfalls
- Don't invent probabilities or money figures. The scores are a ranking aid, say that if asked.
- Keep this file and `risk.py` in sync (`tests/test_skills.py` checks the ids and bands).
