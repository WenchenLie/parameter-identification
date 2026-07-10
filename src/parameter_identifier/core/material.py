from __future__ import annotations

from dataclasses import dataclass
from types import FunctionType
from typing import Any

import math

import numpy as np


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    lower: float
    upper: float

    @property
    def key(self) -> str:
        return self.name


@dataclass(frozen=True)
class MaterialModelSpec:
    name: str
    code: str
    parameters: tuple[ParameterSpec, ...]
    enabled: bool = True


DEFAULT_MATERIAL_BODY = """    mats = [
        ["Steel01", 1, fy, E0, b],
    ]
    ctrl_tag = 1
"""

DEFAULT_MATERIAL_CODE = DEFAULT_MATERIAL_BODY


def compose_material_code(parameters: tuple[ParameterSpec, ...] | list[ParameterSpec], body: str) -> str:
    lines = ["def build(params, context):"]
    for spec in parameters:
        validate_parameter_name(spec.name)
        lines.append(f'    {spec.name} = params["{spec.name}"]')
    validate_material_body(body)
    if body.strip():
        for line in body.splitlines():
            if not line.strip():
                lines.append("")
            elif line.startswith((" ", "\t")):
                lines.append(line)
            else:
                lines.append(f"    {line}")
    else:
        lines.append("    mats = []")
        lines.append("    ctrl_tag = None")
    lines.append("    return mats, ctrl_tag")
    return "\n".join(lines) + "\n"


def material_prefix_text(parameters: tuple[ParameterSpec, ...] | list[ParameterSpec]) -> str:
    lines = ["def build(params, context):"]
    for spec in parameters:
        validate_parameter_name(spec.name)
        lines.append(f'    {spec.name} = params["{spec.name}"]')
    return "\n".join(lines)


def material_suffix_text() -> str:
    return "    return mats, ctrl_tag"


def validate_parameter_name(name: str) -> None:
    if not name.isidentifier():
        raise ValueError(f"Invalid parameter name {name!r}; use a valid Python identifier.")


def validate_material_body(body: str) -> None:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("def build"):
            raise ValueError("Do not define build() in the editable material body.")
        if stripped.startswith("return "):
            raise ValueError("Do not use return in the editable material body; the return line is fixed.")


def legacy_default_full_code() -> str:
    return """def build(params, context):
    fy = params["fy"]
    E0 = params["E0"]
    b = params["b"]
    mats = [
        ["Steel01", 1, fy, E0, b],
    ]
    ctrl_tag = 1
    return mats, ctrl_tag
"""


def default_material() -> MaterialModelSpec:
    return MaterialModelSpec(
        name="Material",
        code=DEFAULT_MATERIAL_CODE,
        parameters=(
            ParameterSpec("fy", 100.0, 500.0),
            ParameterSpec("E0", 1000.0, 5000.0),
            ParameterSpec("b", 0.0, 0.1),
        ),
        enabled=True,
    )


def compile_material_builder(code: str) -> FunctionType:
    namespace: dict[str, Any] = {
        "__builtins__": {
            "abs": abs,
            "bool": bool,
            "dict": dict,
            "enumerate": enumerate,
            "float": float,
            "int": int,
            "len": len,
            "list": list,
            "max": max,
            "min": min,
            "pow": pow,
            "range": range,
            "round": round,
            "sum": sum,
            "tuple": tuple,
            "zip": zip,
        },
        "math": math,
        "np": np,
    }
    exec(compile(code, "<material-script>", "exec"), namespace)
    build = namespace.get("build")
    if not callable(build):
        raise ValueError("Material script must define callable build(params, context).")
    return build


def build_material_commands(
    material: MaterialModelSpec,
    params: dict[str, float],
    context: dict[str, Any] | None = None,
) -> tuple[list[list[Any]], int]:
    builder = compile_material_builder(compose_material_code(material.parameters, material.code))
    result = builder(params, context or {})
    return validate_material_build_result(material.name, result)


def validate_material_build_result(material_name: str, result: Any) -> tuple[list[list[Any]], int]:
    if not isinstance(result, tuple) or len(result) != 2:
        raise ValueError(f"{material_name}: build must return (mats, ctrl_tag).")
    mats, ctrl_tag = result
    if not isinstance(mats, list) or not mats:
        raise ValueError(f"{material_name}: mats must be a non-empty list.")
    for command in mats:
        if not isinstance(command, list) or len(command) < 2:
            raise ValueError(f"{material_name}: every material command must be a list with at least two items.")
        tag = command[1]
        if isinstance(tag, bool) or not isinstance(tag, int) or tag < 1:
            raise ValueError(f"{material_name}: every material tag must be a positive integer starting from 1.")
    if isinstance(ctrl_tag, bool) or not isinstance(ctrl_tag, int) or ctrl_tag < 1:
        raise ValueError(f"{material_name}: ctrl_tag must be a positive integer starting from 1.")
    material_tags = {command[1] for command in mats}
    if ctrl_tag not in material_tags:
        raise ValueError(f"{material_name}: ctrl_tag must refer to a tag defined in mats.")
    return mats, ctrl_tag


def flatten_parameters(materials: list[MaterialModelSpec]) -> list[ParameterSpec]:
    specs: list[ParameterSpec] = []
    seen: set[str] = set()
    for material in materials:
        if not material.enabled:
            continue
        for spec in material.parameters:
            validate_parameter_name(spec.name)
            if spec.upper <= spec.lower:
                raise ValueError(f"{spec.key}: upper bound must be greater than lower bound.")
            if spec.key in seen:
                raise ValueError(f"Duplicate parameter key: {spec.key}.")
            seen.add(spec.key)
            specs.append(spec)
    if not specs:
        raise ValueError("At least one enabled material parameter is required.")
    return specs


def vector_to_material_params(
    vector: np.ndarray,
    parameter_specs: list[ParameterSpec],
) -> dict[str, float]:
    values: dict[str, float] = {}
    for value, spec in zip(vector, parameter_specs):
        values[spec.name] = float(value)
    return values


def bounds_arrays(parameter_specs: list[ParameterSpec]) -> tuple[np.ndarray, np.ndarray]:
    lower = np.asarray([spec.lower for spec in parameter_specs], dtype=float)
    upper = np.asarray([spec.upper for spec in parameter_specs], dtype=float)
    return lower, upper
