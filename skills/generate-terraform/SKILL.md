---
name: generate-terraform
description: Renders Leaseweb Terraform (instances, load balancers, listeners, target groups, DNS records) and finalize.json from mapping.json. Use it when changing the generated Terraform or adding a resource kind.
---

# Generate Terraform

Part of: sovereign-shift. Code: `sovereign_shift/generator/`. Schema: `docs/schemas/leaseweb.json`. Facts: `docs/research/leaseweb-terraform.md`.

## Rules
- Never emit an attribute that isn't in the provider schema. Everything generated must pass `terraform validate`:
  `podman run --rm -v "$PWD/out/terraform":/w:Z -w /w docker.io/hashicorp/terraform:1.9.8 validate`
- Labels come from the translator's `tf_name`, never raw AWS ids (ARNs carry the account id).
- `user_data` is plain text cloud-init: brings up the private interface with DHCP and carries the SSH key.
- Security groups and target registrations go to `finalize.json`, not Terraform.
