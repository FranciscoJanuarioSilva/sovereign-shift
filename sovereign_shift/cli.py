"""CLI entry points for the migration pipeline."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated

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


@app.command("scan")
def scan_command(
    profile: Annotated[str | None, typer.Option(help="AWS shared configuration profile.")] = None,
    region: Annotated[list[str] | None, typer.Option(help="AWS region to scan. Repeat for multiple regions.")] = None,
    out: Annotated[Path, typer.Option(help="Output directory.")] = Path("out"),
) -> None:
    """Write inventory.json using read-only AWS calls."""
    try:
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
) -> None:
    """Resolve deployed IDs and configure Leaseweb groups and targets."""
    token = None if dry_run else os.getenv("LEASEWEB_TOKEN")
    calls = finalize(
        read(out, "finalize"), json.loads(outputs.read_text()), admin_cidr, token
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
def report_command(out: Path = typer.Option(Path("out"), "--out")) -> None:
    """Write the Markdown and JSON migration assessment."""
    report(out, read(out, "inventory"), read(out, "mapping"))


@app.command("all")
def all_command(
    from_snapshot: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    mapping: Annotated[Path, typer.Option(exists=True, dir_okay=False, help="Prepared translator output.")],
    out: Annotated[Path, typer.Option()] = Path("out"),
    no_ai: Annotated[bool, typer.Option()] = False,
) -> None:
    """Run the assessment using a snapshot and a prepared mapping."""
    from sovereign_shift.artifacts import indexed
    from sovereign_shift.models import Mapping

    snapshot = json.loads(from_snapshot.read_text())
    prepared = json.loads(mapping.read_text())
    Inventory.model_validate(snapshot)
    Mapping.model_validate(prepared)
    indexed(snapshot, prepared)
    save(out, "inventory", snapshot)
    save(out, "mapping", prepared)
    graph_command(out / "inventory.json", out)
    generate_command(out)
    runbook_command(out, no_ai)
    report_command(out)
    typer.echo(f"Assessment ready at {out / 'report.md'}")


if __name__ == "__main__":
    app()
