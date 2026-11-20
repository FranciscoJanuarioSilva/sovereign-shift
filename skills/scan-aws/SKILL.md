---
name: scan-aws
description: Runs or changes the read-only AWS scanner that turns an account into inventory.json (EC2, VPC, security groups, ELB, RDS, S3, Route 53). Use it when scanning a live AWS account or adding a resource type to the scan.
---

# Scan AWS

Part of: sovereign-shift. Code: `sovereign_shift/scanner/aws.py`. Facts: `docs/research/aws-scanning.md`, `docs/research/environment.md`. Policy: `docs/iam-policy.json`.

## Steps
```bash
sovereign-shift scan --profile sovereign-readonly --region eu-north-1 --out out/live
```
- Credentials: an IAM user or role with `ReadOnlyAccess` only. The product never uses a write profile.
- The demo account's SCP only allows `eu-north-1`: treat AccessDenied per region or service as "denied", record it and continue.

## Rules
- Output follows the inventory contract in `docs/contracts.md`: neutral resource types (`ec2_instance`, `db_instance`, `s3_bucket`, ...), `properties`, `relations` (the graph is built from them).
- Never store secrets: `user_data` only as a hash and length, public keys are fine.
- Skip AWS-managed Elastic IPs (ALB and RDS ones), they aren't the customer's.
- Every new property the translator or checks rely on must come from a read-only call.

## Pitfalls
- Security group rules: write `source_groups` (the graph and translator read it).
- Root volumes appear both inside the instance and as `ebs_volume`: mark `root: true`.
