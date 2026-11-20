---
name: scan-gcp
description: Maps a Google Cloud project to the same neutral inventory.json the AWS scanner writes (Compute Engine VMs, disks, VPCs, firewall rules, load balancers, Cloud SQL, Cloud Storage, Cloud DNS, plus GKE and other services as other). Use it when building, testing or running Google Cloud as a source.
---

# Scan Google Cloud

Part of: sovereign-shift. Status: see `docs/gcp.md`. There is no live project for testing, so anything Google Cloud is verified with recorded-shape REST responses and a mock transport only. Say that whenever you present it.

## Credentials
A service account with the basic Viewer role, token scope `cloud-platform.read-only`, through application default credentials (`pip install -e '.[gcp]'`) or `GCP_ACCESS_TOKEN` from `gcloud auth print-access-token --impersonate-service-account=...`. Never Editor. The reader refuses any call except GET and `instanceGroups.listInstances`.

## Mapping to the neutral types
| Google Cloud | inventory type | Notes |
|---|---|---|
| `compute.googleapis.com/Instance` | `ec2_instance` | `instance_type` = machine type, vCPU and RAM from the machine type, OS from the boot disk image, SSH keys from instance and project metadata, startup script only as hash and length |
| `Network`, `Subnetwork` | `vpc`, `subnet` | |
| `Firewall` | `security_group` | one group per (network, target tag / service account / all), `sourceTags` -> `source_instances`, deny rules and odd protocols dropped with a note |
| `Disk` | `ebs_volume` | always encrypted |
| `Address` (external, on an instance) | `elastic_ip` | addresses of forwarding rules travel with the lb |
| forwarding rule -> proxy -> URL map -> backend service | `lb`, `lb_listener`, `target_group` | rules sharing an IP are one lb, instance groups are the members |
| `sqladmin.googleapis.com/Instance` | `db_instance` + `security_group` | tier -> vCPU/RAM, the access group holds authorized networks and private network clients |
| `storage.googleapis.com/Bucket` | `s3_bucket` | `allUsers` in the IAM policy = public, public access prevention = access block |
| `dns.googleapis.com/ManagedZone`, record sets | `route53_zone`, `route53_record` | TXT values never stored |
| GKE, Cloud Run, Cloud Functions, Memorystore, Pub/Sub | `other` | GKE gets a Leaseweb Managed Kubernetes rule, the rest goes to the AI step |

Set `"source": "gcp"` on the inventory and `properties.cloud_type` on every resource. Ids are `gcp:` + API path without the project.

## Steps
1. Change the mapping in `build_inventory()`, never in `collect()`.
2. Add the REST response to `testdata/gcp_api_responses.json`, regenerate `testdata/gcp_inventory.json` and check the diff by hand.
3. `pytest tests/test_gcp.py`, then run `all --from-snapshot testdata/gcp_inventory.json --no-ai` and `terraform validate` on the output.

## Pitfalls
- GCP regions (`europe-west4`, ...) need entries in `gcp_to_leaseweb` in `mappings/regions.yaml`. `europe-west4` is the Netherlands, `eu-west-3` on Leaseweb is Amsterdam, on AWS it's Paris.
- Machine types: `e2-micro/small/medium` are shared-core, `t2a`/`c4a` are Arm, `a2`/`a3`/`g2` have GPUs.
- Status `TERMINATED` is a stopped VM, keep it.
- Google list prices aren't fetched, the source cost column is unknown.
