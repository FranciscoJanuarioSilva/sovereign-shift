import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# built from parts so the secret check doesn't mistake it for a real key
FAKE_KEY_ID = "AKIA" + "A" * 16
spec = importlib.util.spec_from_file_location("serve", ROOT / "frontend/serve.py")
serve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serve)


@pytest.mark.parametrize("request_body, message", [
    ({"access_key_id": "nope", "secret_access_key": "x" * 40, "region": "eu-north-1"}, "access key ID"),
    ({"access_key_id": FAKE_KEY_ID, "secret_access_key": "short", "region": "eu-north-1"}, "access key ID"),
    ({"access_key_id": FAKE_KEY_ID, "secret_access_key": "x" * 40, "region": "mars-1"}, "region"),
])
def test_aws_form_is_checked_before_any_call(request_body: dict, message: str) -> None:
    with pytest.raises(serve.ScanProblem, match=message):
        serve.scan_aws(request_body)


def test_cloudflare_form_is_checked_before_any_call() -> None:
    with pytest.raises(serve.ScanProblem, match="account ID"):
        serve.scan_cloudflare({"account_id": "123", "api_token": "t"})


def test_static_files_cannot_escape_dist() -> None:
    for path in ("/../serve.py", "/../../.env", "/assets/../../serve.py", "/nope"):
        target, _ = serve.asset(path)
        assert target.resolve().is_relative_to(serve.DIST.resolve()), path


def test_demo_inventory_is_served() -> None:
    target, kind = serve.asset("/demo-inventory.json")
    assert target == serve.DEMO and kind == "application/json"


def test_write_check_reads_the_dry_run_answer() -> None:
    import botocore.exceptions

    class Ec2:
        def __init__(self, code: str) -> None:
            self.code = code

        def create_security_group(self, **kwargs):
            raise botocore.exceptions.ClientError({"Error": {"Code": self.code, "Message": ""}}, "CreateSecurityGroup")

    class Session:
        def __init__(self, code: str) -> None:
            self.code = code

        def client(self, name: str, region_name: str):
            return Ec2(self.code)

    assert serve.can_write(Session("DryRunOperation"), "eu-north-1") is True
    assert serve.can_write(Session("UnauthorizedOperation"), "eu-north-1") is False
