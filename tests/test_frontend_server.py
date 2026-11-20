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


# google cloud: no live project, so these run against a mock transport (like tests for the gcp scanner)
READ_ONLY = "https://www.googleapis.com/auth/cloud-platform.read-only"
FULL = "https://www.googleapis.com/auth/cloud-platform"
FAKE_TOKEN = "ya29." + "x" * 40


def google(scope: str, granted: list[str], tokeninfo_status: int = 200):
    import httpx

    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.host, request.url.path))
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(tokeninfo_status, json={"scope": scope})
        if request.url.path.endswith(":testIamPermissions"):
            return httpx.Response(200, json={"permissions": granted} if granted else {})
        return httpx.Response(404, json={})

    return httpx.MockTransport(handle), calls


@pytest.fixture
def fake_collect(monkeypatch):
    monkeypatch.setattr(serve.gcp_scanner, "collect", lambda project, client: {"project": project})
    monkeypatch.setattr(serve.gcp_scanner, "build_inventory", lambda raw: {"source": "gcp", "resources": [], "project": raw["project"]})


def test_gcp_read_only_scope_is_scanned_without_asking_iam(fake_collect) -> None:
    transport, calls = google(READ_ONLY, [])
    inventory = serve.scan_gcp({"project_id": "shop-prod-123", "access_token": FAKE_TOKEN}, transport)
    assert inventory["source"] == "gcp" and inventory["project"] == "shop-prod-123"
    assert not any(path.endswith(":testIamPermissions") for _, _, path in calls)


def test_gcp_viewer_with_full_scope_is_allowed(fake_collect) -> None:
    transport, _ = google(FULL, [])
    assert serve.scan_gcp({"project_id": "shop-prod-123", "access_token": FAKE_TOKEN}, transport)["source"] == "gcp"


def test_gcp_editor_token_is_refused(fake_collect) -> None:
    transport, _ = google(FULL, ["compute.instances.create"])
    with pytest.raises(serve.ScanProblem, match="can change resources"):
        serve.scan_gcp({"project_id": "shop-prod-123", "access_token": FAKE_TOKEN}, transport)


def test_gcp_rejected_token(fake_collect) -> None:
    transport, _ = google(READ_ONLY, [], tokeninfo_status=400)
    with pytest.raises(serve.ScanProblem, match="rejected this access token"):
        serve.scan_gcp({"project_id": "shop-prod-123", "access_token": FAKE_TOKEN}, transport)


def test_gcp_form_is_checked_before_any_call() -> None:
    with pytest.raises(serve.ScanProblem, match="project ID"):
        serve.scan_gcp({"project_id": "Bad_Project", "access_token": FAKE_TOKEN})


def test_gcp_full_path_with_recorded_responses() -> None:
    # same recorded REST responses as tests/test_gcp.py, behind the server's token check
    import json

    import httpx

    from tests.test_gcp import FIXTURE, GOLDEN, fake_api

    recorded = fake_api([])

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"scope": READ_ONLY})
        return recorded(request)

    inventory = serve.scan_gcp({"project_id": FIXTURE["project"], "access_token": FAKE_TOKEN}, httpx.MockTransport(handle))
    golden = json.loads(GOLDEN.read_text())
    assert sorted(r["id"] for r in inventory["resources"]) == sorted(r["id"] for r in golden["resources"])
