# Google Cloud as a source

Status, 2026-11-20: **the Google Cloud scanner is not verified against a live project.** We had no GCP project. `collect()` is tested by replaying hand-built REST responses (`testdata/gcp_api_responses.json`, made up, not real data) through a mock transport, and the full pipeline runs on the result (`testdata/gcp_inventory.json`, `terraform validate` passes). Say this whenever Google Cloud comes up.

## How it works
- `sovereign_shift/scanner/gcp.py` has two parts. `collect()` reads the REST APIs over httpx (no Google SDK needed). `build_inventory()` maps the records to the same neutral inventory the AWS scanner writes. Both are tested.
- Read-only by construction: the reader only sends GETs, plus `instanceGroups.listInstances`, which Google only offers as a POST but which just lists members. Any other method raises.
- A 403 (missing permission or API not enabled) is recorded in `denied` and the scan continues, like the AWS scanner.
- Ids are `gcp:` plus the API path without the project (`gcp:zones/europe-west4-a/instances/web-1`), so the project id only appears in `account_id`, which the report masks.
- Every resource keeps its Google type in `properties.cloud_type`. The mapping table is in [skills/scan-gcp](../skills/scan-gcp/SKILL.md).
- Regions map through `gcp_to_leaseweb` in `mappings/regions.yaml`. A global load balancer takes the region of its backends.

## Firewall rules
GCP firewall rules belong to a network and target instances by network tag, service account, or all instances. Leaseweb security groups are attached to instances, like AWS ones. So the scanner builds one neutral security group per (network, target):
- `default-all` holds the rules without targets, `default-<tag>` the rules for one tag, `default-sa-<account>` the rules for one service account. An instance uses every group that matches it.
- `sourceTags` and `sourceServiceAccounts` become `source_instances` on the rule. The translator turns them into /32 rules on those instances' private IPs, resolved after apply, the same as AWS SG-to-SG rules.
- The VPC range (`10.128.0.0/9` in auto mode, plus scanned subnet ranges) becomes the Leaseweb private network. Google's load balancer and health check ranges (`130.211.0.0/22`, `35.191.0.0/16`) become the private network too, because the Leaseweb load balancer reaches backends over it. The IAP range (`35.235.240.0/20`) becomes `var.admin_cidr`.
- Deny rules and protocols other than TCP, UDP and ICMP can't be expressed in a Leaseweb group. They are dropped with a note, never silently. Disabled rules are skipped. Egress rules are kept in the inventory but not translated (same as AWS).

Cloud SQL isn't behind firewall rules, so each instance gets a synthetic `<name>-access` group: its authorized networks (when it has a public IP) plus the instances on its private network, on the engine port. This way the checks (public database) and the translator's fixes apply as for RDS.

## Load balancers
Forwarding rule -> target proxy -> URL map -> backend service -> instance group is flattened to `lb` / `lb_listener` / `target_group`. Forwarding rules that share an IP are one load balancer (port 80 and 443 usually do). An HTTP listener whose URL map only redirects to HTTPS becomes a manual item: Leaseweb listeners can only forward. Network endpoint groups (serverless, GKE) are kept as `target_type: network_endpoint_group` with no instance members. Path and host rules mark the listener partial.

## Prices
Google list prices aren't fetched. The source side of the cost table shows `unknown`, and the Leaseweb column sums every priced row. Compare it with the project's billing export.

## Run it
See [usage.md](usage.md#scan-a-google-cloud-project).

## Not done yet
- A live run, which needs a project and a viewer service account.
- Google prices (the Cloud Billing Catalog API needs a key and prices per core and per GB).
- Managed instance group autoscaling, Cloud Armor, Cloud CDN, internal TCP/UDP load balancers with several backends, serverless NEG targets.
- IAM checks (owner bindings, user-managed service account keys).
