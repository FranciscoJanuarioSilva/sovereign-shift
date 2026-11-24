"""Serve the local dashboard: connect a cloud account or upload an inventory, get the assessment.

Credentials typed into the page are used in this process only, for read-only scans.
They are never written to disk, logged, put in the environment or sent to the AI.
"""

import json
import os
import shutil
import subprocess
import sys
from argparse import ArgumentParser
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from urllib.parse import urlsplit
from uuid import uuid4
import contextlib
import re

import boto3
import botocore.exceptions
import httpx

from sovereign_shift.scanner import aws as aws_scanner
from sovereign_shift.scanner import cloudflare as cloudflare_scanner
from sovereign_shift.scanner import gcp as gcp_scanner

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
MAX_INVENTORY_BYTES = 16 * 1024 * 1024
DEMO = ROOT.parent / "testdata/clickops_inventory.json"
TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".json": "application/json",
    ".woff2": "font/woff2", ".png": "image/png", ".ico": "image/x-icon",
}
AWS_REGION = re.compile(r"^[a-z]{2}(-[a-z]+)+-\d$")
AWS_KEY_ID = re.compile(r"^(AKIA|ASIA)[A-Z0-9]{16}$")
# leaseweb destinations the page offers, empty means "closest to the source" (mappings/regions.yaml)
DESTINATIONS = {"eu-west-3", "eu-central-1", ""}


class ScanProblem(Exception):
    """A message the page can show as is."""


def asset(path: str) -> tuple[Path, str] | None:
    # built react app in dist/, unknown paths fall back to index.html (single page app)
    if path == "/demo-inventory.json":
        return DEMO, "application/json"
    target = (DIST / path.lstrip("/")).resolve()
    if not target.is_relative_to(DIST.resolve()) or not target.is_file():
        target = DIST / "index.html"
    return target, TYPES.get(target.suffix, "application/octet-stream")


def can_write(session: boto3.Session, region: str) -> bool:
    # a dry run answers "would have succeeded" only when the key may create resources
    try:
        session.client("ec2", region_name=region).create_security_group(
            GroupName="sovereign-shift-write-check", Description="dry run only", DryRun=True)
    except botocore.exceptions.ClientError as error:
        return error.response["Error"]["Code"] == "DryRunOperation"
    return True


def scan_aws(request: dict) -> dict:
    key_id = str(request.get("access_key_id", "")).strip()
    secret = str(request.get("secret_access_key", "")).strip()
    token = str(request.get("session_token", "")).strip() or None
    region = str(request.get("region", "")).strip()
    if not AWS_KEY_ID.match(key_id) or len(secret) < 20:
        raise ScanProblem("Enter an AWS access key ID (AKIA… or ASIA…) and its secret access key.")
    if not AWS_REGION.match(region):
        raise ScanProblem("Choose the AWS region to scan, for example eu-north-1.")
    # explicit keys only: no profile, no shared files, so nothing on this machine is picked up instead
    session = boto3.Session(aws_access_key_id=key_id, aws_secret_access_key=secret,
                            aws_session_token=token, region_name=region)
    try:
        session.client("sts").get_caller_identity()
        if can_write(session, region):
            raise ScanProblem("This key can change resources in the account. Create a read-only key "
                              "(AWS managed policy ReadOnlyAccess) and use that one instead.")
        return aws_scanner.scan(session, [region])
    except botocore.exceptions.ClientError as error:
        code = error.response["Error"]["Code"]
        if code in {"InvalidClientTokenId", "SignatureDoesNotMatch", "UnrecognizedClientException", "ExpiredToken"}:
            raise ScanProblem("AWS rejected these credentials. Check the key ID, the secret and, for temporary keys, the session token.") from None
        raise ScanProblem(f"AWS refused {error.operation_name} ({code}). Attach the ReadOnlyAccess policy to this key.") from None
    except botocore.exceptions.BotoCoreError:
        raise ScanProblem("Could not reach AWS. Check the network connection and try again.") from None


GCP_PROJECT = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
GCP_READ_ONLY_SCOPES = {"https://www.googleapis.com/auth/cloud-platform.read-only", "https://www.googleapis.com/auth/compute.readonly",
                        "https://www.googleapis.com/auth/devstorage.read_only", "https://www.googleapis.com/auth/ndev.clouddns.readonly",
                        "openid", "https://www.googleapis.com/auth/userinfo.email"}
# a viewer can't do any of these, an editor or owner can
GCP_WRITE_PERMISSIONS = ["compute.instances.create", "compute.firewalls.create", "storage.buckets.create", "cloudsql.instances.create"]


def gcp_can_write(project: str, token: str, client: httpx.Client) -> bool:
    # 1) a token limited to read-only scopes can't write, whatever the role
    info = client.get("https://oauth2.googleapis.com/tokeninfo", params={"access_token": token})
    if info.status_code != 200:
        raise ScanProblem("Google rejected this access token. Create a fresh one with gcloud auth print-access-token.")
    scopes = set(str(info.json().get("scope", "")).split())
    if scopes and scopes <= GCP_READ_ONLY_SCOPES:
        return False
    # 2) otherwise ask which write permissions the caller holds on the project (testIamPermissions changes nothing)
    answer = client.post(f"https://cloudresourcemanager.googleapis.com/v1/projects/{project}:testIamPermissions",
                         json={"permissions": GCP_WRITE_PERMISSIONS})
    if answer.status_code != 200:
        raise ScanProblem("Could not check this token's permissions on the project. Use a viewer service account token.")
    return bool(answer.json().get("permissions"))


def scan_gcp(request: dict, transport: httpx.BaseTransport | None = None) -> dict:
    project = str(request.get("project_id", "")).strip()
    token = str(request.get("access_token", "")).strip()
    if not GCP_PROJECT.match(project) or len(token) < 20:
        raise ScanProblem("Enter the Google Cloud project ID and an access token from a viewer account.")
    with httpx.Client(timeout=30, headers={"Authorization": f"Bearer {token}"}, transport=transport) as client:
        try:
            if gcp_can_write(project, token, client):
                raise ScanProblem("This token can change resources in the project. Use a service account with the "
                                  "Viewer role, or a token with the cloud-platform.read-only scope.")
            return gcp_scanner.build_inventory(gcp_scanner.collect(project, client))
        except gcp_scanner.ScanError as error:
            raise ScanProblem(str(error)) from None
        except httpx.HTTPError:
            raise ScanProblem("Could not reach Google Cloud. Check the network connection and try again.") from None
        except (KeyError, TypeError, ValueError):
            raise ScanProblem("Google Cloud answered in an unexpected shape. Check the project ID.") from None


def scan_cloudflare(request: dict) -> dict:
    account = str(request.get("account_id", "")).strip()
    token = str(request.get("api_token", "")).strip()
    if not re.fullmatch(r"[a-fA-F0-9]{32}", account) or not token:
        raise ScanProblem("Enter the 32-character Cloudflare account ID and an API token with read permissions.")
    worker_name = str(request.get("worker_name") or "").strip()
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", worker_name):
        raise ScanProblem("Enter the Worker script name from the Cloudflare dashboard.")
    with httpx.Client(base_url="https://api.cloudflare.com/client/v4", timeout=30,
                      headers={"Authorization": f"Bearer {token}"}) as client:
        try:
            return cloudflare_scanner.scan_account(account, client, worker_name=worker_name)
        except cloudflare_scanner.ScanError as error:
            raise ScanProblem(str(error)) from None
        except httpx.HTTPError:
            raise ScanProblem("Could not reach Cloudflare. Check the network connection and try again.") from None


def analyse(inventory: bytes, use_ai: bool = False, target_region: str = "") -> tuple[dict, dict[str, str]]:
    with TemporaryDirectory(prefix="sovereign-assessment-") as folder:
        out = Path(folder)
        snapshot = out / "inventory.json"
        snapshot.write_bytes(inventory)
        subprocess.run(
            [
                sys.executable, "-m", "sovereign_shift.cli", "all",
                "--from-snapshot", str(snapshot), *([] if use_ai else ["--no-ai"]),
                *(["--target-region", target_region] if target_region else []), "--out", str(out),
            ],
            cwd=ROOT.parent,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=180 if use_ai else 60,
            check=True,
        )
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))
        files = {
            "terraform/" + file.name: file.read_text(encoding="utf-8")
            for file in sorted((out / "terraform").glob("*.tf"))
        }
        files["finalize.json"] = (out / "finalize.json").read_text(encoding="utf-8")
        return report, files


def validate(terraform: str, files: dict[str, str]) -> dict:
    with TemporaryDirectory(prefix="sovereign-terraform-") as folder:
        work = Path(folder)
        for name, contents in files.items():
            if name.startswith("terraform/"):
                (work / Path(name).name).write_text(contents, encoding="utf-8")
        env = {
            "HOME": folder,
            "PATH": os.defpath,
            "TF_IN_AUTOMATION": "1",
            "TF_CLI_CONFIG_FILE": str(work / "terraform.rc"),
        }
        output = []
        for command in (
            ["init", "-backend=false", "-input=false", "-no-color"],
            ["validate", "-no-color"],
        ):
            result = subprocess.run(
                [terraform, *command], cwd=work, env=env, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60,
            )
            output.append(result.stdout.strip())
            if result.returncode:
                break
        return {"passed": result.returncode == 0, "output": "\n\n".join(output)}


def serve(port: int, terraform: str | None = None, bind: str = "127.0.0.1", public_host: str = "") -> None:
    assessments: OrderedDict[str, dict[str, str]] = OrderedDict()
    lock = Lock()
    local_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    # behind a proxy the browser sends the public name, with whichever scheme the proxy uses
    allowed_origins = {f"http://{host}" for host in local_hosts}
    if public_host:
        local_hosts.add(public_host)
        allowed_origins |= {f"https://{public_host}", f"http://{public_host}"}

    class Handler(BaseHTTPRequestHandler):
        def reply(self, data: bytes, content_type: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def json_reply(self, data: dict, status: int = 200) -> None:
            self.reply(json.dumps(data).encode(), "application/json", status)

        def problem(self, status: int, message: str) -> None:
            self.json_reply({"error": message}, status)

        def do_GET(self) -> None:
            if self.headers.get("Host") not in local_hosts:
                self.send_error(403)
                return
            found = asset(urlsplit(self.path).path)
            if found is None:
                self.send_error(404)
                return
            filename, content_type = found
            try:
                data = filename.read_bytes()
            except OSError:
                self.send_error(500, "Could not read the requested file")
                return
            self.reply(data, content_type)

        def do_POST(self) -> None:
            host = self.headers.get("Host")
            if host not in local_hosts or self.headers.get("Origin") not in allowed_origins:
                self.problem(403, "Open the dashboard on localhost to analyse an inventory.")
                return
            route = urlsplit(self.path).path
            if route not in {"/analyse", "/validate", "/scan"}:
                self.send_error(404)
                return
            if self.headers.get_content_type() != "application/json":
                self.problem(415, "Select an AWS inventory JSON file.")
                return
            try:
                size = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self.problem(411, "The request needs a file size.")
                return
            if not 0 < size <= MAX_INVENTORY_BYTES:
                self.problem(413, "Select a non-empty inventory JSON of up to 16 MB.")
                return
            body = self.rfile.read(size)
            if route == "/validate":
                self.validate_assessment(body)
                return
            use_ai = False
            target_region = ""
            if route == "/scan":
                try:
                    request = json.loads(body)
                    if not isinstance(request, dict):
                        raise ValueError
                except ValueError:
                    self.problem(400, "The connection form could not be read. Reload the page and try again.")
                    return
                use_ai = request.get("use_ai") is True
                target_region = str(request.get("target_region", ""))
                if target_region not in DESTINATIONS:
                    self.problem(400, "Choose Amsterdam, Frankfurt or the region closest to the source.")
                    return
                try:
                    scanner = {"aws": scan_aws, "gcp": scan_gcp, "cloudflare": scan_cloudflare}.get(request.get("provider"))
                    inventory = scanner(request) if scanner else None
                except ScanProblem as error:
                    self.problem(422, str(error))
                    return
                finally:
                    # drop the secrets as soon as the scan is done
                    request.clear()
                if inventory is None:
                    self.problem(400, "Choose AWS, Google Cloud or Cloudflare.")
                    return
                body = json.dumps(inventory).encode()
            try:
                report, files = analyse(body, use_ai, target_region)
            except subprocess.TimeoutExpired:
                self.problem(504, "The local assessment timed out.")
                return
            except subprocess.CalledProcessError:
                self.problem(422, "Could not analyse this inventory. Select an inventory.json generated by the AWS scanner and check that the project is installed in the server's Python environment.")
                return
            except OSError:
                self.problem(500, "Could not read or write the local assessment files.")
                return
            assessment_id = uuid4().hex
            with lock:
                assessments[assessment_id] = files
                if len(assessments) > 8:
                    assessments.popitem(last=False)
            self.json_reply({"report": report, "files": files, "assessment_id": assessment_id, "ai": use_ai})

        def validate_assessment(self, body: bytes) -> None:
            try:
                request = json.loads(body)
                assessment_id = request.get("assessment_id")
                if not isinstance(assessment_id, str):
                    raise ValueError
            except (ValueError, AttributeError):
                self.problem(400, "A generated assessment is required.")
                return
            with lock:
                files = assessments.get(assessment_id)
            if files is None:
                self.problem(404, "This assessment has expired. Load the inventory or demo again.")
                return
            if not terraform:
                self.problem(503, "Terraform is unavailable. Add it to PATH or restart with --terraform /path/to/terraform.")
                return
            try:
                result = validate(terraform, files)
            except subprocess.TimeoutExpired:
                self.problem(504, "Terraform validation timed out.")
                return
            except OSError:
                self.problem(500, "Could not run the configured Terraform executable.")
                return
            self.json_reply(result)

    with ThreadingHTTPServer((bind, port), Handler) as server:
        print(f"Frontend: http://{bind}:{port}", flush=True)
        with contextlib.suppress(KeyboardInterrupt):
            server.serve_forever()


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--terraform", type=Path, help="Path to the Terraform executable")
    parser.add_argument("--bind", default="127.0.0.1", help="Address to listen on, 0.0.0.0 inside a container")
    parser.add_argument("--public-host", default=os.environ.get("SOVEREIGN_PUBLIC_HOST", ""), help="Public hostname served behind a tls proxy")
    args = parser.parse_args()
    terraform = str(args.terraform.resolve()) if args.terraform else shutil.which("terraform")
    serve(args.port, terraform, args.bind, args.public_host)
