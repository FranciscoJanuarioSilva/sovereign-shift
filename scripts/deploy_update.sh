#!/usr/bin/env bash
# pushes the committed HEAD to the dashboard vm and restarts the service
# usage: SSH_PASSWORD=... scripts/deploy_update.sh   (or run it and type the password when asked)
# the server is not a git checkout, so the code is copied with git archive
# frontend/dist is committed, so nothing gets built on the server
set -euo pipefail

host="${DEPLOY_HOST:?set DEPLOY_HOST to the server address}"
user="${DEPLOY_USER:-ubuntu}"
dir=/opt/sovereign-shift
service=sovereign-shift-dashboard
here="$(cd "$(dirname "$0")/.." && pwd)"
cd "$here"

if [ -n "$(git status --porcelain)" ]; then
  echo "warning: uncommitted changes are not deployed, only HEAD ($(git rev-parse --short HEAD)) is" >&2
fi

archive="$(mktemp)"
trap 'rm -f "$archive"' EXIT
git archive --format=tar HEAD > "$archive"

if [ -z "${SSH_PASSWORD:-}" ]; then
  read -rsp "password for $user@$host: " SSH_PASSWORD; echo
fi
export SSH_PASSWORD

python3 -I - "$host" "$user" "$archive" "$dir" "$service" <<'PY'
import os
import sys

import paramiko

host, user, archive, folder, service = sys.argv[1:6]
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.RejectPolicy())
client.load_system_host_keys()
client.connect(host, username=user, password=os.environ["SSH_PASSWORD"], timeout=15,
               look_for_keys=False, allow_agent=False)


def run(command: str, stdin: bytes | None = None) -> str:
    stdin_channel, out, err = client.exec_command(command)
    if stdin is not None:
        stdin_channel.write(stdin)
        stdin_channel.channel.shutdown_write()
    code = out.channel.recv_exit_status()
    text = (out.read() + err.read()).decode().strip()
    if code != 0:
        sys.exit(f"remote command failed ({code}): {command}\n{text}")
    return text


payload = open(archive, "rb").read()
run(f"sudo mkdir -p {folder} && sudo chown {user}:{user} {folder} && find {folder} -mindepth 1 -maxdepth 1 ! -name .venv -exec rm -rf {{}} + && tar -x -C {folder}", payload)
# the dashboard has to listen on all interfaces so the proxy can reach it
run(f"sed -i 's/ThreadingHTTPServer((\"127.0.0.1\", port)/ThreadingHTTPServer((\"0.0.0.0\", port)/' {folder}/frontend/serve.py")
run(f"sudo systemctl restart {service}")
run("sleep 3 && systemctl is-active " + service)
print(run("curl -s -o /dev/null -w 'local http %{http_code}\\n' -H 'Host: 127.0.0.1:8001' http://127.0.0.1:8001/"))
client.close()
PY
