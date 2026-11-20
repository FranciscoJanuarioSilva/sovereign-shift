# Azure as a source

Status, 2026-11-20: **the Azure scanner is not verified against a live subscription.** What *is* checked, without an account:
- Current Azure SDKs return the REST shape from `as_dict()` (camelCase, nested under `properties`), older ones a flat snake_case shape. `normalize()` accepts both, and a test pushes the sample through the installed SDK's own model classes (VM, disk, NSG, public IP, VNet, load balancer, NIC) and requires the same inventory. This caught a real bug: the mapper only understood the old shape.
- Every SDK operation `collect()` calls exists in the installed SDK, and the resource client import works on azure-mgmt-resource 24+ (it didn't before).
- Not checked: the exact field values a real subscription returns, paging, and permission errors. Those need a live Reader run, or an export from someone with access (`az vm list`, `az network nsg list`, ...).

We had no Azure account. The mapping is tested with a hand-built sample of what the Azure SDK returns (`testdata/azure_sdk_sample.json`, made up, not real data) and the full pipeline runs on its output (`testdata/azure_inventory.json`). Say this whenever Azure comes up.

## How it works
- `sovereign_shift/scanner/azure.py` has two parts. `collect()` reads the records with the Azure SDK (Reader role only, `DefaultAzureCredential`). `build_inventory()` maps them to the same neutral inventory the AWS scanner writes. The tests cover `build_inventory()`.
- Every resource keeps its Azure type in `properties.cloud_type`. The mapping table is in [skills/scan-azure](../skills/scan-azure/SKILL.md).
- A database server firewall is modelled as a security group, so the checks (public database port) and the translator's fixes apply as for AWS.
- Regions map through `azure_to_leaseweb` in `mappings/regions.yaml` (Sweden Central, West Europe and North Europe go to Amsterdam, Germany West Central to Frankfurt).
- VM sizes map by series: D general, E and M memory, F compute, B burstable (by RAM per vCPU), N GPU, `p` in the features is ARM.
- Prices: `scripts/fetch_azure_prices.py` reads the public Azure Retail Prices API (no key) into the `regional` block of `data/aws_instance_types.json`. Database (flexible server) prices aren't fetched yet, so databases show `unknown` and stay out of the totals.

## Run it
See [usage.md](usage.md#scan-an-azure-subscription). The GitHub workflow has no Azure option: run the sample locally.

## Not done yet
- A live run, which needs a subscription and a Reader service principal.
- Application Gateways (only Azure Load Balancers are mapped), and storage account versioning (reported as unknown).
- Azure IAM (RBAC) checks.
