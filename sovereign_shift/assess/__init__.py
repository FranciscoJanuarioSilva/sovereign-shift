"""Step after translate: security posture, risk, performance and scaling, all from rules (no AI)."""

from datetime import datetime, timezone

from .performance import performance
from .posture import posture
from .risk import risk
from .scaling import scaling


def assess(inventory: dict, graph: dict, findings: list[dict], mapping: dict) -> dict:
    sec = posture(inventory, graph, findings, mapping)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "posture": sec,
        "risk": risk(inventory, graph, sec, mapping),
        "performance": performance(inventory, mapping),
        "scaling": scaling(inventory, graph, mapping),
    }


__all__ = ["assess"]
