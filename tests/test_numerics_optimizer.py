"""Exercise objective acceptance, rollback and exact nuisance marginalization."""
from dataclasses import replace

import numpy as np
import pytest
from scipy.linalg import qr

from orbit_poc.numerics.config import Controls
from orbit_poc.numerics.optimizer import (Linearization, NumericalFailure, certify_rank,
    minimize, proposal, selected_covariance)


class ProfiledModel:
    def __init__(self, nonlinear=False, support_change=False):
        self.nonlinear, self.support_change = nonlinear, support_change
        self.evaluations = []
        self.finalized = []

    def evaluate(self, state, label, tighter=False):
        x = float(state)
        # Nuisance eta is profiled analytically at each fixed dynamic x.
        y = np.array([3., 1.])
        eta = (y[0]-y[1])/2
        h, j = (np.exp(x), np.exp(x)) if self.nonlinear else (x, 1.)
        residual = np.r_[y - [h+eta, h-eta], -.1*x]
        a = np.array([[j, 1.], [j, -1.], [.1, 0.]])
        scale = 1/np.linalg.norm(a, axis=0)
        q, r = qr(a*scale, mode="economic")
        b = q.T@residual
        point = Linearization(r, b, scale, np.array([True, False]), len(a),
            .5*float(residual@residual), max(0., float(residual@residual-b@b)),
            "modified" if self.support_change and label.startswith("trial") else "fixed-observations",
            x)
        self.evaluations.append((label, x, point.objective))
        return point

    def trial(self, point, delta):
        return point.state+delta[0], {"position_change_m": abs(delta[0])}

    def finish(self, point):
        self.finalized.append(point)
        return {"state": point.state, "covariance": selected_covariance(point, np.eye(2)).tolist()}


def test_affine_map_and_covariance_match_full_rows():
    model = ProfiledModel()
    result = minimize(model, 0.)
    assert result["converged"]
    a = np.array([[1., 1.], [1., -1.], [.1, 0.]])
    expected = np.linalg.lstsq(a, [3., 1., 0.], rcond=None)[0]
    assert result["result"]["state"] == pytest.approx(expected[0], abs=1e-8)
    np.testing.assert_allclose(result["result"]["covariance"], np.linalg.inv(a.T@a), rtol=1e-12, atol=1e-15)
    assert len(model.finalized) == 1


def test_nonlinear_trial_rejection_preserves_the_accepted_reference():
    model = ProfiledModel(nonlinear=True)
    result = minimize(model, -2.)
    assert result["converged"], result
    rejected = [row for row in result["history"] if not row["accepted"]]
    assert rejected
    for left, right in zip(result["history"], result["history"][1:]):
        if not left["accepted"] and not right.get("confirmation"):
            assert right["objective_before"] == left["objective_before"]
    accepted = [row["objective_trial"] for row in result["history"] if row["accepted"] and not row.get("confirmation")]
    assert all(b < a for a, b in zip(accepted, accepted[1:]))
    assert result["history"][-1]["normalized_gradient"] < 1e-8


def test_changed_weights_or_support_fails_without_covariance():
    model = ProfiledModel(support_change=True)
    result = minimize(model, 0.)
    assert result["status"] == "changed_support"
    assert not result["covariance_valid"] and not model.finalized


def test_inexact_profile_allows_only_resolved_progress_to_a_strict_final_fit():
    class InitiallyLimited(ProfiledModel):
        def evaluate(self, state, label, tighter=False):
            point = super().evaluate(state, label, tighter)
            if abs(state) < .1:
                return replace(point, objective_floor=1e-8, metadata={"nuisance_floor_limited": True})
            return point

    model = InitiallyLimited()
    result = minimize(model, 0.)
    assert result["converged"] and model.finalized
    first = result["history"][0]
    assert first["nuisance_floor_limited_before"] and first["accepted"]
    assert first["nuisance_resolution_sum"] <= 1e-3*first["predicted_reduction"]
    assert not model.finalized[-1].metadata.get("nuisance_floor_limited", False)


def test_inexact_profile_rejects_unresolved_progress_and_never_declares_convergence():
    class Limited(ProfiledModel):
        def evaluate(self, state, label, tighter=False):
            return replace(super().evaluate(state, label, tighter), objective_floor=10.,
                           metadata={"nuisance_floor_limited": True})

    model = Limited()
    result = minimize(model, 0., controls=replace(Controls(), maximum_trial_evaluations=4))
    assert not result["converged"] and not model.finalized
    assert result["history"][0]["reason"] == "unresolved_nuisance_profile_reduction"
    assert result["accepted_iterations"] == 0
    # At the analytic MAP, small physical steps and a small full retained
    # gradient cannot turn an unresolved conditional nuisance fit into success.
    model = Limited()
    result = minimize(model, 4/2.01, controls=replace(Controls(), maximum_trial_evaluations=4))
    assert not result["converged"] and not model.finalized
    assert not any(label == "confirmation" for label, _, _ in model.evaluations)

    class LimitedConfirmation(ProfiledModel):
        def evaluate(self, state, label, tighter=False):
            point = super().evaluate(state, label, tighter)
            return (replace(point, objective_floor=1e-8, metadata={"nuisance_floor_limited": True})
                    if label == "confirmation" else point)

    model = LimitedConfirmation()
    result = minimize(model, 4/2.01, controls=replace(Controls(), maximum_trial_evaluations=4))
    assert not result["converged"] and not model.finalized
    assert result["confirmation_checks"]
    assert all(not check["stationary"] and check["nuisance_floor_limited"]
               for check in result["confirmation_checks"])


def test_only_accepted_state_factors_receive_storage_protection():
    class RejectTrials(ProfiledModel):
        def __init__(self):
            super().__init__()
            self.protected = []

        def accept(self, point):
            self.protected.append(point.state)

        def evaluate(self, state, label, tighter=False):
            point = super().evaluate(state, label, tighter)
            return replace(point, objective=point.objective+10.) if label.startswith("trial-") else point

    model = RejectTrials()
    result = minimize(model, 0., controls=replace(Controls(), maximum_trial_evaluations=4))
    assert result["status"] == "iteration_limit"
    assert model.protected and set(model.protected) == {0.}
    assert all(not row["accepted"] for row in result["history"])


def test_failed_fresh_stationarity_continues_bounded_trials_without_covariance():
    class NonstationaryConfirmation(ProfiledModel):
        confirmation_count = 0

        def evaluate(self, state, label, tighter=False):
            value = super().evaluate(state, label, tighter)
            if label == "confirmation":
                self.confirmation_count += 1
                value = replace(value, rhs=value.rhs+1e-4)
            return value

    model = NonstationaryConfirmation()
    result = minimize(model, 0., controls=replace(Controls(), maximum_trial_evaluations=12))
    assert result["status"] == "iteration_limit"
    assert not result["converged"] and not model.finalized
    refreshed = [row for row in result["history"] if row.get("confirmation_refresh")]
    assert refreshed
    check = refreshed[0]["confirmation_refresh"]
    assert check["physical_parameters_unchanged"]
    assert check["normalized_gradient"] >= 1e-8
    assert check["objective_refreshed"] == refreshed[0]["objective_before"]
    assert not refreshed[0]["accepted"]
    assert len(result["confirmation_checks"]) == model.confirmation_count
    assert all(not value["stationary"] and value["physical_parameters_unchanged"]
               for value in result["confirmation_checks"])


@pytest.mark.parametrize("reason", ["closure_failed", "nuisance_failure", "unresolved_rank"])
def test_failed_trial_is_rolled_back_before_retrying(reason):
    class FailedFirstTrial(ProfiledModel):
        def evaluate(self, state, label, tighter=False):
            if label == "trial-001":
                raise NumericalFailure(reason, "controlled candidate failure")
            return super().evaluate(state, label, tighter)

    result = minimize(FailedFirstTrial(), 0.)
    assert result["converged"], result
    first, second = result["history"][:2]
    assert not first["accepted"] and first["reason"] == reason
    assert second["objective_before"] == first["objective_before"]
    assert second["damping"] > first["damping"]


def test_unresolved_candidate_rank_cannot_be_accepted():
    class BadCandidate(ProfiledModel):
        def evaluate(self, state, label, tighter=False):
            value = super().evaluate(state, label, tighter)
            if label == "trial-001":
                value = replace(value, factor=np.diag([1., 3*np.finfo(float).eps*3]))
            return value

    result = minimize(BadCandidate(), 0.)
    assert result["converged"], result
    assert result["history"][0]["reason"] == "unresolved_rank"
    assert not result["history"][0]["accepted"]


def test_tiny_damped_step_does_not_pass_raw_convergence():
    model = ProfiledModel()
    controls = replace(Controls(), initial_damping=1e20, maximum_trial_evaluations=3)
    result = minimize(model, 0., controls=controls)
    assert not result["converged"] and not model.finalized
    assert all(row["raw_correction"]["position_change_m"] > 1 for row in result["history"])


@pytest.mark.parametrize("slow_stage", ["confirmation", "finish"])
def test_final_verification_cannot_exceed_the_wall_budget(slow_stage):
    elapsed = [0.]

    class SlowVerification(ProfiledModel):
        def evaluate(self, state, label, tighter=False):
            value = super().evaluate(state, label, tighter)
            if label == slow_stage:
                elapsed[0] = 7201.
            return value

        def finish(self, point):
            value = super().finish(point)
            if slow_stage == "finish":
                elapsed[0] = 7201.
            return value

    model = SlowVerification()
    result = minimize(model, 0., clock=lambda: elapsed[0])
    assert result["status"] == "timeout"
    assert not result["converged"] and not result["covariance_valid"]
    assert "result" not in result


def test_initialization_and_finalization_share_one_wall_budget():
    elapsed = [10.]

    class SlowFinalization(ProfiledModel):
        def finish(self, point):
            value = super().finish(point)
            elapsed[0] = 7205.
            return value

    result = minimize(SlowFinalization(), 0., clock=lambda: elapsed[0], started_at=0.)
    assert result["status"] == "timeout" and not result["converged"]
    assert "result" not in result
    already_expired = ProfiledModel()
    result = minimize(already_expired, 0., clock=lambda: elapsed[0], started_at=0.)
    assert result["status"] == "timeout" and not already_expired.evaluations


def test_initial_objective_floor_is_remeasured_near_the_solution():
    class ChangingFloor(ProfiledModel):
        def evaluate(self, state, label, tighter=False):
            value = super().evaluate(state, label, tighter)
            if label == "repeat" and state == 0.:
                value = replace(value, objective=value.objective+1e-6)
            return value

    result = minimize(ChangingFloor(), 0.)
    assert result["converged"], result
    checks = [row for row in result["history"] if row.get("floor_measurement")]
    assert checks and checks[-1]["objective_floor"] < 1e-10
    assert result["history"][-1]["normalized_gradient"] < 1e-8


def test_floor_refinement_refreshes_the_undamped_stationarity_factor():
    class ApproximateClosure(ProfiledModel):
        def evaluate(self, state, label, tighter=False):
            value = super().evaluate(state, label, tighter)
            if label == "repeat" and state == 0.:
                value = replace(value, objective=value.objective+1e-6)
            if label.startswith("trial") and not tighter:
                value = replace(value, rhs=value.rhs+np.array([3e-6, 0.]))
            return value

    result = minimize(ApproximateClosure(), 0.)
    assert result["converged"], result
    refinements = [row["floor_measurement"] for row in result["history"] if "floor_measurement" in row]
    assert refinements and all(row["physical_parameters_unchanged"] for row in refinements)
    assert result["history"][-1]["normalized_gradient"] < 1e-8


def test_unresolved_objective_improvement_is_flagged_without_replacing_acceptance_rule():
    class MeasuredFloor(ProfiledModel):
        def evaluate(self, state, label, tighter=False):
            return replace(super().evaluate(state, label, tighter), objective_floor=1e-3)

    result = minimize(MeasuredFloor(), 0.)
    assert result["converged"], result
    trials = [row for row in result["history"] if "trial" in row]
    assert any(row["accepted"] and not row["objective_reduction_numerically_resolved"] for row in trials)
    assert all(row["actual_reduction"] > 0 and row["gain_ratio"] > 1e-4 for row in trials if row["accepted"])
    assert result["history"][-1]["normalized_gradient"] < 1e-8


def test_rank_classification_and_no_pseudoinverse_covariance():
    p = ProfiledModel().evaluate(0., "fixture")
    for last, status in ((0., "rank_deficient"), (3*np.finfo(float).eps*3, "unresolved_rank")):
        bad = replace(p, factor=np.diag([1., last]))
        with pytest.raises(NumericalFailure, match=status):
            certify_rank(bad)
        with pytest.raises(NumericalFailure):
            selected_covariance(bad, np.eye(2))


def test_dynamic_only_damping_and_undamped_covariance():
    point = ProfiledModel().evaluate(0., "fixture")
    zero, _, _ = proposal(point)
    damped, _, _ = proposal(point, 1e5)
    assert abs(damped[0]) < abs(zero[0])*1e-4
    assert damped[1] == pytest.approx(zero[1], abs=1e-14)
    covariance = selected_covariance(point, np.eye(2))
    assert covariance[0, 0] > .49


def test_selected_cross_covariance_matches_global_elimination():
    rng = np.random.default_rng(148)
    a = rng.normal(size=(40, 9))
    scales = 1/np.linalg.norm(a, axis=0)
    q, r = qr(a*scales, mode="economic")
    residual = rng.normal(size=40)
    b = q.T@residual
    point = Linearization(r, b, scales, np.array([True]*3+[False]*6), 40,
        .5*float(residual@residual), float(residual@residual-b@b), "fixed", None)
    design = rng.normal(size=(6, 9))
    np.testing.assert_allclose(selected_covariance(point, design), design@np.linalg.inv(a.T@a)@design.T, rtol=1e-12, atol=1e-14)
    units = np.geomspace(1e-9, 1e9, 9)
    changed = replace(point, scales=scales/units)
    np.testing.assert_allclose(selected_covariance(changed, design*units), selected_covariance(point, design), rtol=1e-12)
