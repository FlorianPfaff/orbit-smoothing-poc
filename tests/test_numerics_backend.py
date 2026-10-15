"""Check native coordinate metadata used to freeze observation support."""
import pytest

from orbit_poc.numerics.backend import native_failure_reason, nuisance_profile_resolution, parameter_support
from orbit_poc.numerics.optimizer import NumericalFailure


def test_parameter_support_excludes_only_named_scale(tmp_path):
    path = tmp_path / "parameters.tsv"
    header = "index\tname\tdynamic\tunit\tscale\tcoordinate_convention\n"
    path.write_text(header + "0\tpulse.x\t1\tum/s\t0.25\tinertial_cartesian\n")
    original = parameter_support(path)
    path.write_text(header + "0\tpulse.x\t1\tum/s\t8\tinertial_cartesian\n")
    assert parameter_support(path) == original
    path.write_text(header + "0\tpulse.x\t1\tum/s\t8\tother_basis\n")
    assert parameter_support(path) != original
    path.write_text("scale\tunit\tdynamic\tname\tindex\tcoordinate_convention\n"
                    "0.125\tum/s\t1\tpulse.x\t0\tinertial_cartesian\n")
    assert parameter_support(path) == original


@pytest.mark.parametrize("text", [
    "index\tname\tdynamic\tunit\n0\tpulse\t1\tum/s\n",
    "index\tname\tdynamic\tunit\tscale\n0\tpulse\t1\tum/s\n",
    "index\tname\tdynamic\tunit\tscale\n0\tpulse\t1\tum/s\t1\textra\n",
])
def test_malformed_parameter_metadata_fails_closed(tmp_path, text):
    path = tmp_path / "parameters.tsv"
    path.write_text(text)
    with pytest.raises(ValueError):
        parameter_support(path)


def test_nuisance_line_search_failure_is_a_rejectable_proposal():
    message = "Nuisance line search rejected every trial without undamped stationarity"
    assert native_failure_reason(message) == "nuisance_failure"
    assert native_failure_reason(message, {"timed_out": True}) == "timeout"
    assert native_failure_reason("Fresh nuisance factor did not confirm empirical resolution status") == "nuisance_failure"
    assert native_failure_reason("Cannot fork nuisance trial") == "native_failure"
    assert native_failure_reason("Unsupported constraint bypassed v3.1 original weighted rows") == "native_failure"


def test_inexact_profile_is_explicit_and_cannot_supply_covariance():
    receipt = {"nuisance_converged": False, "nuisance_floor_limited": True,
               "nuisance_objective_resolution": 2e-7, "nuisance_predicted_reduction": 1e-8,
               "nuisance_floor_policy": "empirical_equivalent_arithmetic_and_symmetric_probes_v1",
               "nuisance_floor_audit": [
                   *[{"kind": "equivalent_arithmetic", "mode": mode,
                      "success": True, "support_unchanged": True} for mode in (1, 2, 3)],
                   {"kind": "two_amplitude_symmetric_nuisance_probe", "probes": [{}, {}, {}, {}],
                    "empirical_quadratic_potential": 1e-8, "half_empirical_quadratic_potential": 1e-8,
                    "empirical_quadratic_potential_with_allowance": 2e-8,
                    "half_empirical_quadratic_potential_with_allowance": 3e-8,
                    "success": True, "support_unchanged": True}]}
    assert nuisance_profile_resolution(receipt) == (2e-7, True)
    with pytest.raises(NumericalFailure):
        nuisance_profile_resolution(receipt, covariance=True)
    assert nuisance_profile_resolution({"nuisance_converged": True}, covariance=True) == (0., False)
    for value in (None, float("nan"), float("inf"), -1., 0., 1e-6):
        invalid_probe = {**receipt["nuisance_floor_audit"][-1], "half_empirical_quadratic_potential_with_allowance": value}
        with pytest.raises(NumericalFailure):
            nuisance_profile_resolution({**receipt, "nuisance_floor_audit": receipt["nuisance_floor_audit"][:3]+[invalid_probe]})
    for update in ({"nuisance_converged": True}, {"nuisance_objective_resolution": 0.},
                   {"nuisance_predicted_reduction": 3e-7}, {"nuisance_predicted_reduction": 0.},
                   {"nuisance_floor_policy": "unspecified"},
                   {"nuisance_floor_audit": receipt["nuisance_floor_audit"][:3]},
                   {"nuisance_floor_audit": [receipt["nuisance_floor_audit"][0]]*3 + receipt["nuisance_floor_audit"][3:]},
                   {"nuisance_floor_audit": []}, {"nuisance_floor_audit": [{"success": False, "support_unchanged": True}]},
                   {"nuisance_floor_audit": [{"success": True, "support_unchanged": False}]}):
        with pytest.raises(NumericalFailure):
            nuisance_profile_resolution({**receipt, **update})


@pytest.mark.parametrize("message", [
    "nonfinite tangent right-hand side, solve_role=physical_correction, column=0",
    "six-state tangent did not meet its true residual tolerance: relative_residual=0.01",
    "nonfinite position force Jacobian",
    "singular local six-state tangent preconditioner",
])
def test_invalid_physical_trial_is_rejected_without_masking_configuration_errors(message):
    assert native_failure_reason(message) == "closure_failed"
    assert native_failure_reason(message, {"timed_out": True}) == "timeout"
    assert native_failure_reason("staged Jacobians do not support fitted force parametrizations") == "native_failure"
    assert native_failure_reason("invalid tangent solver input") == "native_failure"
