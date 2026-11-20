import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from sovereign_shift.models import CONTRACTS


def read(folder: Path, name: str) -> dict:
    data = json.loads((folder / f"{name}.json").read_text())
    CONTRACTS[name].model_validate(data)
    return data


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        stream.write(content)
    Path(stream.name).replace(path)


def save(folder: Path, name: str, data: dict) -> None:
    CONTRACTS[name].model_validate(data)
    write(folder / f"{name}.json", json.dumps(data, indent=2) + "\n")


def indexed(inventory: dict, mapping: dict) -> tuple[dict, dict]:
    resources = {r["id"]: r for r in inventory["resources"]}
    entries = {e["source_id"]: e for e in mapping["entries"]}
    if (
        len(entries) != len(mapping["entries"])
        or len(resources) != len(inventory["resources"])
        or resources.keys() != entries.keys()
    ):
        raise ValueError(
            "Inventory and mapping require one entry per unique resource ID"
        )
    return resources, entries
