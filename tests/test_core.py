from __future__ import annotations

import numpy as np

from parameter_identifier.core.fitness import rmse, weighted_rmse
from parameter_identifier.core.material import (
    ParameterSpec,
    compose_material_code,
    compile_material_builder,
    default_material,
    flatten_parameters,
    validate_material_build_result,
    vector_to_material_params,
)
from parameter_identifier.core.preprocessing import PreprocessSettings, preprocess_curve
from parameter_identifier.optimizers.ga import GAOptimizer, GASettings
from parameter_identifier.optimizers.pso import PSOOptimizer, PSOSettings


def test_rmse() -> None:
    assert rmse(np.array([1.0, 2.0]), np.array([1.0, 4.0])) == np.sqrt(2.0)


def test_weighted_rmse_uses_skeleton_indices() -> None:
    expected = np.array([0.0, 1.0, 2.0])
    predicted = np.array([0.0, 2.0, 4.0])
    value = weighted_rmse(expected, predicted, np.array([2]), skeleton_weight=1.0)
    assert value == 2.0


def test_compile_default_material_script() -> None:
    material = default_material()
    build = compile_material_builder(compose_material_code(material.parameters, material.code))
    mats, ctrl_tag = build({"fy": 200.0, "E0": 3000.0, "b": 0.02}, {})
    assert mats[0][0] == "Steel01"
    assert mats[0][1] == 1
    assert ctrl_tag == 1


def test_material_tags_must_be_positive_integers() -> None:
    with np.testing.assert_raises_regex(ValueError, "positive integer"):
        validate_material_build_result("Material", ([["Steel01", "tag1", 200.0, 3000.0, 0.02]], "tag1"))


def test_control_tag_must_refer_to_defined_material() -> None:
    with np.testing.assert_raises_regex(ValueError, "defined in mats"):
        validate_material_build_result("Material", ([["Steel01", 1, 200.0, 3000.0, 0.02]], 2))


def test_parameter_vector_mapping() -> None:
    specs = [
        ParameterSpec("a", 0.0, 1.0),
        ParameterSpec("b", 2.0, 3.0),
    ]
    values = vector_to_material_params(np.array([0.4, 2.5]), specs)
    assert values == {"a": 0.4, "b": 2.5}


def test_flatten_rejects_invalid_bounds() -> None:
    material = default_material()
    bad = ParameterSpec("bad", 1.0, 1.0)
    material = type(material)(material.name, material.code, (bad,), True)
    try:
        flatten_parameters([material])
    except ValueError as exc:
        assert "upper bound" in str(exc)
    else:
        raise AssertionError("invalid bounds were accepted")


def test_preprocess_small_curve() -> None:
    u = np.array([0.0, 1.0, 0.0, -1.0, 0.0])
    f = np.array([0.0, 2.0, 0.0, -2.0, 0.0])
    result = preprocess_curve(u, f, PreprocessSettings())
    assert len(result.displacement) == len(result.force)
    assert len(result.displacement) == len(u)


def test_pso_history_shape() -> None:
    def objective(x):
        force = np.array([x[0]])
        return float((x[0] - 0.25) ** 2), force

    history = PSOOptimizer(PSOSettings(population_size=5, generations=3, seed=1)).run(
        objective,
        np.array([0.0]),
        np.array([1.0]),
        ["x"],
    )
    assert len(history.entries) == 4
    assert history.entries[-1].global_best_fitness <= history.entries[0].global_best_fitness


def test_ga_history_shape() -> None:
    def objective(x):
        force = np.array([x[0]])
        return float((x[0] - 0.25) ** 2), force

    history = GAOptimizer(GASettings(population_size=6, generations=3, seed=1)).run(
        objective,
        np.array([0.0]),
        np.array([1.0]),
        ["x"],
    )
    assert len(history.entries) == 4
    assert history.entries[-1].global_best_fitness <= history.entries[0].global_best_fitness
