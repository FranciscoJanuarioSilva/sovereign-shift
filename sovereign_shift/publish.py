"""Copy the shareable artifacts to out/public with the aws account id masked."""

import re
from pathlib import Path

# what we hand out, inventory.json stays private (raw ids, ips, public keys)
SHAREABLE = [
    "graph.json", "graph.html", "findings.json", "mapping.json", "runbook.json",
    "finalize.json", "report.json", "report.md",
]


def mask(text: str, account_id: str) -> str:
    masked = text.replace(account_id, "****" + account_id[-4:]) if account_id else text
    # belt and braces: any other 12-digit account number inside an arn
    return re.sub(r"(arn:aws[\w-]*:[\w-]*:[\w-]*:)(\d{8})(\d{4})", r"\1****\3", masked)


def publish(out: Path, account_id: str, dest: Path | None = None) -> list[Path]:
    dest = dest or out / "public"
    files = [out / name for name in SHAREABLE if (out / name).exists()]
    files += sorted((out / "terraform").glob("*.tf"))
    written = []
    for src in files:
        target = dest / src.relative_to(out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(mask(src.read_text(), account_id))
        written.append(target)
    return written
