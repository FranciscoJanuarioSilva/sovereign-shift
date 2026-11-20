"""cuts the huge `terraform providers schema -json` dump down to the resources we care about.

usage: python3 -I scripts/extract_schemas.py corpus/schemas/providers-schema.json docs/schemas
"""
import json
import sys
from pathlib import Path

AWS_IN_SCOPE = [
    "aws_instance", "aws_vpc", "aws_subnet", "aws_security_group",
    "aws_vpc_security_group_ingress_rule", "aws_vpc_security_group_egress_rule",
    "aws_ebs_volume", "aws_volume_attachment", "aws_eip", "aws_key_pair",
    "aws_internet_gateway", "aws_nat_gateway", "aws_route_table",
    "aws_db_instance", "aws_db_subnet_group", "aws_s3_bucket", "aws_s3_bucket_policy",
    "aws_s3_bucket_public_access_block", "aws_lb", "aws_lb_listener",
    "aws_lb_target_group", "aws_lb_target_group_attachment",
    "aws_route53_zone", "aws_route53_record",
]

OPENSTACK_IN_SCOPE = [
    "openstack_compute_instance_v2", "openstack_compute_keypair_v2",
    "openstack_networking_network_v2", "openstack_networking_subnet_v2",
    "openstack_networking_router_v2", "openstack_networking_router_interface_v2",
    "openstack_networking_secgroup_v2", "openstack_networking_secgroup_rule_v2",
    "openstack_networking_floatingip_v2", "openstack_networking_floatingip_associate_v2",
    "openstack_networking_port_v2", "openstack_blockstorage_volume_v3",
    "openstack_compute_volume_attach_v2", "openstack_lb_loadbalancer_v2",
    "openstack_lb_listener_v2", "openstack_lb_pool_v2", "openstack_lb_member_v2",
    "openstack_lb_monitor_v2",
]


def pick(schemas: dict, names: list[str]) -> dict:
    # keep only what we asked for, and say if something is missing
    out = {}
    for n in names:
        if n in schemas:
            out[n] = schemas[n]
        else:
            print(f"warning: {n} not in schema dump", file=sys.stderr)
    return out


def main() -> None:
    src, dest = Path(sys.argv[1]), Path(sys.argv[2])
    dest.mkdir(parents=True, exist_ok=True)
    data = json.loads(src.read_text())
    ps = data["provider_schemas"]

    lw = ps["registry.terraform.io/leaseweb/leaseweb"]
    aws = ps["registry.terraform.io/hashicorp/aws"]
    ost = ps["registry.terraform.io/terraform-provider-openstack/openstack"]

    files = {
        # leaseweb is small, keep all of it
        "leaseweb.json": lw,
        "aws-subset.json": {"resource_schemas": pick(aws["resource_schemas"], AWS_IN_SCOPE)},
        "openstack-subset.json": {
            "provider": ost.get("provider"),
            "resource_schemas": pick(ost["resource_schemas"], OPENSTACK_IN_SCOPE),
        },
    }
    for name, body in files.items():
        (dest / name).write_text(json.dumps(body, indent=1, sort_keys=True) + "\n")
        print(f"wrote {dest / name}")


if __name__ == "__main__":
    main()
