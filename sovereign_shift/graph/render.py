"""Render a dependency graph as self-contained HTML with inline SVG."""

from html import escape
from math import cos, sin, tau
from typing import Any

import networkx as nx


def render_html(graph: dict[str, Any]) -> str:
    """Escape inventory text and use a deterministic layout, including cycles."""
    network = nx.MultiDiGraph()
    network.add_nodes_from(node["id"] for node in graph["nodes"])
    network.add_edges_from((edge["from"], edge["to"]) for edge in graph["edges"])
    positions = {
        node: (cos(tau * index / len(network)), sin(tau * index / len(network)))
        for index, node in enumerate(sorted(network))
    }
    width = max(960, len(network) * 65)
    height = max(600, len(network) * 40)
    points = {
        node: (float(position[0]) * (width / 2 - 170) + width / 2,
               float(position[1]) * (height / 2 - 75) + height / 2)
        for node, position in positions.items()
    }
    shapes = []
    for edge in graph["edges"]:
        x1, y1 = points[edge["from"]]
        x2, y2 = points[edge["to"]]
        title = escape(f'{edge["from"]} → {edge["to"]} ({edge["type"]})')
        dash = ' stroke-dasharray="6 4"' if edge.get("inferred") else ""
        # curves also make self references visible
        curve = f"M {x1} {y1} Q {(x1+x2)/2+45} {(y1+y2)/2-65} {x2} {y2}"
        shapes.append(
            f'<path d="{curve}" fill="none" stroke="#64748b"{dash} '
            f'marker-end="url(#arrow)"><title>{title}</title></path>'
        )
    for node in graph["nodes"]:
        x, y = points[node["id"]]
        name = escape(str(node["name"])[:70])
        kind = escape(str(node["type"]))
        identifier = escape(str(node["id"]))
        shapes.append(
            f'<g transform="translate({x},{y})"><title>{identifier}</title>'
            '<rect x="-120" y="-29" width="240" height="58" rx="8" '
            'fill="#e0f2fe" stroke="#0369a1"/>'
            f'<text text-anchor="middle" y="-4">{name}</text>'
            f'<text text-anchor="middle" y="17" font-size="12">{kind}</text></g>'
        )
    rows = "".join(
        "<tr>" + "".join(f"<td>{escape(str(value))}</td>" for value in (
            edge["from"], edge["to"], edge["type"],
            "inferred" if edge.get("inferred") else "explicit",
        )) + "</tr>"
        for edge in graph["edges"]
    )
    findings = "".join(
        f'<li>{escape(item["resource"])} — {escape(item["message"])}</li>'
        for item in graph["findings"]
    )
    return f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Infrastructure dependencies</title>
<style>body{{font:15px system-ui;margin:2rem;color:#0f172a}}
.diagram{{overflow:auto}}svg{{font-family:system-ui}}table{{border-collapse:collapse}}
td,th{{padding:.6rem;text-align:left;border-bottom:1px solid #cbd5e1}}</style>
<h1>Infrastructure dependencies</h1>
<p>{len(graph["nodes"])} resources · {len(graph["edges"])} relationships.
Arrows follow source to dependency. Dashed lines indicate inferred database access.</p>
<div class="diagram"><svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"
role="img" aria-label="Infrastructure dependency graph">
<defs><marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5"
markerWidth="7" markerHeight="7" orient="auto-start-reverse">
<path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b"/></marker></defs>
{"".join(shapes)}</svg></div>
<table><caption>Relationships</caption><thead><tr><th>Source</th><th>Dependency</th>
<th>Relationship</th><th>Evidence</th></tr></thead><tbody>{rows}</tbody></table>
<ul>{findings}</ul></html>
"""
