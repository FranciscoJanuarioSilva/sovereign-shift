# Scanning a click-ops AWS account

Step 1 of the pipeline: get a full inventory with read-only credentials.

## Credentials
- Ask the customer for an IAM user or role with the AWS managed policy `ReadOnlyAccess` (arn:aws:iam::aws:policy/ReadOnlyAccess). `SecurityAudit` alone misses some describe calls, so recommend both.
- Better for real customers: a cross-account role with an `ExternalId` and `sts:AssumeRole`, so no long-lived keys are shared.
- Never store keys, never log them, never send them to an LLM. Short-lived STS creds only in memory.
- Click-ops users often forget resources in other regions, so offer `--all-regions` (see below).

## Not used: Former2 and other AWS-to-Terraform tools
Decision: we write our own boto3 scanner. Former2, aws2tf, Terraformer and terracognita all output AWS-provider Terraform, which is not what we need, and each has a blocker (Terraformer archived Mar 2026, terracognita pinned to AWS provider 4.9.0, Former2 browser-first with an "experimental" CLI on the end-of-support JS SDK v2, aws2tf needs Terraform 1.12 + AWS CLI v2 + jq and emits HCL, not an inventory).
Former2 stays in `corpus/tools/former2` as a reference for what raw describe data looks like (`f2data` is the unmodified SDK response). Note from reading it: default VPC/SG resources are easy to skip by accident, and click-ops users often run everything in the default VPC, so our scanner must include them.

## Our scanner: boto3
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

Testing without an account: `moto` mocks all of the above for boto3.

Regions: by default scan only `--region`. `--all-regions` loops over `ec2.describe_regions(AllRegions=False)`, slower but catches forgotten resources.

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
