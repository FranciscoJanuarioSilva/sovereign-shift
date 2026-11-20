"""builds (and tears down) the "clickops" demo setup in our own aws test account.

this is a test fixture for the scanner, not part of the product.
it uses the write profile, the scanner only ever uses the read-only one.
it creates bad settings on purpose, so the scanner has findings to show.

usage:
  python -I scripts/demo-account/demo_account.py up
  python -I scripts/demo-account/demo_account.py status
  python -I scripts/demo-account/demo_account.py down
"""
import json
import os
import sys
import time
import uuid
from pathlib import Path

import boto3
import botocore

PROFILE = os.environ.get("DEMO_PROFILE", "sovereign-admin")
REGION = "eu-north-1"
TAG = {"Key": "sovereign-shift-demo", "Value": "true"}
STATE = Path(__file__).with_name("state.json")
KEY_FILE = Path.home() / ".ssh" / "sovereign-demo-ops-key.pem"

# nginx so the alb health check passes, nothing secret in here
WEB_USER_DATA = """#!/bin/bash
apt-get update -y && apt-get install -y nginx
echo "<h1>orders shop - $(hostname)</h1>" > /var/www/html/index.html
systemctl enable --now nginx
"""

s = boto3.Session(profile_name=PROFILE, region_name=REGION)
ec2, elb, rds, s3 = s.client("ec2"), s.client("elbv2"), s.client("rds"), s.client("s3")


def tags(name: str, **extra: str) -> list[dict]:
    t = [TAG, {"Key": "Name", "Value": name}, {"Key": "env", "Value": "prod"}]
    return t + [{"Key": k, "Value": v} for k, v in extra.items()]


def spec(rtype: str, name: str) -> list[dict]:
    return [{"ResourceType": rtype, "Tags": tags(name)}]


def load() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save(st: dict) -> None:
    STATE.write_text(json.dumps(st, indent=1))


def step(st: dict, key: str, fn):
    # idempotent-ish: skip steps that already ran
    if key in st:
        print(f"skip {key}: {st[key]}")
        return st[key]
    try:
        st[key] = fn()
        print(f"ok   {key}: {st[key]}")
    except botocore.exceptions.ClientError as e:
        print(f"FAIL {key}: {e.response['Error']['Code']}: {e.response['Error']['Message'][:200]}")
        st[key + "_error"] = e.response["Error"]["Code"]
    save(st)
    return st.get(key)


def ubuntu_ami() -> str:
    imgs = ec2.describe_images(Owners=["099720109477"], Filters=[
        {"Name": "name", "Values": ["ubuntu/images/hvm-ssd*/ubuntu-jammy-22.04-amd64-server-*"]},
        {"Name": "state", "Values": ["available"]}])["Images"]
    return sorted(imgs, key=lambda i: i["CreationDate"])[-1]["ImageId"]


def default_vpc() -> tuple[str, list[str]]:
    vpc = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"][0]["VpcId"]
    subs = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc]}])["Subnets"]
    return vpc, [x["SubnetId"] for x in sorted(subs, key=lambda x: x["AvailabilityZone"])]


def sg(name: str, desc: str, vpc: str) -> str:
    return ec2.create_security_group(GroupName=name, Description=desc, VpcId=vpc,
                                     TagSpecifications=spec("security-group", name))["GroupId"]


def ingress(group: str, port: int, cidr: str | None = None, src_group: str | None = None, desc: str = "") -> str:
    perm = {"IpProtocol": "tcp", "FromPort": port, "ToPort": port}
    if cidr:
        perm["IpRanges"] = [{"CidrIp": cidr, "Description": desc}]
    if src_group:
        perm["UserIdGroupPairs"] = [{"GroupId": src_group, "Description": desc}]
    ec2.authorize_security_group_ingress(GroupId=group, IpPermissions=[perm])
    return f"{group}:{port}<-{cidr or src_group}"


def key_pair() -> str:
    k = ec2.create_key_pair(KeyName="ops-key", KeyType="ed25519", TagSpecifications=spec("key-pair", "ops-key"))
    KEY_FILE.parent.mkdir(mode=0o700, exist_ok=True)
    KEY_FILE.write_text(k["KeyMaterial"])
    KEY_FILE.chmod(0o600)
    return k["KeyPairId"]


# the account is on the aws free plan: only free-tier types launch (others fail with InvalidParameterCombination)
# dry-run doesn't catch it, only a real launch does
FREE_TYPES = ["m7i-flex.large", "c7i-flex.large", "t3.small", "t3.micro"]


def instance(name: str, ami: str, subnet: str, group: str, types: list[str] = FREE_TYPES) -> str:
    for t in types:
        try:
            return _launch(name, ami, subnet, group, t)
        except botocore.exceptions.ClientError as e:
            if "not eligible for Free Tier" not in e.response["Error"]["Message"]:
                raise
            print(f"     {t} not free-tier, trying next")
    raise RuntimeError("no free-tier instance type worked")


def _launch(name: str, ami: str, subnet: str, group: str, itype: str) -> str:
    r = ec2.run_instances(
        ImageId=ami, InstanceType=itype, MinCount=1, MaxCount=1, KeyName="ops-key",
        SubnetId=subnet, SecurityGroupIds=[group], UserData=WEB_USER_DATA,
        # imdsv1 allowed on purpose (finding EC2-001), root volume unencrypted (EC2-002)
        MetadataOptions={"HttpTokens": "optional", "HttpEndpoint": "enabled"},
        BlockDeviceMappings=[{"DeviceName": "/dev/sda1", "Ebs": {"VolumeSize": 30, "VolumeType": "gp3", "Encrypted": False, "DeleteOnTermination": True}}],
        TagSpecifications=spec("instance", name) + spec("volume", f"{name}-root"))
    return r["Instances"][0]["InstanceId"]


def wait_running(ids: list[str]) -> None:
    ec2.get_waiter("instance_running").wait(InstanceIds=ids)


def data_volume(instance_id: str) -> str:
    az = ec2.describe_instances(InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]["Placement"]["AvailabilityZone"]
    v = ec2.create_volume(AvailabilityZone=az, Size=20, VolumeType="gp3", Encrypted=False,
                          TagSpecifications=spec("volume", "web-1-uploads"))["VolumeId"]
    ec2.get_waiter("volume_available").wait(VolumeIds=[v])
    ec2.attach_volume(VolumeId=v, InstanceId=instance_id, Device="/dev/sdf")
    return v


def eip(instance_id: str) -> str:
    a = ec2.allocate_address(Domain="vpc", TagSpecifications=spec("elastic-ip", "web-1-ip"))
    ec2.associate_address(AllocationId=a["AllocationId"], InstanceId=instance_id)
    return a["AllocationId"]


def alb(subnets: list[str], group: str) -> str:
    return elb.create_load_balancer(Name="web-alb", Subnets=subnets[:2], SecurityGroups=[group], Scheme="internet-facing",
                                    Type="application", Tags=tags("web-alb"))["LoadBalancers"][0]["LoadBalancerArn"]


def target_group(vpc: str, targets: list[str]) -> str:
    tg = elb.create_target_group(Name="web-tg", Protocol="HTTP", Port=80, VpcId=vpc, TargetType="instance",
                                 HealthCheckPath="/", Tags=tags("web-tg"))["TargetGroups"][0]["TargetGroupArn"]
    elb.register_targets(TargetGroupArn=tg, Targets=[{"Id": t, "Port": 80} for t in targets])
    return tg


def listener(lb: str, tg: str) -> str:
    # plain http, no https redirect (finding ELB-001)
    return elb.create_listener(LoadBalancerArn=lb, Protocol="HTTP", Port=80, Tags=tags("web-http"),
                               DefaultActions=[{"Type": "forward", "TargetGroupArn": tg}])["Listeners"][0]["ListenerArn"]


def database(group: str) -> str:
    # public, unencrypted, no backups, all on purpose (RDS-001/002/003)
    # aws manages the master password in secrets manager, so it never passes through us
    rds.create_db_instance(
        DBInstanceIdentifier="orders-db", DBName="orders", Engine="postgres", DBInstanceClass="db.t4g.micro",
        AllocatedStorage=20, StorageType="gp2", MasterUsername="orders_admin", ManageMasterUserPassword=True,
        VpcSecurityGroupIds=[group], PubliclyAccessible=True, StorageEncrypted=False, BackupRetentionPeriod=0,
        MultiAZ=False, DeletionProtection=False, Tags=tags("orders-db"))
    return "orders-db"


def bucket() -> str:
    name = f"orders-shop-assets-{uuid.uuid4().hex[:8]}"
    s3.create_bucket(Bucket=name, CreateBucketConfiguration={"LocationConstraint": REGION})
    s3.put_bucket_tagging(Bucket=name, Tagging={"TagSet": tags(name)})
    s3.put_object(Bucket=name, Key="index.html", Body=b"<h1>orders shop assets</h1>", ContentType="text/html")
    return name


def make_public(name: str) -> str:
    # public read on purpose (S3-001/S3-002)
    s3.delete_public_access_block(Bucket=name)
    policy = {"Version": "2012-10-17", "Statement": [{"Sid": "PublicRead", "Effect": "Allow", "Principal": "*",
              "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{name}/*"}]}
    s3.put_bucket_policy(Bucket=name, Policy=json.dumps(policy))
    return "public-read"


def up() -> None:
    st = load()
    vpc, subnets = default_vpc()
    st.setdefault("vpc", vpc)
    ami = step(st, "ami", ubuntu_ami)
    step(st, "key_pair", key_pair)
    web_sg = step(st, "web_sg", lambda: sg("web-sg", "web servers", vpc))
    alb_sg = step(st, "alb_sg", lambda: sg("alb-sg", "load balancer", vpc))
    db_sg = step(st, "db_sg", lambda: sg("db-sg", "orders database", vpc))
    step(st, "rule_web_80", lambda: ingress(web_sg, 80, cidr="0.0.0.0/0", desc="http"))
    step(st, "rule_web_443", lambda: ingress(web_sg, 443, cidr="0.0.0.0/0", desc="https"))
    step(st, "rule_web_22", lambda: ingress(web_sg, 22, cidr="0.0.0.0/0", desc="ssh from anywhere, temporary"))
    step(st, "rule_alb_80", lambda: ingress(alb_sg, 80, cidr="0.0.0.0/0", desc="http"))
    step(st, "rule_db_from_web", lambda: ingress(db_sg, 5432, src_group=web_sg, desc="app servers"))
    step(st, "rule_db_world", lambda: ingress(db_sg, 5432, cidr="0.0.0.0/0", desc="debug from home"))
    w1 = step(st, "web_1", lambda: instance("web-1", ami, subnets[0], web_sg))
    w2 = step(st, "web_2", lambda: instance("web-2", ami, subnets[1], web_sg))
    step(st, "db", lambda: database(db_sg))
    b = step(st, "bucket", bucket)
    if b:
        step(st, "bucket_public", lambda: make_public(b))
    lb = step(st, "alb", lambda: alb(subnets, alb_sg))
    print("waiting for instances to run...")
    wait_running([w1, w2])
    step(st, "data_volume", lambda: data_volume(w1))
    step(st, "eip", lambda: eip(w1))
    tg = step(st, "target_group", lambda: target_group(vpc, [w1, w2]))
    if lb and tg:
        step(st, "listener", lambda: listener(lb, tg))
    print("done. rds takes ~5-10 min more to become available, check with: status")


def status() -> None:
    st = load()
    print(json.dumps({k: v for k, v in st.items()}, indent=1))
    try:
        d = rds.describe_db_instances(DBInstanceIdentifier="orders-db")["DBInstances"][0]
        print("rds:", d["DBInstanceStatus"])
    except botocore.exceptions.ClientError as e:
        print("rds:", e.response["Error"]["Code"])
    if st.get("target_group"):
        h = elb.describe_target_health(TargetGroupArn=st["target_group"])["TargetHealthDescriptions"]
        print("targets:", [(x["Target"]["Id"], x["TargetHealth"]["State"]) for x in h])
    if st.get("alb"):
        print("alb dns:", elb.describe_load_balancers(LoadBalancerArns=[st["alb"]])["LoadBalancers"][0]["DNSName"])


def quiet(label: str, fn) -> None:
    try:
        fn()
        print(f"deleted {label}")
    except botocore.exceptions.ClientError as e:
        print(f"skip {label}: {e.response['Error']['Code']}")


def down() -> None:
    st = load()
    if st.get("listener"):
        quiet("listener", lambda: elb.delete_listener(ListenerArn=st["listener"]))
    if st.get("alb"):
        quiet("alb", lambda: elb.delete_load_balancer(LoadBalancerArn=st["alb"]))
    quiet("rds", lambda: rds.delete_db_instance(DBInstanceIdentifier="orders-db", SkipFinalSnapshot=True, DeleteAutomatedBackups=True))
    if st.get("eip"):
        def release():
            a = ec2.describe_addresses(AllocationIds=[st["eip"]])["Addresses"][0]
            if a.get("AssociationId"):
                ec2.disassociate_address(AssociationId=a["AssociationId"])
            ec2.release_address(AllocationId=st["eip"])
        quiet("eip", release)
    ids = [i for i in (st.get("web_1"), st.get("web_2")) if i]
    if ids:
        quiet("instances", lambda: ec2.terminate_instances(InstanceIds=ids))
        print("waiting for instances to terminate...")
        ec2.get_waiter("instance_terminated").wait(InstanceIds=ids)
    if st.get("data_volume"):
        quiet("data volume", lambda: ec2.delete_volume(VolumeId=st["data_volume"]))
    if st.get("target_group"):
        time.sleep(5)
        quiet("target group", lambda: elb.delete_target_group(TargetGroupArn=st["target_group"]))
    if st.get("bucket"):
        def empty_and_delete():
            for o in s3.list_objects_v2(Bucket=st["bucket"]).get("Contents", []):
                s3.delete_object(Bucket=st["bucket"], Key=o["Key"])
            s3.delete_bucket(Bucket=st["bucket"])
        quiet("bucket", empty_and_delete)
    quiet("key pair", lambda: ec2.delete_key_pair(KeyName="ops-key"))
    # security groups go last, the alb and rds hold on to them for a while
    for key in ("db_sg", "alb_sg", "web_sg"):
        if st.get(key):
            for attempt in range(12):
                try:
                    ec2.delete_security_group(GroupId=st[key])
                    print(f"deleted {key}")
                    break
                except botocore.exceptions.ClientError as e:
                    if e.response["Error"]["Code"] != "DependencyViolation" or attempt == 11:
                        print(f"skip {key}: {e.response['Error']['Code']} (rerun down later)")
                        break
                    time.sleep(20)
    print("done. if rds or a security group was still busy, run down again in a few minutes.")


if __name__ == "__main__":
    {"up": up, "down": down, "status": status}[sys.argv[1]]()
