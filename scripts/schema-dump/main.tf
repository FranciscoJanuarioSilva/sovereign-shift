terraform {
  required_providers {
    leaseweb  = { source = "leaseweb/leaseweb" }
    aws       = { source = "hashicorp/aws" }
    openstack = { source = "terraform-provider-openstack/openstack" }
  }
}
