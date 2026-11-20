import json
from pathlib import Path

from typer.testing import CliRunner

from sovereign_shift.cli import app
from sovereign_shift.publish import mask

FIXTURE = Path(__file__).resolve().parents[1] / "testdata" / "clickops_inventory.json"
ACCOUNT = "123456789012"
DB_ARN = f"arn:aws:rds:eu-north-1:{ACCOUNT}:db:orders"


def run_all(tmp_path: Path) -> Path:
    # give the db a real-looking arn so the account id is inside an id, like the live scanner does
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(FIXTURE.read_text().replace('"db-orders"', json.dumps(DB_ARN)))
    out = tmp_path / "out"
    result = CliRunner().invoke(app, ["all", "--from-snapshot", str(snapshot), "--out", str(out), "--no-ai"])
    assert result.exit_code == 0, result.output
    return out


def test_terraform_labels_come_from_names(tmp_path):
    main_tf = (run_all(tmp_path) / "terraform" / "main.tf").read_text()
    assert 'resource "leaseweb_public_cloud_instance" "web_1"' in main_tf
    assert ACCOUNT not in main_tf


def test_public_copies_never_hold_the_account(tmp_path):
    out = run_all(tmp_path)
    public = list((out / "public").rglob("*"))
    assert any(p.name == "report.md" for p in public)
    assert any(p.name == "main.tf" for p in public)
    assert not any(p.name == "inventory.json" for p in public)
    for path in public:
        if path.is_file():
            assert ACCOUNT not in path.read_text(), path


def test_mask_catches_other_arn_accounts():
    assert mask("arn:aws:iam::999988887777:role/x", "") == "arn:aws:iam::****7777:role/x"
    assert mask(f"id {ACCOUNT}", ACCOUNT) == "id ****9012"


def test_report_is_readable(tmp_path):
    report = (run_all(tmp_path) / "report.md").read_text()
    costs = report.split("## Monthly costs (EUR)")[1].split("## Migration work")[0]
    # only priced rows, by name, with the leaseweb type and the over-provisioning flag
    assert "| web-1 | t3.large |" in costs
    assert "| orders | db.t3.medium |" in costs and "over-provisioned" in costs
    assert "unknown" not in costs and "sg-web" not in costs
    runbook = report.split("## Migration runbook")[1]
    assert "### orders" in runbook and "### web-sg" not in runbook
    assert "No separate data move for:" in runbook
    assert "arn:aws" not in runbook.split("No separate data move")[0]
    # the lambda gets no runbook, and the db heading is its name, not the arn
    assert DB_ARN not in report
