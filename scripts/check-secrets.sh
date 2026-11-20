#!/usr/bin/env bash
# blocks commits that contain credentials. install: ln -sf ../../scripts/check-secrets.sh .git/hooks/pre-commit
# with no args it checks staged files, with --all it checks every tracked file
set -euo pipefail
pattern='AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|aws_secret_access_key[[:space:]]*=[[:space:]]*[A-Za-z0-9/+]{20,}|sk-or-v1-[0-9a-f]{20,}|sk-[A-Za-z0-9]{32,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|LEASEWEB_TOKEN=[0-9a-fA-F-]{20,}|SOVEREIGN_AI_API_KEY=[^[:space:]]+'
if [ "${1:-}" = "--all" ]; then
  files=$(git ls-files)
else
  files=$(git diff --cached --name-only --diff-filter=ACM)
fi
[ -z "$files" ] && exit 0
# the script itself holds the patterns, skip it
hits=$(echo "$files" | grep -v '^scripts/check-secrets.sh$' | xargs -r grep -nIE "$pattern" -- 2>/dev/null || true)
if [ -n "$hits" ]; then
  echo "possible secrets found, commit blocked:" >&2
  echo "$hits" | cut -c1-120 >&2
  exit 1
fi
