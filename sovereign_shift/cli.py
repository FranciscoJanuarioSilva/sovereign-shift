"""CLI entry points for the migration pipeline."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated

from dotenv import load_dotenv

import boto3
import typer
from botocore.exceptions import BotoCoreError, ClientError

from sovereign_shift.artifacts import read, save
from sovereign_shift.finalize.apply import finalize
from sovereign_shift.generator.build import generate
from sovereign_shift.graph import build_graph, render_html
from sovereign_shift.scanner.aws import scan
from sovereign_shift.graph.security import findings
from sovereign_shift.models import Inventory
from sovereign_shift.report.build import report
from sovereign_shift.runbook.build import runbook

app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """Assess cloud infrastructure migrations."""
    load_dotenv(Path.cwd() / ".env", override=False)


@app.command("scan")
def scan_command(
    profile: Annotated[str | None, typer.Option(help="AWS shared configuration profile.")] = None,
    region: Annotated[list[str] | None, typer.Option(help="AWS region to scan. Repeat for multiple regions.")] = None,
    out: Annotated[Path, typer.Option(help="Output directory.")] = Path("out"),
) -> None:
    """Write inventory.json using read-only AWS calls."""
    try:
        if not region and os.getenv("AWS_REGION"):
            region = [os.environ["AWS_REGION"]]
        inventory = scan(boto3.Session(profile_name=profile), region)
    except ClientError as exc:
        typer.echo(f"AWS scan failed in {exc.operation_name}: {exc.response['Error']['Code']}", err=True)
        raise typer.Exit(1) from None
    except BotoCoreError as exc:
        typer.echo(f"AWS scan failed: {type(exc).__name__}", err=True)
        raise typer.Exit(1) from None

    destination = out / "inventory.json"
    temporary = None
    try:
        out.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=out, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(inventory, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        temporary.replace(destination)
    except OSError as exc:
        typer.echo(f"Failed to write inventory: {exc}", err=True)
        raise typer.Exit(1) from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    typer.echo(f"Wrote {len(inventory['resources'])} resources to {destination}")
    for entry in inventory.get("denied", []):
        typer.echo(f"Skipped {entry['service']} in {entry['region']}: {entry['error']} ({entry['operation']})", err=True)



@app.command("graph")
def graph_command(
    inventory: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    out: Path = typer.Option(Path("out"), "--out", help="Output directory."),
) -> None:
    """Build graph.json and graph.html from an inventory snapshot."""
    try:
        snapshot = json.loads(inventory.read_text())
        Inventory.model_validate(snapshot)
        graph = build_graph(snapshot)
        security = findings(snapshot, graph)
        html = render_html(graph)
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise typer.BadParameter(f"Invalid inventory: {error}") from error
    out.mkdir(parents=True, exist_ok=True)
    save(out, "findings", {"findings": security})
    (out / "graph.json").write_text(json.dumps(graph, indent=2) + "\n")
    (out / "graph.html").write_text(html)
    typer.echo(
        f"Wrote {out / 'graph.json'} and {out / 'graph.html'} and {out / 'findings.json'}"
    )


@app.command("generate")
def generate_command(out: Path = typer.Option(Path("out"), "--out")) -> None:
    """Render Terraform and the post-apply plan from the pipeline artifacts."""
    generate(out, read(out, "inventory"), read(out, "graph"), read(out, "mapping"))


@app.command("finalize")
def finalize_command(
    outputs: Path = typer.Option(
        ..., "--outputs", help="File from terraform output -json"
    ),
    out: Path = typer.Option(Path("out"), "--out"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    admin_cidr: str | None = typer.Option(None, "--admin-cidr"),
    private_network_cidr: str | None = typer.Option(None, "--private-network-cidr"),
) -> None:
    """Resolve deployed IDs and configure Leaseweb groups and targets."""
    token = None if dry_run else os.getenv("LEASEWEB_TOKEN")
    calls = finalize(
        read(out, "finalize"), json.loads(outputs.read_text()), admin_cidr, token, private_network_cidr=private_network_cidr
    )
    typer.echo(json.dumps(calls, indent=2))


@app.command("runbook")
def runbook_command(
    out: Path = typer.Option(Path("out"), "--out"),
    no_ai: bool = typer.Option(False, "--no-ai"),
) -> None:
    """Render migration steps from the validated template library."""
    save(
        out,
        "runbook",
        runbook(out, read(out, "inventory"), read(out, "mapping"), no_ai),
    )


@app.command("report")
def report_command(out: Path = typer.Option(Path("out"), "--out"), no_ai: bool = typer.Option(False, "--no-ai")) -> None:
    """Write the Markdown and JSON migration assessment."""
    report(out, read(out, "inventory"), read(out, "mapping"), no_ai)


@app.command("all")
def all_command(
    from_snapshot: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
    mapping: Annotated[Path | None, typer.Option(exists=True, dir_okay=False, help="Reuse a prepared mapping.")] = None,
    profile: Annotated[str | None, typer.Option()] = None,
    region: Annotated[list[str] | None, typer.Option()] = None,
    target_region: Annotated[str | None, typer.Option()] = None,
    out: Annotated[Path, typer.Option()] = Path("out"),
    no_ai: Annotated[bool, typer.Option()] = False,
) -> None:
    """Scan or load a snapshot, translate it and generate the assessment."""
    if from_snapshot is None:
        scan_command(profile, region, out)
    else:
        if profile or region:
            raise typer.BadParameter("--profile and --region apply only to live scans")
        snapshot = json.loads(from_snapshot.read_text())
        Inventory.model_validate(snapshot)
        save(out, "inventory", snapshot)
    inventory = out / "inventory.json"
    graph_command(inventory, out)
    if mapping is None:
        translate_command(inventory, out / "graph.json", out, target_region, no_ai)
    else:
        if target_region:
            raise typer.BadParameter("--target-region requires translation")
        save(out, "mapping", json.loads(mapping.read_text()))
    generate_command(out)
    runbook_command(out, no_ai)
    report_command(out, no_ai)
    publish_command(out)
    typer.echo(f"Assessment ready at {out / 'report.md'}")


@app.command("publish")
def publish_command(out: Path = typer.Option(Path("out"), "--out")) -> None:
    """Write shareable copies to out/public with the AWS account id masked."""
    from sovereign_shift.publish import publish

    account = json.loads((out / "inventory.json").read_text()).get("account_id", "")
    written = publish(out, account)
    typer.echo(f"Wrote {len(written)} shareable files to {out / 'public'} (account id masked)")


@app.command("translate")
def translate_command(
    inventory: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    graph: Path | None = typer.Option(None, "--graph", help="graph.json, rebuilt from the inventory if missing."),
    out: Path = typer.Option(Path("out"), "--out", help="Output directory."),
    target_region: str | None = typer.Option(None, "--target-region", help="Force one Leaseweb region, e.g. eu-west-3."),
    no_ai: bool = typer.Option(False, "--no-ai", help="Rules only, no LLM calls."),
) -> None:
    """Map every inventory resource to a Leaseweb target and write mapping.json."""
    from sovereign_shift.translator import main_files, summary

    if graph is None and (out / "graph.json").exists():
        graph = out / "graph.json"
    try:
        mapping = main_files(inventory, graph, out, target_region, use_ai=not no_ai)
    except (ValueError, KeyError, TypeError) as error:
        raise typer.BadParameter(f"Invalid input: {error}") from error
    typer.echo(summary(mapping))
    typer.echo(f"Wrote {out / 'mapping.json'}")


if __name__ == "__main__":
    app()
