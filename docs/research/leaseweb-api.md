# Leaseweb Public Cloud REST API (what Terraform can't do)

Checked 2026-11-20 against the generated Go SDK, which is built from the OpenAPI spec:
https://github.com/leaseweb/leaseweb-go-sdk/tree/main/publiccloud (`api_publiccloud.go`, `model_*.go`).
https://developer.leaseweb.com/api-docs/publiccloud_v1.html is the human reference, but it's over 10 MB, so open it in a browser.

## Basics
- Base URL `https://api.leaseweb.com/publicCloud/v1`, header `X-LSW-Auth: <token>` (`configuration.go`).
- The Terraform provider talks to this same API through the SDK (`internal/provider/client/client.go`). There's no OpenStack or Keystone code in the provider.
- So the MVP targets this API plus the `leaseweb/leaseweb` provider. The OpenStack-based "new platform" is roadmap only.

## Endpoints we use and that the provider doesn't cover
| Need | Endpoint | Body / notes |
|---|---|---|
| security groups (AWS SG) | `POST /securityGroups` | `{"name": "..."}` |
| firewall rules | `POST /securityGroups/{id}/authorizeFirewallRules` | `{"rules": [{"protocol", "startPort", "endPort", "icmpType", "icmpCode", "source"}]}`, `source` is a CIDR |
| list / revoke rules | `GET /securityGroups/{id}/firewallRules`, `POST .../revokeFirewallRules` | |
| attach SG to instance | `POST /instances/{instanceId}/attachSecurityGroups` | `{"securityGroupIds": [...]}` |
| LB backends (AWS TG targets) | `POST /targetGroups/{id}/registerTargets` | JSON array of instance ids |
| list targets | `GET /targetGroups/{id}/targets` | `Target` has `id`, `reference`, `ips`, `healthCheck` |
| instance types + prices | `GET /instanceTypes?region=<region>` | each item: `name`, `resources.cpu`, `resources.memory`, `storageTypes`, `prices.hourly`, `prices.monthly` (strings), `minDiskSize` |
| regions | `GET /regions` | use it to verify `mappings/regions.yaml` |
| instance IPs | `GET /instances/{instanceId}/ips` | needed to turn SG-to-SG rules into /32 CIDRs |
| auto scaling groups | `/autoScalingGroups`, `.../registerTargetGroup` | not in the provider. Roadmap for AWS ASGs |

Firewall rules only take a CIDR `source`. There's no SG-to-SG reference like on AWS. An AWS rule "allow web-sg on 5432" becomes one rule per web instance, with its private IP as a /32, resolved after `terraform apply`.

## Facts that change the generator
- **`user_data` is plain text.** The SDK model says "Send the user data as plain text, not encoded as base64" (`model_launch_instance_opts.go`). The provider passes it through unchanged (`instance_resource.go`, `opts.SetUserData(plan.UserData.ValueString())`).
- **cloud-init works.** "There are two types of user data supported: a cloud-config for the cloud-init program and shell scripts" (https://kb.leaseweb.com/kb/public-cloud/run-commands-on-boot-with-user-data/).
- **The private network interface isn't up by default.** The KB calls it `eth1` and configures it by hand with netplan or nmcli and DHCP (https://kb.leaseweb.com/kb/public-cloud/public-cloud-adding-public-cloud-instance-to-private-network/), but that's the old platform. Our team VM on the new platform names its interface `enp3s0` (`environment.md`). Our cloud-init must bring up every non-primary interface with DHCP, matched in netplan, never by name. The default subnet is a /27 and you can't choose the range (https://kb.leaseweb.com/kb/private-network/private-network-overview/).
- **One public IPv4 per instance, always**, and no extra IPs (https://kb.leaseweb.com/products/public-cloud). A private-subnet DB on AWS still gets a public IP on Leaseweb, so the security group must block it.
- **Only instances with private networking can be targets** in a target group (https://kb.leaseweb.com/kb/public-cloud/managing-target-groups-for-public-cloud/). Set `has_private_network = true` on every backend.
- **The default security group allows ALL from 0.0.0.0/0** (https://kb.leaseweb.com/kb/public-cloud/public-cloud-managing-firewall-of-public-cloud/). Finalize must attach our groups and stop relying on the default one (to verify: whether the default group can be detached).

## Terraform plan and validate
From `internal/provider/provider.go` and `publiccloud/instance_resource.go`:
- Configure fails with "Missing Leaseweb API token" if there's no token, but it makes no API call. So `plan` with a dummy token (`LEASEWEB_TOKEN=dummy`) should work for new resources. Verify on the VM.
- Validation is static only (enum validators for region, type, storage type and contract type, plus 5-1000 for `root_disk_size`). Nothing checks instance type availability per region at plan time.
- `terraform validate` doesn't need a token.

## Prices
Checked 2026-11-20 with a real token. `GET /instanceTypes?region=<region>` returns, per type:
`name`, `resources.{cpu,memory,gpu,publicNetworkSpeed,privateNetworkSpeed}`, `prices.{hourly,monthly}` (strings),
`minDiskSize` and `storageTypes` (`CENTRAL` and/or `LOCAL`). The list is paginated (`limit` 50, `offset`, `_metadata.totalCount`, 84 types per region).
`GET /regions` returns all 10 regions: eu-west-3 Amsterdam, eu-central-1 Frankfurt, eu-west-2 London, us-east-1 Washington,
us-west-1 San Francisco, us-west-2 Los Angeles, ca-central-1 Montreal, ap-southeast-1 Singapore, ap-southeast-2 Sydney, ap-northeast-1 Japan.

Things that matter for the translator:
- **Each region is billed in its own currency** (`_metadata.currency`): EUR for Amsterdam and Frankfurt, GBP London, USD for the US regions, CAD, SGD, AUD, JPY. Never put a non-EUR number in a EUR total.
- **Many types are local-NVMe only.** In eu-west-3, 42 of 74 non-GPU types (including all `5a` and `6a`) only support `LOCAL` root disks. `root_disk_storage_type = "CENTRAL"` on those fails at apply, so the translator picks the kind the type supports. Databases prefer central-capable types.
- **Real memory is not exactly the family ratio** (`lsw.c3.large` has 3 GiB, `lsw.m3.large` 7 GiB, `lsw.c6a.large` 4 GiB, `lsw.m6a.large` 8 GiB).
- Real Amsterdam prices (EUR per month): `lsw.c6a.large` 33.05, `lsw.m6a.large` 37.38, `lsw.r6a.large` 46.06, `lsw.m3.large` 29.04.

How we use it, without making end users bring a token:
- `scripts/fetch_leaseweb_catalog.py` (maintainers, needs `LEASEWEB_TOKEN`) writes `data/leaseweb_catalog.json`, which is committed.
- The translator reads that snapshot (or the file named by `SOVEREIGN_LEASEWEB_CATALOG`). It's authoritative for the account that made it. Contract discounts and taxes aren't in it.
- Without a snapshot, `data/leaseweb_public_prices.json` holds a dated, sourced list of public website prices:
  - New OpenStack Public Cloud: https://www.leaseweb.com/en/products-services/cloud/public-cloud-openstack/pricing
  - Older Public Cloud GPU list: https://www.leaseweb.com/products-services/cloud/public-cloud/pricing
  - Same-named OpenStack prices are proxies on a different platform, marked `*` in the report.

Not in the compute subtotal: storage, traffic, public IPs, load balancers. Reference figures from the website: 1 TB pooled outgoing traffic per month included, then EUR 2.20/TB at the first tier; older Public Cloud local NVMe from EUR 0.0300/GB/month and network SSD EUR 0.0800/GB/month; the new OpenStack cloud (a different platform) has Value block storage at EUR 0.0700/GB/month and load balancers at EUR 11.02, 22.05 and 44.17/month. Verify exact regional pricing before making customer-facing savings claims.
