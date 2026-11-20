"""Load SKILL.md files (the skill tree in skills/) for our own AI agents."""

import re
from functools import cache
from pathlib import Path

from sovereign_shift.paths import data_path

# repo skills/ in a clone, bundled copy in a wheel
SKILLS = data_path("skills")
FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.S)


def path(name: str) -> Path:
    return SKILLS / name / "SKILL.md"


def meta(name: str) -> dict[str, str]:
    match = FRONTMATTER.match(path(name).read_text())
    if not match:
        raise ValueError(f"{name}: SKILL.md has no frontmatter")
    return dict(line.split(": ", 1) for line in match.group(1).splitlines() if ": " in line)


@cache
def load(name: str) -> str:
    """The skill's instructions without the frontmatter, ready to use as a system prompt."""
    return FRONTMATTER.sub("", path(name).read_text(), count=1).strip()


def names() -> list[str]:
    return sorted(p.parent.name for p in SKILLS.glob("*/SKILL.md"))
