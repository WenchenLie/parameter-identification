from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from parameter_identifier.core.fitness import weighted_rmse
from parameter_identifier.core.material import (
    MaterialModelSpec,
    ParameterSpec,
    bounds_arrays,
    compile_material_builder,
    compose_material_code,
    flatten_parameters,
    validate_material_build_result,
    vector_to_material_params,
)
from parameter_identifier.core.opensees_backend import OpenSeesPythonBackend
from parameter_identifier.optimizers.base import OptimizationHistory
from parameter_identifier.optimizers.ga import GAOptimizer, GASettings
from parameter_identifier.optimizers.pso import PSOOptimizer, PSOSettings


@dataclass(frozen=True)
class IdentificationData:
    displacement: np.ndarray
    force: np.ndarray
    skeleton_indices: np.ndarray


@dataclass(frozen=True)
class IdentificationSettings:
    algorithm: str = "PSO"
    population_size: int = 30
    generations: int = 50
    skeleton_weight: float = 0.0
    random_seed: int | None = 42
    algorithm_parameters: dict[str, float | int] | None = None


class IdentificationProblem:
    def __init__(
        self,
        data: IdentificationData,
        materials: list[MaterialModelSpec],
        opensees_path: str,
        skeleton_weight: float = 0.0,
    ) -> None:
        self.data = data
        self.materials = [material for material in materials if material.enabled]
        if len(self.materials) != 1:
            raise ValueError("Exactly one material script must be enabled.")
        self.parameter_specs = flatten_parameters(self.materials)
        self.lower_bounds, self.upper_bounds = bounds_arrays(self.parameter_specs)
        self.backend = OpenSeesPythonBackend(opensees_path)
        self.skeleton_weight = skeleton_weight
        self.material = self.materials[0]
        self.builder = compile_material_builder(compose_material_code(self.material.parameters, self.material.code))
        self.context: dict[str, Any] = {
            "u": self.data.displacement,
            "F_exp": self.data.force,
            "skeleton_indices": self.data.skeleton_indices,
        }

    @property
    def parameter_names(self) -> list[str]:
        return [spec.key for spec in self.parameter_specs]

    def simulate(self, vector: np.ndarray) -> np.ndarray:
        params = vector_to_material_params(vector, self.parameter_specs)
        result = self.builder(params, self.context)
        mats, ctrl_tag = validate_material_build_result(self.material.name, result)
        return self.backend.calculate_uniaxial_response(
            mats,
            ctrl_tag,
            self.data.displacement,
        )

    def objective(self, vector: np.ndarray) -> tuple[float, np.ndarray]:
        force = self.simulate(vector)
        fitness = weighted_rmse(
            self.data.force,
            force,
            self.data.skeleton_indices,
            self.skeleton_weight,
        )
        return fitness, force


def run_identification(
    data: IdentificationData,
    materials: list[MaterialModelSpec],
    settings: IdentificationSettings,
    opensees_path: str,
    progress=None,
    should_stop=None,
) -> tuple[OptimizationHistory, list[ParameterSpec]]:
    problem = IdentificationProblem(
        data=data,
        materials=materials,
        opensees_path=opensees_path,
        skeleton_weight=settings.skeleton_weight,
    )
    algorithm = settings.algorithm.strip().upper()
    algorithm_parameters = settings.algorithm_parameters or {}
    population_size = int(algorithm_parameters.get("population_size", settings.population_size))
    generations = int(algorithm_parameters.get("generations", settings.generations))
    if algorithm == "PSO":
        optimizer = PSOOptimizer(
            PSOSettings(
                population_size=population_size,
                generations=generations,
                inertia_start=float(algorithm_parameters.get("inertia_start", 0.9)),
                inertia_end=float(algorithm_parameters.get("inertia_end", 0.4)),
                cognitive=float(algorithm_parameters.get("cognitive", 2.0)),
                social=float(algorithm_parameters.get("social", 2.0)),
                velocity_ratio=float(algorithm_parameters.get("velocity_ratio", 0.1)),
                seed=settings.random_seed,
            )
        )
    elif algorithm == "GA":
        optimizer = GAOptimizer(
            GASettings(
                population_size=population_size,
                generations=generations,
                crossover_rate=float(algorithm_parameters.get("crossover_rate", 0.85)),
                mutation_rate=float(algorithm_parameters.get("mutation_rate", 0.12)),
                mutation_scale=float(algorithm_parameters.get("mutation_scale", 0.08)),
                tournament_size=int(algorithm_parameters.get("tournament_size", 3)),
                elite_count=int(algorithm_parameters.get("elite_count", 1)),
                seed=settings.random_seed,
            )
        )
    else:
        raise ValueError("algorithm must be PSO or GA.")
    history = optimizer.run(
        problem.objective,
        problem.lower_bounds,
        problem.upper_bounds,
        problem.parameter_names,
        progress=progress,
        should_stop=should_stop,
    )
    return history, problem.parameter_specs
