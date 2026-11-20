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
- **The private network interface is `eth1` and isn't up by default.** The KB configures it by hand with netplan or nmcli and DHCP (https://kb.leaseweb.com/kb/public-cloud/public-cloud-adding-public-cloud-instance-to-private-network/). Our cloud-init must bring `eth1` up with DHCP. The default subnet is a /27 and you can't choose the range (https://kb.leaseweb.com/kb/private-network/private-network-overview/).
- **One public IPv4 per instance, always**, and no extra IPs (https://kb.leaseweb.com/products/public-cloud). A private-subnet DB on AWS still gets a public IP on Leaseweb, so the security group must block it.
- **Only instances with private networking can be targets** in a target group (https://kb.leaseweb.com/kb/public-cloud/managing-target-groups-for-public-cloud/). Set `has_private_network = true` on every backend.
- **The default security group allows ALL from 0.0.0.0/0** (https://kb.leaseweb.com/kb/public-cloud/public-cloud-managing-firewall-of-public-cloud/). Finalize must attach our groups and stop relying on the default one (to verify: whether the default group can be detached).

## Terraform plan and validate
From `internal/provider/provider.go` and `publiccloud/instance_resource.go`:
- Configure fails with "Missing Leaseweb API token" if there's no token, but it makes no API call. So `plan` with a dummy token (`LEASEWEB_TOKEN=dummy`) should work for new resources. Verify on the VM.
- Validation is static only (enum validators for region, type, storage type and contract type, plus 5-1000 for `root_disk_size`). Nothing checks instance type availability per region at plan time.
- `terraform validate` doesn't need a token.

## Prices (fallback until we have a token)
With a token, `GET /instanceTypes?region=eu-west-3` gives real prices, so fetch them into `data/leaseweb_catalog.json`.
Without one, these are the only figures found (third party, not Leaseweb's site):

| Item | Price | Source |
|---|---|---|
| `lsw.c6a.large` (2 vCPU / 4 GB) | 34.39 EUR/month | https://www.vpsbenchmarks.com/hosters/leaseweb/plans (updated 2026-11-06) |
| `lsw.m3.large` (2 vCPU / 7 GB) | 29.44 EUR/month | same |
| compute family | USD 14.29-18.12 per vCPU/month | same |
| general purpose family | USD 17.58-22.38 per vCPU/month | same |
| traffic | 1 TB/month pooled free, then 2.20 EUR/TB (1-15 TB); incoming free | same |
| object storage | 0.017 EUR/GB/month, minimum 500 GB | same |

Load balancer prices weren't found. Leaseweb's own pricing pages are JS-rendered and can't be fetched.
Pitch angle: AWS egress is about USD 0.09/GB, and Leaseweb includes 1 TB. Put traffic in the cost comparison, because that's where Leaseweb wins, and small instances (smallest is 2 vCPU) are where it loses.
