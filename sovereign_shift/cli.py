"""CLI entry points for the migration pipeline."""

import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated

import boto3
import typer
from botocore.exceptions import BotoCoreError, ClientError

from sovereign_shift.graph import build_graph, render_html
from sovereign_shift.scanner.aws import scan

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
        graph = build_graph(json.loads(inventory.read_text()))
        html = render_html(graph)
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise typer.BadParameter(f"Invalid inventory: {error}") from error
    out.mkdir(parents=True, exist_ok=True)
    (out / "graph.json").write_text(json.dumps(graph, indent=2) + "\n")
    (out / "graph.html").write_text(html)
    typer.echo(f"Wrote {out / 'graph.json'} and {out / 'graph.html'}")


if __name__ == "__main__":
    app()
