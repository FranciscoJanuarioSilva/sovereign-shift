# Leaseweb platform

Fetched 2026-11-20. Every fact has its source. "Not found" means not on the pages we could read, not that it doesn't exist.
Unreadable sources: https://developer.leaseweb.com/docs/ (too large for the fetcher; read it in a browser or fetch sub-pages), and the www.leaseweb.com marketing and pricing pages (JS-rendered, so no prices were obtained).

## Public Cloud: old vs new platform
Source: https://kb.leaseweb.com/kb/public-cloud-new/public-cloud-platform-comparison/

| | Old | New |
|---|---|---|
| Regions | DE, UK, US, CA, JP, SG, AU | NL, "other regions coming soon" |
| API | EC2-compatible API | OpenStack API |
| Storage | local NVMe + central NAS | central only, Value (8K IOPS) or Performance (30K IOPS) |
| IPs | public by default | private by default, public on demand, full IPv6 |
| Security groups / basic firewall | yes | yes |
| Routers, subnets | no | yes |
| Load balancer | yes | yes, new flavors |
| Private network | yes | coming soon |
| Auto-scaling | yes | coming soon |
| Snapshots | 1 | 10 per project |
| Billing | on-demand, monthly | on-demand, Savings Plans |
| Launch from | images | images, volumes, volume snapshots |

New platform details (https://kb.leaseweb.com/kb/public-cloud-new/new-leaseweb-public-cloud/):
- AZs `eu-west-3-az1`, `eu-west-3-az2`. The same page also calls them AMS-01 and AMS-02, so this is Amsterdam.
- Instance families: General Purpose (1 vCPU : 4 GiB), Compute Optimized (1 : 2), Memory Optimized (1 : 8). GPU coming soon.
- Naming: `lsw.<family><vintage>.<size>`, e.g. `lsw.m4i.large`, `lsw.c6a.12xlarge`, `lsw.r5.xlarge`.
- Vintages: 3i/4i/5i Intel up to 32 cores / 64 GiB, 5a AMD EPYC v2 up to 48 / 384 GiB, 6a EPYC v3 up to 96 / 768 GiB, 7a EPYC 9004 up to 64 / 512 GiB (7a is the only one with dedicated vCPU).
- Network: up to 25 Gbps uplink, 1 TB pooled outgoing traffic, incoming free, DDoS IP protection included.
- OSes: Ubuntu, Rocky, Alma, Debian, Arch, FreeBSD, Windows.
- Managed through the portal or "direct OpenStack API access". Keystone URL: not found.

The size naming mirrors AWS (`m`, `c`, `r`, `large` = 2 vCPU, `xlarge` = 4 vCPU, etc.), which makes EC2 mapping mostly mechanical. See `service-equivalence.md`.

## Public Cloud load balancer (new)
Source: https://kb.leaseweb.com/kb/public-cloud-new/public-cloud-load-balancer-new/
- Flavors: `lsw.lb.small` (1 vCPU / 1 GiB), `lsw.lb.medium` (2 / 2), `lsw.lb.large` (4 / 4).
- Needs an existing subnet, plus a router for public access. Only balances to backends in the same AZ.
- TLS termination via a `TERMINATED_HTTPS` listener with a certificate container. Pools with member instances.
- This is OpenStack Octavia terminology, which supports the "new platform = OpenStack" reading.

## Object Storage (S3 replacement)
Sources: https://kb.leaseweb.com/kb/object-storage/object-storage-overview/, https://kb.leaseweb.com/kb/object-storage/object-storage-getting-started-with-object-storage/, https://kb.leaseweb.com/kb/object-storage/ordering-api-for-object-storage/
- S3-compatible. Data is stored across three AZs.
- Endpoints: `nl.object-storage.io` (nl-01), `de.object-storage.io` (de-01), `uk.object-storage.io` (uk-01), `us.object-storage.io` (us-01), `ca.object-storage.io` (ca-01, the page's link points to us, which is a doc bug), `sg.object-storage.io` (sg-01).
- Don't use `us-east-1` as the region name: data then lands wherever the package lives.
- Bucket policies supported (public read via `Principal: "*"`, IP-restricted via `sgws:SourceIp`, which suggests NetApp StorageGRID underneath). Versioning, lifecycle and presigned URLs: not stated.
- Tools shown: s3cmd, S3 Browser.
- Products: Reserved (500 GB to 1 PB, 100 GB steps, 1 month to 3 year terms) and On Demand. Usage (storage, egress, API calls) is billed on top. Unit prices are only in the ordering API (`https://api.leaseweb.com/ordering/v1`).
- Management API: `/objectStorage/v1/objectStorages` (buckets, users, groups, access keys).
- Locations (ordering page): AMS-01, FRA-01, LON-01, MTL-02, SIN-01, WDC-02. Orders are limited to the API key's Leaseweb entity, and new customers need KYC.
- Terraform: the native resources were reverted in provider v1.32.1. MVP: bucket creation and copy with rclone in the runbook. Untested idea for later: the `aws` provider pointed at the Leaseweb endpoint (`endpoints { s3 = "https://nl.object-storage.io" }`, `s3_use_path_style = true`, `skip_credentials_validation`, `skip_requesting_account_id`, `skip_region_validation`) or the `minio` provider.

## Networking
- Leaseweb VPC (https://kb.leaseweb.com/kb/leaseweb-vpc/leaseweb-vpc-overview/): "first release phase", set up via support ticket. L2 isolated or L3 routed networks (up to 5, no ACLs between them). Connects dedicated servers and public cloud. Network ACLs and security groups are "available in a future release".
- Private Network (https://kb.leaseweb.com/kb/private-network/private-network-overview/): metro-wide L2, free traffic within a metro. Connects dedicated servers, colocation, public cloud, Elastic Compute, VMware and file/block storage. Doesn't connect object storage or VPS. Default DHCP /27, max /24, jumbo frames.
- Public cloud private network inside the instance: interface `eth1`, not up by default, DHCP must be configured (netplan/nmcli). Source: https://kb.leaseweb.com/kb/public-cloud/public-cloud-adding-public-cloud-instance-to-private-network/
- Each instance has its own security group, "IP-table based", rules managed in the portal "or via the API", default rule ALL from 0.0.0.0/0. Source: https://kb.leaseweb.com/kb/public-cloud/public-cloud-managing-firewall-of-public-cloud/
- Conclusion for the tool: VPC/subnets collapse to the private network (`has_private_network`). Security groups go to the Public Cloud API through finalize (`leaseweb-api.md`).

## Databases
No managed Postgres/MySQL product found in the KB navigation. Treat RDS as "self-host on an instance" (cloud-init installs Postgres/MySQL, plus a backup cron to object storage), or "Managed Kubernetes + operator" for bigger setups. Confirm with Leaseweb staff.

## Managed Kubernetes
Source: https://kb.leaseweb.com/kb/kubernetes/kubernetes-overview/ and https://kb.leaseweb.com/kb/managing-a-kubernetes-cluster/limits-known-issues/
- Available in NL, CA, DE, UK, US, SG. Control plane is free, you pay for nodes.
- Limits: 10 nodes default (100 on request), 3 free public IPs, 1 Gbps shared egress, RWO-only volumes up to 2 TB, no volume encryption at rest, no private networking yet.
- No Terraform resource in the provider. Target for EKS/ECS migrations, with manual steps.

## Dedicated servers (data centers)
Source: https://kb.leaseweb.com/kb/dedicated-server/dedicated-server-overview/
AMS-01, AMS-02 (Amsterdam), FRA-10 (Frankfurt), LON-01, LON-11 (London), HKG-10, SIN-01, SYD-10, CHI-11, DAL-13, MIA-11, LAX-11, NYC-01, PHX-01, SFO-12, SEA-11, WDC-02, MTL-02.
Delivery: hours for standard, up to 5 working days on demand, 7-10 business days custom. Not created by Terraform (bought, then managed via `leaseweb_dedicated_server`).

## DNS
KB has Domain Name articles (overview, record types, round-robin). The provider's `leaseweb_dns_resource_record_set` manages records on domains hosted at Leaseweb. Zone creation via Terraform: not found, so domain transfer/registration is a manual step.

## CDN
In-house CDN since 2014 plus Multi-CDN (https://kb.leaseweb.com/). Details not fetched (the overview page returned 404). CloudFront becomes manual.

## Compliance (sovereignty pitch)
Source: https://kb.leaseweb.com/kb/compliance-security/security-certifications/
- ISO/IEC 27001:2022 (EY CertifyPoint) for the NL, DE, UK, US, SG, CA entities.
- PCI DSS v4.0 (physical) in AMS-01, FRA-01, LON-01, SIN-01, WDC-02, MTL-01, MTL-02.
- SOC 1 Type II, SOC 2 (Canada colo), HIPAA (WDC-01), NEN 7510 (AMS-01).
- Leaseweb Global B.V. is Dutch-headquartered. EU ownership and GDPR statements weren't on the pages read, so cite their own site before using it in the pitch.
- Note for the "EU sovereign" story: the US/SG/CA entities exist, so recommend NL/DE entities and EU locations only.

## Answered by reading the SDK (see `leaseweb-api.md`)
- The provider uses the `publicCloud/v1` REST API, not OpenStack.
- Prices come from `GET /instanceTypes` (`prices.hourly`, `prices.monthly`).

## Still open (nice to know, not blocking)
1. ETA for object storage in the provider.
2. Any managed database on the roadmap?
3. Load balancer prices.
