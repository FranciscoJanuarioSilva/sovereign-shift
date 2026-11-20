# Google Cloud scanning

The REST calls the GCP scanner makes, and the facts behind its mapping. Fetched from memory of the public API reference on 2026-11-20, not re-read live: everything here is "verify" until a live run confirms it.

## Credentials (verify)
- Use a service account with the basic Viewer role (`roles/viewer`) on the project, and the token scope `https://www.googleapis.com/auth/cloud-platform.read-only`. Source: https://cloud.google.com/iam/docs/understanding-roles#basic
- Viewer may not include `storage.buckets.getIamPolicy`. Without it the bucket's public state isn't assessed (the scanner leaves `policy_public` out instead of guessing) and the call is listed under `denied`. Source: https://cloud.google.com/storage/docs/access-control/iam-permissions
- A user token from `gcloud auth print-access-token` carries the user's own, possibly write, permissions. Impersonate the viewer account instead: `gcloud auth print-access-token --impersonate-service-account=<viewer sa>`. Source: https://cloud.google.com/sdk/gcloud/reference/auth/print-access-token

## Calls
| What | Call | Source |
|---|---|---|
| networks, firewalls, global addresses and forwarding rules | `GET compute/v1/projects/{p}/global/{networks,firewalls,addresses,forwardingRules}` | https://cloud.google.com/compute/docs/reference/rest/v1 |
| instances, disks, subnetworks, addresses, forwarding rules | `GET compute/v1/projects/{p}/aggregated/{...}`, items keyed by zone or region | same |
| machine type vCPU and RAM | `GET .../zones/{z}/machineTypes/{type}` (`guestCpus`, `memoryMb`) | same |
| project SSH keys, OS Login | `GET compute/v1/projects/{p}` (`commonInstanceMetadata`) | same |
| proxies, URL maps, backend services, health checks, instance groups | `GET` on the self link each object references | same |
| instance group members | `POST .../instanceGroups/{g}/listInstances` (read-only list) | https://cloud.google.com/compute/docs/reference/rest/v1/instanceGroups/listInstances |
| Cloud SQL | `GET sqladmin/v1/projects/{p}/instances` | https://cloud.google.com/sql/docs/postgres/admin-api/rest/v1/instances/list |
| buckets and their IAM | `GET storage/v1/b?project={p}`, `GET storage/v1/b/{b}/iam` | https://cloud.google.com/storage/docs/json_api/v1/buckets |
| DNS | `GET dns/v1/projects/{p}/managedZones`, `.../{zone}/rrsets` | https://cloud.google.com/dns/docs/reference/rest/v1 |
| GKE, Cloud Run, Cloud Functions, Memorystore, Pub/Sub | `GET .../locations/-/{clusters,services,functions,instances}`, `GET pubsub/v1/projects/{p}/topics` | each service's REST reference |

Pagination is `nextPageToken` -> `pageToken` everywhere. An API that isn't enabled answers 403 with reason `accessNotConfigured` (recorded as `ServiceDisabled`).

## Facts the mapping relies on (verify)
- A firewall rule without targets applies to every instance in its network. An ingress rule with no source fields means `0.0.0.0/0`. Source: https://cloud.google.com/firewall/docs/firewalls
- The default network has `default-allow-internal` (`10.128.0.0/9`), `-ssh` and `-rdp` from anywhere, and `-icmp`. Source: https://cloud.google.com/firewall/docs/firewalls#more_rules_default_vpc
- Google health checks and proxy load balancers come from `130.211.0.0/22` and `35.191.0.0/16`. IAP TCP forwarding comes from `35.235.240.0/20`. Sources: https://cloud.google.com/load-balancing/docs/health-check-concepts#ip-ranges, https://cloud.google.com/iap/docs/using-tcp-forwarding
- Instance status `TERMINATED` means stopped, not deleted. Source: https://cloud.google.com/compute/docs/instances/instance-life-cycle
- Persistent disks are always encrypted at rest. Source: https://cloud.google.com/docs/security/encryption/default-encryption
- Cloud SQL `db-custom-<vcpu>-<mib>` tiers encode their size. `db-n1-standard-N` is 3.75 GiB per vCPU, `highmem` 6.5. Source: https://cloud.google.com/sql/docs/mysql/instance-settings
- `t2a`, `c4a` and `n4a` are Arm. `a2`, `a3`, `g2` carry GPUs. `c*`/`h*` are compute-optimized, `m*`/`x*` memory-optimized. Source: https://cloud.google.com/compute/docs/machine-resource
