# Scanning a click-ops AWS account

Step 1 of the pipeline: get a full inventory with read-only credentials.

## Credentials
- Ask the customer for an IAM user or role with the AWS managed policy `ReadOnlyAccess` (arn:aws:iam::aws:policy/ReadOnlyAccess). `SecurityAudit` alone misses some describe calls, so recommend both.
- Better for real customers: a cross-account role with an `ExternalId` and `sts:AssumeRole`, so no long-lived keys are shared.
- Never store keys, never log them, never send them to an LLM. Short-lived STS creds only in memory.
- Scan every enabled region (`ec2.describe_regions(AllRegions=False)`): click-ops users often forget resources in other regions.

## Option A: Former2 (chosen dependency)
Repo: https://github.com/iann0036/former2 (MIT), local copy in `corpus/tools/former2`.

Status (checked 2026-11-20):
- Not archived or deprecated. Low maintenance: last commits July 2026 (region adds), CLI code last changed July 2024, 182 open issues.
- The README calls the CLI "experimental, use at your own risk".
- Depends on `aws-sdk` v2 for JS (AWS end-of-support Sept 2025). It still runs but gets no fixes.
- Covers 148 service modules. Terraform output covers almost all our in-scope types, except `aws_db_instance`, which is missing from its TF output (CloudFormation `AWS::RDS::DBInstance` is covered). The raw data does include RDS (`f2type: 'rds.instance'`), which is why we consume raw data, not its HCL.

Run (Docker, since node/npm isn't installed on dev machines here; use podman if docker needs root):
```bash
docker build https://github.com/iann0036/former2.git#master:cli -t former2:local
docker run --rm -t -v "$PWD":/former2 -v ~/.aws:/root/.aws:ro former2:local generate \
  --output-raw-data raw.json \
  --output-terraform aws.tf \
  --region eu-west-1 \
  --exclude-services "CloudWatch,KMS"
```
Useful flags: `--services`, `--exclude-services`, `--search-filter`, `--regex-filter`, `--profile`, `--region`, `--include-default-resources`, `--sort-output`.

Raw output shape (from `cli/main.js`): a JSON array of
```json
{ "f2id": "...", "f2type": "ec2.instance", "f2data": { /* the original describe_* item */ }, "f2region": "eu-west-1" }
```
`f2data` is the unmodified SDK response, so our IR adapter maps the same fields as boto3 would. Verify the exact keys (`f2region` etc.) in spike 0.

Known risks to check in spike 0: one region per run (loop over regions), errors are swallowed (`updateDatatable failed` only warns), default VPC/SG resources are skipped unless `--include-default-resources` (click-ops users often run everything in the default VPC, so we need this flag on).

## Option B: native boto3 (fallback, and for the core services)
Read-only calls per service. All are paginated, so use `get_paginator`.

| Service | Calls | Gives us |
|---|---|---|
| EC2 | `describe_instances`, `describe_images` (for the AMI OS), `describe_volumes`, `describe_addresses`, `describe_key_pairs`, `describe_instance_types` (vCPU/RAM) | VMs, disks, EIPs |
| VPC | `describe_vpcs`, `describe_subnets`, `describe_route_tables`, `describe_internet_gateways`, `describe_nat_gateways`, `describe_security_groups`, `describe_security_group_rules`, `describe_network_interfaces` | network graph, firewall rules |
| ELBv2 | `describe_load_balancers`, `describe_listeners`, `describe_target_groups`, `describe_target_health`, `describe_rules` | LB -> TG -> instance edges |
| RDS | `describe_db_instances`, `describe_db_subnet_groups`, `describe_db_clusters` | DBs, their SGs and subnets |
| S3 | `list_buckets`, `get_bucket_location`, `get_bucket_policy_status`, `get_public_access_block`, `get_bucket_encryption`, `get_bucket_versioning` | buckets + public/encryption findings |
| Route 53 | `list_hosted_zones`, `list_resource_record_sets` | DNS records -> LB/EIP edges |
| IAM (report only) | `get_account_summary`, `list_users`, `list_access_keys`, `get_credential_report` | security findings |
| Cost | Cost Explorer `get_cost_and_usage` (needs `ce:GetCostAndUsage`, in ReadOnlyAccess) | real monthly AWS cost per service |
| Pricing | `pricing.get_products` (us-east-1 endpoint) | list price per instance type, as a fallback |

Testing without an account: `moto` mocks all of the above for boto3. It does not help with Former2, which needs real endpoints.

## Dependency edges to build (step 2)
| From | To | Field |
|---|---|---|
| instance | subnet, VPC | `SubnetId`, `VpcId` |
| instance | security groups | `SecurityGroups[].GroupId` |
| instance | volumes | `BlockDeviceMappings[].Ebs.VolumeId` |
| instance | EIP | `describe_addresses` -> `InstanceId` |
| instance | key pair | `KeyName` |
| SG rule | SG | `UserIdGroupPairs[].GroupId` (SG-to-SG trust, e.g. web -> db) |
| subnet | route table -> IGW / NAT | `Associations[].SubnetId`, `Routes[].GatewayId/NatGatewayId` (public vs private subnet) |
| LB | subnets, SGs | `AvailabilityZones[].SubnetId`, `SecurityGroups` |
| listener | LB, TG | `LoadBalancerArn`, `DefaultActions[].TargetGroupArn` |
| TG | instances | `describe_target_health` -> `Target.Id` |
| RDS | subnet group, SGs | `DBSubnetGroup`, `VpcSecurityGroups` |
| Route 53 record | LB / IP / CloudFront | `AliasTarget.DNSName`, `ResourceRecords` matched against LB DNS names and EIPs |
| instance -> RDS (inferred) | SG rule on the DB SG allowing the instance's SG on 5432/3306 | this is the "who talks to the DB" edge click-ops users forget |
