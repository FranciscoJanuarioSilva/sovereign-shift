---
name: scan-azure
description: Maps an Azure subscription to the same neutral inventory.json the AWS scanner writes (VMs, VNets, NSGs, load balancers, PostgreSQL/MySQL flexible servers, storage accounts, DNS). Use it when building, testing or running Azure as a source.
---

# Scan Azure

Part of: sovereign-shift. Status: see `docs/azure.md`. There is no live Azure subscription for testing, so anything Azure is verified with a sample inventory and mocked SDK responses only. Say that whenever you present it.

## Credentials
A service principal with the Reader role on the subscription, through `azure-identity` (`DefaultAzureCredential`). Never Contributor. Read-only like AWS.

## Mapping to the neutral types
| Azure | inventory type | Notes |
|---|---|---|
| `Microsoft.Compute/virtualMachines` | `ec2_instance` | `instance_type` = VM size, vCPU and RAM from the VM sizes API, OS from the image reference, disks, SSH keys, public IP |
| `Microsoft.Network/virtualNetworks` + subnets | `vpc`, `subnet` | |
| `Microsoft.Network/networkSecurityGroups` | `security_group` | inbound Allow rules; source `*`, `Internet` or `0.0.0.0/0` means `0.0.0.0/0`; respect Deny by priority |
| `Microsoft.Network/publicIPAddresses` | `elastic_ip` | |
| `Microsoft.Network/loadBalancers`, `applicationGateways` | `lb`, `lb_listener`, `target_group` | backend pool = target group |
| `Microsoft.DBforPostgreSQL/flexibleServers`, MySQL | `db_instance` | SKU, storage, public network access, HA mode, backup retention |
| `Microsoft.Storage/storageAccounts` | `s3_bucket` | public blob access, versioning |
| `Microsoft.Network/dnszones` + record sets | `route53_zone`, `route53_record` | |
| anything else | `other` | `properties.cloud_type` holds the Azure type, the AI step proposes a replacement |

Set `"source": "azure"` on the inventory and `properties.cloud_type` on every resource.

## Prices
Azure's Retail Prices API is public (`https://prices.azure.com/api/retail/prices`), so VM prices can be real without a key.

## Pitfalls
- Azure regions (`westeurope`, `swedencentral`, ...) need their own entries in `mappings/regions.yaml`.
- VM size families: D general, E and M memory, F compute, B burstable, N GPU (review by hand).
