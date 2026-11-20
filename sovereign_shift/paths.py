"""Find reference data both in a git clone and in an installed wheel.

In a clone (or editable install) the files live at the repo root. A normal pip install bundles
the same folders under sovereign_shift/_data (see tool.hatch force-include in pyproject.toml).
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BUNDLED = Path(__file__).resolve().parent / "_data"


def data_path(relative: str) -> Path:
    repo = REPO / relative
    return repo if repo.exists() else BUNDLED / relative
