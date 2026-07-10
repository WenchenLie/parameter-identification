from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


def _find_builtin_opensees() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "resources" / "opensees" / "opensees.pyd"
        if candidate.exists():
            return candidate
    return current.parents[3] / "resources" / "opensees" / "opensees.pyd"


BUILTIN_OPENSEES_PATH = _find_builtin_opensees()
DEFAULT_OPENSEES_PATH = str(BUILTIN_OPENSEES_PATH)


@dataclass
class OpenSeesPythonBackend:
    module_path: str = DEFAULT_OPENSEES_PATH

    def __post_init__(self) -> None:
        self.ops = self._load_module(self.module_path)

    @staticmethod
    def _load_module(module_path: str):
        path = Path(module_path)
        if not path.exists():
            raise FileNotFoundError(f"OpenSees module not found: {module_path}")
        if path.suffix.lower() not in {".pyd", ".py"}:
            raise ValueError("Only opensees.pyd or opensees.py are supported.")

        parent = str(path.parent)
        old_module = sys.modules.pop("opensees", None)
        sys.path.insert(0, parent)
        dll_handle = None
        if hasattr(os, "add_dll_directory"):
            dll_handle = os.add_dll_directory(parent)
        try:
            return importlib.import_module("opensees")
        finally:
            if dll_handle is not None:
                dll_handle.close()
            try:
                sys.path.remove(parent)
            except ValueError:
                pass
            if old_module is not None and "opensees" not in sys.modules:
                sys.modules["opensees"] = old_module

    def calculate_uniaxial_response(
        self,
        mats: list[list[Any]],
        ctrl_tag: int,
        displacement: np.ndarray,
    ) -> np.ndarray:
        ops = self.ops
        ops.wipe()
        for command in mats:
            ops.uniaxialMaterial(*command)
        ops.testUniaxialMaterial(ctrl_tag)
        force = np.zeros(len(displacement), dtype=float)
        for i, ui in enumerate(displacement):
            ops.setStrain(float(ui))
            force[i] = float(ops.getStress())
        return force
