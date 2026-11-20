---
name: assess-security-posture
description: Scores the security posture of a scanned account per area, before and after the Leaseweb migration, and lists what is reachable from the internet. Use it to compute, change or explain the "Security posture" section.
---

# Assess security posture

Part of: sovereign-shift. Code: `sovereign_shift/assess/posture.py`, `sovereign_shift/assess/common.py`. Checks: `sovereign_shift/graph/security.py`.

## Inputs
`inventory.json`, `graph.json`, `findings.json` (from the graph step), `mapping.json` (its `fixes` say which findings the migration removes).

## Rubric
- Areas and the findings that count in them:
  - Network exposure: SG-001, SG-002, SG-003, SG-004, SG-005, NET-001, ELB-001, EC2-003, RDS-001.
  - Data protection: S3-001, S3-002, S3-003, S3-004, RDS-002, EC2-002.
  - Access and identity: IAM-001, IAM-002, EC2-001.
  - Availability: RDS-003, RDS-004.
- Each area starts at 100 and loses points per finding: critical 40, high 20, medium 8, low 3, info 0. Floor at 0.
- "After migration" removes the findings listed in the mapping entry's `fixes` for that resource.
- Overall = average of the assessed areas. Grades: A 90+, B 75+, C 60+, D 40+, F below.
- An area is "not assessed" when the scan has no data for it (for example no IAM data). Never score it 100 by default.

## Exposure
- Today: instances with a public IP and a security group open to `0.0.0.0/0` or `::/0`, publicly accessible databases, internet-facing load balancers, public buckets.
- After: every Leaseweb instance has a public IP, so only the ports the translated groups still open to the world count, plus load balancers and buckets.

## Output
`assessment.json` -> `posture`: `overall` (before, after, grades), `domains`, `not_assessed`, `findings` (with `domain`, `fixed_by_migration`), `exposure.before/after`.

## Pitfalls
- Only mark a finding fixed when the translator really changed it (`fixes`), never because a resource "will be rebuilt".
- Unencrypted storage and public buckets are not fixed by the move. Say so.
