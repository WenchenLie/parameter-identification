from __future__ import annotations

from importlib import metadata
from pathlib import Path
import tomllib


DIST_NAME = "parameter-identifier"
DEFAULT_VERSION = "0.0.0"


def get_version() -> str:
    pyproject_version = _read_pyproject_version()
    if pyproject_version != DEFAULT_VERSION:
        return pyproject_version
    try:
        return metadata.version(DIST_NAME)
    except metadata.PackageNotFoundError:
        return DEFAULT_VERSION


def _read_pyproject_version() -> str:
    for parent in Path(__file__).resolve().parents:
        pyproject = parent / "pyproject.toml"
        if pyproject.exists():
            with pyproject.open("rb") as file:
                data = tomllib.load(file)
            return str(data.get("project", {}).get("version", DEFAULT_VERSION))
    return DEFAULT_VERSION
