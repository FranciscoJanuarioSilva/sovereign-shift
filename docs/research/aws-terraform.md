# AWS Terraform format (what we read and compare against)

Provider `hashicorp/aws` v6.73.0 (schema dump 2026-11-20). In-scope schemas are in `docs/schemas/aws-subset.json`. Full docs for each resource are in `corpus/aws/terraform-provider-aws/website/docs/r/`.

We don't parse AWS HCL in the MVP (we scan the live account). This file is reference for the scanner's field names and for golden tests.
Roadmap, not MVP: a path for customers who already have AWS Terraform (`sovereign-shift convert ./infra`), since the mapping is the same.

## HCL basics an agent needs
- Blocks: `terraform {}`, `provider "aws" { region = ... }`, `resource "<type>" "<name>" {}`, `data "<type>" "<name>" {}`, `variable`, `output`, `locals`, `module`.
- References: `aws_subnet.public.id`, `var.x`, `local.y`, `module.vpc.vpc_id`, `data.aws_ami.ubuntu.id`. These are the edges of the graph when parsing HCL.
- Meta-arguments: `count`, `for_each`, `depends_on`, `lifecycle`, `provider`. With `count`/`for_each` one block expands to N resources: evaluate them or keep them as-is in the output.
- Parsing in Python: `python-hcl2` (reads HCL into dicts, loses comments). To be safe with modules, run `terraform show -json` on a plan for the fully expanded resource list.

## In-scope resources and the fields that matter
| Resource | Fields we map |
|---|---|
| `aws_instance` | `ami`, `instance_type`, `subnet_id`, `vpc_security_group_ids`, `key_name`, `user_data`, `root_block_device { volume_size, volume_type, encrypted }`, `associate_public_ip_address`, `tags.Name` |
| `aws_vpc` / `aws_subnet` | `cidr_block`, `availability_zone`, `map_public_ip_on_launch` |
| `aws_security_group` (+ `aws_vpc_security_group_ingress_rule` / `_egress_rule`) | `ingress/egress { from_port, to_port, protocol, cidr_blocks, security_groups }` |
| `aws_ebs_volume` + `aws_volume_attachment` | `size`, `type`, `iops`, `encrypted` |
| `aws_eip` | `instance`, `domain = "vpc"` |
| `aws_lb` | `load_balancer_type` (application/network), `internal`, `subnets`, `security_groups` |
| `aws_lb_listener` | `port`, `protocol`, `certificate_arn`, `default_action { type, target_group_arn }` |
| `aws_lb_target_group` | `port`, `protocol`, `health_check { path, port, protocol, matcher }` |
| `aws_db_instance` | `engine`, `engine_version`, `instance_class`, `allocated_storage`, `multi_az`, `publicly_accessible`, `storage_encrypted`, `backup_retention_period`, `db_subnet_group_name`, `vpc_security_group_ids` |
| `aws_s3_bucket` (+ `_policy`, `_public_access_block`, `_versioning`, `_server_side_encryption_configuration`) | name, policy, public access, versioning |
| `aws_route53_zone` / `aws_route53_record` | `name`, `type`, `ttl`, `records`, `alias { name, zone_id }` |
| `aws_key_pair` | `public_key` |

## Reference repos in `corpus/aws/` (fetch with `scripts/fetch-corpus.sh`)
| Repo | Why |
|---|---|
| `terraform-provider-aws/examples/{two-tier,networking,eip,elb,ecs-alb,rds,asg}` | small plain-resource stacks, the closest to a scanned click-ops account |
| `learn-terraform-resources`, `learn-terraform-rds`, `learn-terraform-import` | HashiCorp tutorials, `import` is the click-ops-to-IaC story |
| `futurice-terraform-examples` | older but varied (static sites, lambdas, etc.) |
| `terraform-aws-{vpc,ec2-instance,security-group,alb,rds,s3-bucket}` | the most-used modules, for the "already Terraform" path |
