"""The opt-in solver interface must not change the compatibility optimizer."""
from dataclasses import replace

import numpy as np
import pytest

from orbit_poc.numerics.optimizer import (
    DenseLinearSystem, Linearization, NumericalFailure, certify_rank,
    proposal, selected_covariance,
)


def point():
    rng = np.random.default_rng(74621)
    rows = rng.normal(size=(31, 7))
    q, r = np.linalg.qr(rows)
    rhs = q.T @ rng.normal(size=31)
    return Linearization(r, rhs, np.geomspace(1e-6, 1e6, 7),
                         np.array([True, False, True, True, False, False, True]),
                         31, 21., 3., "fixed-support", None)


@pytest.mark.parametrize("damping", [0., 1e-3, 1., 1e12])
def test_explicit_dense_adapter_is_bitwise_compatibility_path(damping):
    original = point().validate()
    adapted = replace(original, linear_system=DenseLinearSystem()).validate()
    assert certify_rank(original) == certify_rank(adapted)
    before = proposal(original, damping)
    after = proposal(adapted, damping)
    np.testing.assert_array_equal(before[0], after[0])
    assert before[1:] == after[1:]
    design = np.arange(21., dtype=float).reshape(3, 7) / 20
    np.testing.assert_array_equal(selected_covariance(original, design),
                                  selected_covariance(adapted, design))


@pytest.mark.parametrize("tiny", [0., 4*np.finfo(float).eps*31])
def test_adapter_preserves_rejected_rank_and_covariance(tiny):
    original = replace(point(), factor=np.diag([1., 1., 1., 1., 1., 1., tiny]))
    adapted = replace(original, linear_system=DenseLinearSystem())
    for value in (original, adapted):
        with pytest.raises(NumericalFailure) as error:
            certify_rank(value)
        assert error.value.reason == ("rank_deficient" if tiny == 0 else "unresolved_rank")
        with pytest.raises(NumericalFailure):
            selected_covariance(value, np.eye(7))


def test_alternate_system_owns_linear_operations_only():
    class RecordedSystem(DenseLinearSystem):
        def __init__(self):
            self.calls = []

        def validate(self, value):
            self.calls.append("validate")

        def certify_rank(self, value):
            self.calls.append("rank")
            return super().certify_rank(value)

        def proposal(self, value, damping=0.):
            self.calls.append(("step", damping))
            return super().proposal(value, damping)

        def selected_covariance(self, value, design):
            self.calls.append("covariance")
            return super().selected_covariance(value, design)

    system = RecordedSystem()
    value = replace(point(), linear_system=system).validate()
    certify_rank(value)
    proposal(value, .3)
    selected_covariance(value, np.eye(7))
    assert system.calls == ["validate", "rank", ("step", .3), "covariance"]
    assert value.objective == 21. and value.support_hash == "fixed-support"
