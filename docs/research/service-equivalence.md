# AWS -> Leaseweb equivalence

This feeds `mappings/*.yaml`. Status: `full` = generated automatically, `partial` = generated + manual note, `manual` = report only (AI may propose an alternative).
Target A = `leaseweb/leaseweb` provider. Target B = `openstack` provider (new NL platform, pending the Keystone URL from Leaseweb). Target C = cloud-init on an instance.

| AWS | Leaseweb target | Status | Notes |
|---|---|---|---|
| EC2 instance | A `leaseweb_public_cloud_instance` | full | type via the table below, OS via AMI -> image id, `Name` tag -> `reference` |
| EC2 large/steady (>= 16 vCPU, 24/7) | A `leaseweb_dedicated_server` + `_installation` | partial | server must be ordered first, cheaper at scale (cost report shows both) |
| EBS root volume | A `root_disk_size` + `root_disk_storage_type = "CENTRAL"` | full | max 1000 GB |
| EBS extra volumes | B `openstack_blockstorage_volume_v3` | partial | no volume resource in the Leaseweb provider. Without B: bigger root disk + manual data copy |
| EIP | public IP on the instance (A), or B `openstack_networking_floatingip_v2` | partial | IP address changes, so DNS must be updated (we generate the records) |
| Key pair | A `ssh_key` on the instance | full | AWS never exposes private keys; the public key comes from `describe_key_pairs(IncludePublicKey=True)` |
| user_data | A `user_data` | full | can't combine with `ssh_key`, so merge the key into cloud-init |
| VPC / subnets / route tables / IGW | B `openstack_networking_{network,subnet,router,router_interface}_v2`, or A `has_private_network = true` | partial | without B, everything collapses to one private network: report what was lost (isolation between subnets) |
| NAT gateway | B router with external gateway | partial | |
| Security group | B `openstack_networking_secgroup_v2` + `_rule_v2`, or C ufw/nftables rules in cloud-init | partial | SG-to-SG references become CIDR rules on the private network in C |
| ALB / NLB | A `leaseweb_public_cloud_load_balancer` + `_listener` + `_target_group` | partial | path/host routing rules and multiple AZ backends aren't supported. HTTPS needs a cert, ACM can't be exported |
| Target group | A `leaseweb_public_cloud_target_group` | full | health check path/port/protocol map directly |
| ACM certificate | inline `certificate {}` on the listener | manual | issue a new cert (Let's Encrypt) |
| Route 53 records | A `leaseweb_dns_resource_record_set` | partial | alias -> A record to the new LB/instance IP. TTL rounded to an allowed value. Zone/domain move is manual |
| Route 53 zone | none | manual | transfer domain or change NS at the registrar |
| S3 bucket | Leaseweb Object Storage via `aws` provider with custom endpoint (`*.object-storage.io`) | partial | native provider resources were reverted in v1.32.1. Data copy with rclone/s3cmd. Policies only partly compatible |
| RDS Postgres/MySQL/MariaDB | C instance + cloud-init installing the engine + backup cron to object storage | manual (AI) | no managed DB found. Size instance from `instance_class`. Report: dump/restore or logical replication plan, lost features (PITR, multi-AZ) |
| Aurora | same as RDS | manual (AI) | |
| ElastiCache Redis | C instance with Redis/Valkey | manual (AI) | |
| EKS / ECS | Leaseweb Managed Kubernetes | manual (AI) | no TF resource. ECS task defs -> k8s manifests is a good AI task |
| Lambda | container on an instance / k8s, or an OpenFaaS-style setup | manual (AI) | |
| SQS / SNS | RabbitMQ / NATS on an instance | manual (AI) | |
| DynamoDB | ScyllaDB (Alternator is DynamoDB-compatible) or Postgres | manual (AI) | |
| CloudFront | Leaseweb CDN | manual | no TF resource |
| IAM | none (Leaseweb has portal users, object storage users/groups) | manual | report only, plus security findings |
| CloudWatch | Prometheus/Grafana on an instance | manual | |
| Auto Scaling group | fixed N instances (`count`) | partial | auto-scaling is "coming soon" on the new platform |

## Instance type mapping
Leaseweb names copy AWS: `lsw.<family><gen>.<size>`. Valid provider types: `m3, m4, m5, m5a, m6a, c3, c4, c5, c5a, c6a, r3, r4, r5, r5a, r6a, g6, gr6` with sizes `large` to `24xlarge` (not every size for every gen, see `docs/schemas/leaseweb.json`).

Rules, in order:
1. Same family letter (m/c/r/g). AWS `t*` (burstable) -> `m` or `c` by RAM ratio. AWS `x*`/`z*`/`u*` -> `r`.
2. Size by vCPU: `large` = 2, `xlarge` = 4, `2xlarge` = 8, etc. AWS `nano/micro/small/medium` have no Leaseweb equivalent: round up to `large`, and the report says "over-provisioned, smallest Leaseweb size is 2 vCPU".
3. Generation: prefer the newest AMD (`6a`), then fall back to the newest available in that family/size.
4. AWS Graviton (`*g`, e.g. `m7g`) -> x86 equivalent, flagged "ARM -> x86, rebuild images/binaries".
5. GPU (`g4dn`, `g5`, `p*`) -> `lsw.g6.*` by GPU count, flagged for review.
6. Always check RAM: the chosen type's RAM must be >= the AWS RAM (vCPU/RAM from `describe_instance_types`, Leaseweb from the instance types API).

Examples (assuming the KB ratios: c = 2 GiB/vCPU, m = 4, r = 8):
- `t3.micro` (2 vCPU / 1 GiB) -> `lsw.c6a.large` (2 / 4), over-provisioned
- `t3.medium` (2 / 4) -> `lsw.c6a.large` (2 / 4)
- `t3.large` (2 / 8) -> `lsw.m6a.large` (2 / 8)
- `m5.xlarge` -> `lsw.m6a.xlarge`
- `c6i.4xlarge` -> `lsw.c6a.4xlarge`
- `r6g.2xlarge` -> `lsw.r6a.2xlarge` (+ ARM flag)

Verify the real vCPU/RAM per type with the Leaseweb instance types API before trusting the ratios.

## RDS instance class -> VM
`db.<family>.<size>` -> same rules on `<family>.<size>`, then add 20% disk headroom over `allocated_storage`, and `root_disk_storage_type = "CENTRAL"`.

## AMI -> Leaseweb image
From `describe_images`: `PlatformDetails` + `Name`/`Description` (e.g. "ubuntu-jammy-22.04" -> `UBUNTU_22_04_64BIT`). Windows -> Windows image + 50 GB minimum root. Custom/golden AMIs -> `manual` (export via VM Import/Export or rebuild with Packer).
