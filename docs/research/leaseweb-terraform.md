# Leaseweb Terraform provider

Fetched 2026-11-20. Ground truth: `corpus/leaseweb/terraform-provider-leaseweb` (docs/, examples/) and the schema dump in `docs/schemas/leaseweb.json`.

## Basics

| | |
|---|---|
| Source | `leaseweb/leaseweb` on the Terraform Registry, code at https://github.com/leaseweb/terraform-provider-leaseweb |
| Latest | v1.32.1 (2026-10-23), actively maintained |
| Language / SDK | Go, uses `github.com/leaseweb/leaseweb-go-sdk` (`publiccloud`, `dedicatedserver/v2`, `dns`, `ipmgmt`) |
| API host | `api.leaseweb.com` over https (override with `host` / `LEASEWEB_HOST`) |
| Auth | `token` attribute or `LEASEWEB_TOKEN` env var. One token = one Leaseweb account, so use provider aliases for multiple accounts. |

```hcl
terraform {
  required_providers {
    leaseweb = {
      source  = "leaseweb/leaseweb"
      version = "~> 1.32"
    }
  }
}

provider "leaseweb" {} # token from LEASEWEB_TOKEN
```

## Resources (v1.32.1)

| Resource | What it is | AWS counterpart |
|---|---|---|
| `leaseweb_public_cloud_instance` | VM | `aws_instance` |
| `leaseweb_public_cloud_ip` | sets reverse DNS on an instance IP (not an allocation) | partial `aws_eip` |
| `leaseweb_public_cloud_load_balancer` | LB, sized by instance type | `aws_lb` |
| `leaseweb_public_cloud_load_balancer_listener` | HTTP / HTTPS / TCP listener, inline cert | `aws_lb_listener` (+ ACM cert) |
| `leaseweb_public_cloud_target_group` | HTTP / HTTPS / TCP, optional health check | `aws_lb_target_group` |
| `leaseweb_public_cloud_image` | custom image from an instance | `aws_ami_from_instance` |
| `leaseweb_public_cloud_instance_iso` | attach an ISO | none |
| `leaseweb_public_cloud_credential` | stored instance credential | none |
| `leaseweb_dedicated_server` | existing bare-metal server (bought via portal, not created by TF) | none, target for large/steady EC2 |
| `leaseweb_dedicated_server_installation` | OS install, RAID, partitions, `post_install_script` | user_data on bare metal |
| `leaseweb_dedicated_server_credential` | | |
| `leaseweb_dedicated_server_notification_setting_bandwidth` / `_datatraffic` | usage alerts | CloudWatch billing alarm-ish |
| `leaseweb_dns_resource_record_set` | DNS record on a domain hosted at Leaseweb | `aws_route53_record` |
| `leaseweb_ipmgmt_ip` | reverse DNS on an IP | |
| `leaseweb_ipmgmt_null_route` | null-route an IP | |

Data sources: `dedicated_server(s)`, `dedicated_server_operating_systems`, `dedicated_server_control_panels`, `dedicated_server_credential`, `dns_resource_record_sets`, `ipmgmt_ips`, `ipmgmt_null_route_history`, `public_cloud_credential`, `public_cloud_images`, `public_cloud_instances`, `public_cloud_isos`, `public_cloud_load_balancers`, `public_cloud_load_balancer_listeners`, `public_cloud_target_groups`.

## Missing from the provider (the gaps our tool has to handle)

- No network/VPC/subnet, route table, security group or firewall resources. An instance only has `has_private_network = true|false`.
- No block volumes (only `root_disk_size` 5-1000 GB with `root_disk_storage_type` LOCAL or CENTRAL).
- No object storage. v1.32.0 (2026-10-19) added `object_storage_bucket/_user/_group/_access_key`, but v1.32.1 reverted it: "Object storage isn't yet completely ready to use in Terraform" (PR #599). Expect it to come back. Until then, use the S3-compatible API (see `leaseweb-platform.md`).
- No managed DB, queues, functions, CDN, IAM or Kubernetes resources.
- No load balancer to target-group membership resource in the docs. Check `docs/schemas/leaseweb.json` before emitting targets.

## Key attributes

### `leaseweb_public_cloud_instance`
```hcl
resource "leaseweb_public_cloud_instance" "web" {
  region                 = "eu-west-3"          # forces replacement
  type                   = "lsw.m5a.large"      # forces replacement
  reference              = "web-1"              # display name, use the AWS Name tag
  image                  = { id = "UBUNTU_24_04_64BIT" }  # or a custom image UUID
  root_disk_size         = 50                   # GB, min 5 Linux / 50 Windows, max 1000
  root_disk_storage_type = "CENTRAL"            # LOCAL | CENTRAL
  has_private_network    = true
  ssh_key                = var.ssh_public_key   # mutually exclusive with user_data
  # user_data            = file("cloud-init.yaml")
  contract = {
    type              = "HOURLY"                # HOURLY | MONTHLY
    billing_frequency = 1                       # months: 0,1,3,6,12
    term              = 0                       # months, MONTHLY only: 0,1,3,6,12,24,36
  }
}
```
- Valid `region` values: `eu-west-3`, `us-east-1`, `eu-central-1`, `ap-southeast-1`, `us-west-1`, `eu-west-2`, `ca-central-1`, `ap-northeast-1`.
- Valid `type` values: families `lsw.m*` (general), `lsw.c*` (compute), `lsw.r*` (memory), `lsw.g6.*`, `lsw.gr6.*` (GPU), with generations 3, 4, 5, 5a, 6a and sizes large to 24xlarge. Full list in the schema dump.
- Gotcha: `ssh_key` and `user_data` can't both be set. If the AWS instance has both, inject the key into cloud-init `user_data`.
- Gotcha: the `image.id` values are Leaseweb OS ids like `UBUNTU_22_04_64BIT`, not AMIs. Map the AMI's OS family to the closest id (list via the `leaseweb_public_cloud_images` data source).

### `leaseweb_public_cloud_load_balancer_listener`
`protocol` HTTP|HTTPS|TCP, `port`, `default_rule.target_group_id`, `certificate { certificate, private_key, chain }` for HTTPS. ACM certs can't be exported, so HTTPS listeners need a new cert (Let's Encrypt or customer-supplied): flag as manual.

### `leaseweb_public_cloud_target_group`
`name`, `protocol`, `port`, `region`, optional `health_check { protocol, port, method, uri, host }`.

### `leaseweb_dns_resource_record_set`
`domain_name`, `name` (FQDN with trailing dot), `type` (A, AAAA, CAA, CNAME, MX, NS, SRV, TXT, SOA, DS, TLSA), `content` (list), `ttl` (one of 60, 300, 1800, 3600, 14400, 28800, 43200, 86400, so round the AWS TTL to the nearest one). Route 53 alias records have no equivalent: resolve the alias to the new LB IP (A record) or a CNAME.

## Platform caveat: old vs new Public Cloud

The provider's public cloud resources take the 8 AWS-style region codes above. These match the old Leaseweb Public Cloud platform (EC2-compatible API, multi-region). The new Public Cloud platform (NL only for now, AZs `eu-west-3-az1/az2`) is OpenStack-based: networks, routers, subnets, security groups, volumes, and Octavia-style load balancers with pools and `TERMINATED_HTTPS`. These are reachable through the OpenStack API, so the `terraform-provider-openstack/openstack` provider is the likely way to get networking and security groups on the new platform.
Open question to ask Leaseweb at the hackathon: which platform does `leaseweb_public_cloud_*` target today, and what is the Keystone auth URL for the new platform? See `leaseweb-platform.md`.

## OpenStack provider (fallback target)
Schema subset in `docs/schemas/openstack-subset.json` (provider v3.4.0). Relevant resources: `openstack_compute_instance_v2`, `openstack_networking_{network,subnet,router,router_interface,secgroup,secgroup_rule,floatingip,port}_v2`, `openstack_blockstorage_volume_v3`, `openstack_lb_{loadbalancer,listener,pool,member,monitor}_v2`. These cover exactly the gaps in the Leaseweb provider (VPC, SG, EBS, ALB internals).

## Real-world usage found
Almost none on GitHub. `remerge/terraform-modules` (`leaseweb/server/installation`, `op/host/leaseweb`) is the only external repo found using the provider. Use the provider's own `examples/` as few-shot material.
