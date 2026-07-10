from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from parameter_identifier.core.opensees_backend import DEFAULT_OPENSEES_PATH, OpenSeesPythonBackend


@pytest.mark.skipif(not Path(DEFAULT_OPENSEES_PATH).exists(), reason="default opensees.pyd is not available")
def test_default_opensees_backend_steel01_response() -> None:
    backend = OpenSeesPythonBackend(DEFAULT_OPENSEES_PATH)
    force = backend.calculate_uniaxial_response(
        [["Steel01", 1, 200.0, 3000.0, 0.02]],
        1,
        np.array([0.0, 0.01, -0.01]),
    )
    assert force.shape == (3,)
    assert np.all(np.isfinite(force))
    assert force[1] > force[0]
