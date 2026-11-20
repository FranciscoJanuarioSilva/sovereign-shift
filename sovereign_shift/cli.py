"""CLI entry points for the migration pipeline."""

import json
from pathlib import Path

import typer

from sovereign_shift.graph import build_graph, render_html

app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """Assess cloud infrastructure migrations."""


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
