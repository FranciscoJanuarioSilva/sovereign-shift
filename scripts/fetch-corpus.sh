#!/usr/bin/env bash
# clones the reference terraform repos into corpus/ (gitignored), shallow so it stays small
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
dest="$root/corpus"
mkdir -p "$dest/leaseweb" "$dest/aws" "$dest/tools"

clone() {
  local repo="$1" dir="$2"
  if [ -d "$dir/.git" ]; then
    echo "skip $repo (already there)"
    return
  fi
  echo "clone $repo"
  git clone --depth 1 --quiet "https://github.com/$repo.git" "$dir"
}

# sparse clone, for big repos where we only want a few folders
sparse() {
  local repo="$1" dir="$2"; shift 2
  if [ -d "$dir/.git" ]; then
    echo "skip $repo (already there)"
    return
  fi
  echo "sparse clone $repo ($*)"
  git clone --depth 1 --quiet --filter=blob:none --sparse "https://github.com/$repo.git" "$dir"
  # no-cone so single files work, not just folders
  git -C "$dir" sparse-checkout set --no-cone "$@"
}

# leaseweb, ground truth for every resource
clone leaseweb/terraform-provider-leaseweb "$dest/leaseweb/terraform-provider-leaseweb"
# only real-world leaseweb modules we found on github
clone remerge/terraform-modules "$dest/leaseweb/remerge-terraform-modules"

# aws, plain resources (closest to what a scan produces)
sparse hashicorp/terraform-provider-aws "$dest/aws/terraform-provider-aws" \
  /examples/ /website/docs/r/instance.html.markdown /website/docs/r/vpc.html.markdown \
  /website/docs/r/subnet.html.markdown /website/docs/r/security_group.html.markdown \
  /website/docs/r/vpc_security_group_ingress_rule.html.markdown /website/docs/r/ebs_volume.html.markdown \
  /website/docs/r/eip.html.markdown /website/docs/r/db_instance.html.markdown \
  /website/docs/r/s3_bucket.html.markdown /website/docs/r/lb.html.markdown \
  /website/docs/r/lb_listener.html.markdown /website/docs/r/lb_target_group.html.markdown \
  /website/docs/r/route53_record.html.markdown /website/docs/r/key_pair.html.markdown
clone hashicorp-education/learn-terraform-resources "$dest/aws/learn-terraform-resources"
clone hashicorp-education/learn-terraform-rds "$dest/aws/learn-terraform-rds"
clone hashicorp-education/learn-terraform-import "$dest/aws/learn-terraform-import"
clone futurice/terraform-examples "$dest/aws/futurice-terraform-examples"

# aws, popular modules
for m in vpc ec2-instance security-group alb rds s3-bucket; do
  clone "terraform-aws-modules/terraform-aws-$m" "$dest/aws/terraform-aws-$m"
done

# tools we compare against (reference only, not dependencies)
clone iann0036/former2 "$dest/tools/former2"

echo "done, corpus in $dest"
