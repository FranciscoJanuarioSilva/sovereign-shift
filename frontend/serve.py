"""Serve the local dashboard and analyse uploaded AWS inventories offline."""

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

ROOT = Path(__file__).resolve().parent
MAX_INVENTORY_BYTES = 16 * 1024 * 1024
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/demo-inventory.json": ("../testdata/clickops_inventory.json", "application/json"),
}


def analyse(inventory: bytes) -> tuple[dict, dict[str, str]]:
    with TemporaryDirectory(prefix="sovereign-assessment-") as folder:
        out = Path(folder)
        snapshot = out / "inventory.json"
        snapshot.write_bytes(inventory)
        subprocess.run(
            [
                sys.executable, "-m", "sovereign_shift.cli", "all",
                "--from-snapshot", str(snapshot), "--no-ai", "--out", str(out),
            ],
            cwd=ROOT.parent,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
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


def serve(port: int, terraform: str | None = None) -> None:
    assessments: OrderedDict[str, dict[str, str]] = OrderedDict()
    lock = Lock()
    local_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

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
            asset = ASSETS.get(urlsplit(self.path).path)
            if asset is None:
                self.send_error(404)
                return
            filename, content_type = asset
            try:
                data = (ROOT / filename).read_bytes()
            except OSError:
                self.send_error(500, "Could not read the requested file")
                return
            self.reply(data, content_type)

        def do_POST(self) -> None:
            host = self.headers.get("Host")
            if host not in local_hosts or self.headers.get("Origin") != f"http://{host}":
                self.problem(403, "Open the dashboard on localhost to analyse an inventory.")
                return
            route = urlsplit(self.path).path
            if route not in {"/analyse", "/validate"}:
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
            try:
                report, files = analyse(body)
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
            self.json_reply({"report": report, "files": files, "assessment_id": assessment_id})

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

    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        print(f"Frontend: http://127.0.0.1:{port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--terraform", type=Path, help="Path to the Terraform executable")
    args = parser.parse_args()
    terraform = str(args.terraform.resolve()) if args.terraform else shutil.which("terraform")
    serve(args.port, terraform)
