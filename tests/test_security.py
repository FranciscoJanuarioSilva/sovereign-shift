from sovereign_shift.graph.security import findings


def ids(resource: dict) -> set[str]:
    return {f["id"] for f in findings({"resources": [resource]}, {"edges": []})}


def thing(kind: str, **props) -> dict:
    return {"id": f"{kind}-1", "type": kind, "name": kind, "properties": props, "relations": []}


# shapes below are what the real scanner writes (see examples/aws_demo_inventory.json)

def test_public_bucket_from_the_scanner() -> None:
    bucket = thing("s3_bucket", policy_public=True, acl_public=False, public_access_block={},
                   encryption=["AES256"], versioning="Disabled")
    assert ids(bucket) == {"S3-001", "S3-002", "S3-004"}


def test_locked_down_bucket_has_no_findings() -> None:
    block = dict.fromkeys(["BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"], True)
    bucket = thing("s3_bucket", policy_public=False, acl_public=False, public_access_block=block,
                   encryption=["aws:kms"], versioning="Enabled")
    assert ids(bucket) == set()


def test_bucket_without_default_encryption() -> None:
    assert "S3-003" in ids(thing("s3_bucket", encryption=[]))


def test_static_website_bucket_is_not_flagged_public() -> None:
    assert "S3-001" not in ids(thing("s3_bucket", policy_public=True, static_website=True))


def test_missing_evidence_raises_nothing() -> None:
    assert ids(thing("s3_bucket")) == set()
    assert ids(thing("db_instance")) == set()


def test_rds_without_backups() -> None:
    db = thing("db_instance", publicly_accessible=False, storage_encrypted=True, backup_retention_days=0)
    assert ids(db) == {"RDS-003"}


def test_http_listener_without_redirect() -> None:
    assert ids(thing("lb_listener", protocol="HTTP", port=80, redirects_to_https=False)) == {"ELB-001"}
    assert ids(thing("lb_listener", protocol="HTTP", port=80, redirects_to_https=True)) == set()


def test_only_default_vpc() -> None:
    assert ids(thing("vpc", cidr="172.31.0.0/16", default=True)) == {"NET-001"}
