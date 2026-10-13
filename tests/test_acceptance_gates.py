"""Scientific acceptance regressions, independent of numerical solver execution."""
from copy import deepcopy
import json

import numpy as np
import pytest

from orbit_poc import benchmark as orchestration
from orbit_poc.data import Dataset, save_dataset
from orbit_poc.solvers import FitResult


def calibration_and_config():
    config = {"orbits": ["leo500"], "models": ["white", "colored", "density"],
              "substep": 2.5, "evaluation_seeds": [42, 43, 44, 45, 46]}
    calibration = {
        "complete": True, "truth_backend": "tudat", "integration_substep_seconds": 2.5,
        "calibration_seeds": [10000, 10001, 10002, 10003, 10004],
        "provenance": {"source_sha256": "verified-source"},
        "selections": {"leo500": {model: {"parameters": {"model": model},
                                          "full_grid_complete": True, "calibration_seeds": 5}
                                     for model in config["models"]}},
    }
    return calibration, config


def test_matching_calibration_contract_is_accepted():
    calibration, config = calibration_and_config()
    orchestration.validate_calibration(calibration, config, "tudat", source_sha256="verified-source")


@pytest.mark.parametrize("changed_key,changed_value", [
    ("complete", False),
    ("truth_backend", "scipy"),
    ("integration_substep_seconds", 5.0),
    ("calibration_seeds", [42, 10001, 10002, 10003, 10004]),
    ("provenance", {"source_sha256": "old-source-before-numerical-fix"}),
    ("selections", {"leo500": {"white": {"parameters": {"model": "white"}}}}),
])
def test_incompatible_calibration_cannot_certify_test_benchmark(changed_key, changed_value):
    calibration, config = calibration_and_config()
    calibration[changed_key] = deepcopy(changed_value)
    with pytest.raises(ValueError):
        orchestration.validate_calibration(calibration, config, "tudat", source_sha256="verified-source")


def test_benchmark_rejects_changed_source_before_generating_any_test_data(tmp_path, monkeypatch):
    calibration, config = calibration_and_config()
    calibration["provenance"]["source_sha256"] = "old-source-before-numerical-fix"
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(calibration))
    monkeypatch.setattr(orchestration, "provenance", lambda: {"source_sha256": "verified-source"})
    calls = []

    def forbidden_generation(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("An incompatible calibration reached test-data generation")

    monkeypatch.setattr(orchestration, "generate_one", forbidden_generation)
    with pytest.raises(ValueError):
        orchestration.benchmark(config, tmp_path / "benchmark", calibration_path=path,
                                truth_backend="tudat", seeds=5, workers=1)
    assert not calls


@pytest.mark.parametrize("diagnostic_status,converged,expected", [
    ("passed", True, True),
    ("inconclusive", True, False),
    ("passed", False, False),
    (None, True, False),
])
def test_numpyro_acceptance_uses_actual_backend_diagnostic_contract(
        tmp_path, monkeypatch, diagnostic_status, converged, expected):
    """A passed backend result used to be rejected because the key differed.

    A convergence flag alone must also not bypass the explicit posterior
    diagnostics. Mock only numerical fitting, leaving orchestration unchanged.
    """
    from orbit_poc import solvers

    times = np.array([0., 60., 120.])
    states = np.tile([7e6, 0., 0., 0., 7500., 0.], (3, 1))
    dataset = Dataset(times=times,
                      observations={"node": np.array([0, 2]),
                                    "station_pos": np.zeros((2, 3)),
                                    "station_vel": np.zeros((2, 3)),
                                    "y": np.array([[7e6, 0.], [7e6, 0.]]),
                                    "sigma": np.array([10., .01])},
                      prior_mean=states[0], prior_sigma=np.ones(6))
    dataset_path = save_dataset(dataset, tmp_path / "observations.npz")
    metadata = {} if diagnostic_status is None else {"diagnostic_status": diagnostic_status}
    fitted = FitResult(states=states, covariance=np.tile(np.eye(6), (3, 1, 1)),
                       objective=1., converged=converged, iterations=1000,
                       elapsed_seconds=.1, metadata=metadata)
    monkeypatch.setattr(solvers, "initialize", lambda *args, **kwargs: np.zeros((3, 6)))
    monkeypatch.setattr(solvers, "fit", lambda *args, **kwargs: fitted)
    result = orchestration.fit_one(dataset_path, {"model": "white"}, tmp_path / "fit",
                                   solver="numpyro", resume=False)
    assert result["status"] == "complete"
    assert result["valid_for_comparison"] is expected
