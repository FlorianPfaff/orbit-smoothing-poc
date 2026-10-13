"""Sparse-solver checks against independently assembled dense Gaussian systems."""
import numpy as np
from numpy.testing import assert_allclose
from orbit_poc.solvers import solve_block_tridiagonal, marginal_covariances, schur_prefix


def _system(n=9, d=4, seed=5):
    rng = np.random.default_rng(seed)
    factor = np.zeros((n * d, n * d))
    for k in range(n):
        factor[k*d:(k+1)*d, k*d:(k+1)*d] = rng.normal(size=(d, d)) + 3*np.eye(d)
        if k:
            factor[k*d:(k+1)*d, (k-1)*d:k*d] = rng.normal(size=(d, d))
    full = factor.T @ factor + np.eye(n*d)
    diagonal = np.stack([full[k*d:(k+1)*d, k*d:(k+1)*d] for k in range(n)])
    upper = np.stack([full[k*d:(k+1)*d, (k+1)*d:(k+2)*d] for k in range(n-1)]) if n > 1 else np.empty((0,d,d))
    rhs = rng.normal(size=(n, d))
    return full, diagonal, upper, rhs


def test_chain_mean_and_marginals_match_dense():
    full, diagonal, upper, rhs = _system()
    n, d = rhs.shape
    mean = solve_block_tridiagonal(diagonal, upper, rhs)
    expected = np.linalg.solve(full, rhs.ravel()).reshape(n, d)
    assert_allclose(mean, expected, rtol=1e-11, atol=1e-12)
    inverse = np.linalg.inv(full)
    expected_cov = np.stack([inverse[k*d:(k+1)*d, k*d:(k+1)*d] for k in range(n)])
    assert_allclose(marginal_covariances(diagonal, upper), expected_cov, rtol=1e-11, atol=1e-12)


def test_separator_retains_prefix_information():
    full, diagonal, upper, rhs = _system()
    keep = 4
    reduced_a, reduced_e, reduced_b = schur_prefix(diagonal, upper, rhs, keep)
    full_mean = np.linalg.solve(full, rhs.ravel()).reshape(rhs.shape)
    reduced_mean = solve_block_tridiagonal(reduced_a, reduced_e, reduced_b)
    assert_allclose(reduced_mean, full_mean[keep:], rtol=1e-11, atol=1e-12)
    full_covariance = marginal_covariances(diagonal, upper)
    assert_allclose(marginal_covariances(reduced_a, reduced_e), full_covariance[keep:], rtol=1e-11, atol=1e-12)
    # Dropping the prefix without its message is measurably different.
    discarded_mean = solve_block_tridiagonal(diagonal[keep:], upper[keep:], rhs[keep:])
    assert np.linalg.norm(discarded_mean - full_mean[keep:]) > 1e-4


def test_one_state_chain_and_multiple_rhs():
    full, diagonal, upper, rhs = _system(n=1)
    assert_allclose(solve_block_tridiagonal(diagonal, upper, rhs)[0], np.linalg.solve(full, rhs[0]))
    right = np.stack([rhs, 2*rhs], axis=-1)
    result = solve_block_tridiagonal(diagonal, upper, right)
    assert_allclose(result[0], np.linalg.solve(full, right[0]))


def test_bad_separator_rejected():
    _, diagonal, upper, rhs = _system()
    try:
        schur_prefix(diagonal, upper, rhs, len(diagonal))
    except ValueError:
        pass
    else:
        raise AssertionError("Empty retained trajectory must be rejected")


def test_actual_filter_rts_matches_independent_dense_gaussian():
    from types import SimpleNamespace
    from orbit_poc.solvers import _ieks_step
    rng = np.random.default_rng(9)
    n, d = 12, 3
    f = np.stack([np.eye(d) + rng.normal(size=(d, d))*.05 for _ in range(n-1)])
    q = np.broadcast_to(np.eye(d)*.03, (n-1,d,d)).copy()
    chol = np.linalg.cholesky(q)
    nodes = np.array([0, 3, 3, 7, 11])
    h = rng.normal(size=(len(nodes),2,d))
    observation = rng.normal(size=(len(nodes),2))
    process = rng.normal(size=(n-1,d))*.2
    prior = rng.normal(size=d)
    prior_sigma = np.array([.6,.8,1.1])
    damping = np.full((n,d), .02)
    problem = SimpleNamespace(n=n,d=d,nodes=nodes,q=q,chol=chol,prior=prior,prior_sigma=prior_sigma)
    linear = dict(z=np.zeros((n,d)),transition_jacobian=f,r_process=process,h=h,r_obs=observation)
    # Assemble a completely separate dense least-squares system.
    rows, targets = [], []
    a = np.zeros((d,n*d)); a[:,:d] = np.diag(1/prior_sigma)
    rows.append(a); targets.append(prior/prior_sigma)
    for k in range(n-1):
        a=np.zeros((d,n*d))
        a[:,k*d:(k+1)*d] = -np.linalg.solve(chol[k],f[k])
        a[:,(k+1)*d:(k+2)*d] = np.linalg.inv(chol[k])
        rows.append(a); targets.append(-process[k])
    for m,k in enumerate(nodes):
        a=np.zeros((2,n*d)); a[:,k*d:(k+1)*d]=h[m]
        rows.append(a); targets.append(-observation[m])
    rows.append(np.diag(np.sqrt(damping.ravel()))); targets.append(np.zeros(n*d))
    matrix=np.concatenate(rows); target=np.concatenate(targets)
    dense_mean=np.linalg.lstsq(matrix,target,rcond=None)[0].reshape(n,d)
    dense_cov=np.linalg.inv(matrix.T@matrix)
    expected_cov=np.stack([dense_cov[k*d:(k+1)*d,k*d:(k+1)*d] for k in range(n)])
    mean,covariance=_ieks_step(problem,linear,damping,return_covariance=True)
    assert_allclose(mean,dense_mean,rtol=1e-11,atol=1e-12)
    assert_allclose(covariance,expected_cov,rtol=1e-11,atol=1e-12)


def orbital_fixture(model="density", duration=600):
    """Small observable synthetic geometry, intended for solver parity only."""
    from orbit_poc.config import ModelSpec, EARTH_RADIUS, MU
    from orbit_poc.data import Dataset
    from orbit_poc import dynamics
    spec=ModelSpec(model=model)
    truth_spec=ModelSpec(model="density")
    times=np.arange(0.,duration+1.,60.)
    initial=np.array([EARTH_RADIUS+500000.,0,0,0,np.sqrt(MU/(EARTH_RADIUS+500000.)),0,.1])
    states=np.asarray(dynamics.propagate(initial/dynamics.scales(truth_spec),times,truth_spec))
    nodes=np.repeat(np.arange(len(times)),3)
    ps=np.tile(np.array([[EARTH_RADIUS,0,0],[0,EARTH_RADIUS,0],[0,0,EARTH_RADIUS]]),(len(times),1))
    vs=np.zeros_like(ps)
    y=np.asarray(dynamics.batch_observe(states[nodes],ps,vs))
    sigma=np.broadcast_to(np.array([10.,.01]),y.shape).copy()
    sigma[::3] *= 1.5  # Exercise heteroskedastic uncertainty support.
    y=y+np.random.default_rng(7).normal(size=y.shape)*sigma
    data=Dataset(times,dict(node=nodes,station_pos=ps,station_vel=vs,y=y,sigma=sigma),
                 initial[:6]+np.array([300,-200,100,.1,-.1,.05]),np.array([1000]*3+[1]*3))
    return data,spec


def test_orbital_gtsam_and_filter_rts_parity():
    import pytest
    pytest.importorskip("jax")
    pytest.importorskip("gtsam")
    from orbit_poc.solvers import initialize, fit, separator_check
    data,spec=orbital_fixture()
    reference=initialize(data,spec)
    first=fit(data,spec,solver="ieks",reference=reference)
    second=fit(data,spec,solver="gtsam",reference=reference)
    assert first.converged and second.converged
    assert abs(first.objective-second.objective)/max(1.,first.objective) < 1e-4
    assert np.max(np.linalg.norm(first.states[:,:3]-second.states[:,:3],axis=1)) < .1
    check=separator_check(data,spec,states=first.states,reference=reference,boundary_indices=[0,5,10])
    assert check["relative_linear_objective_difference"] < 1e-4
    assert check["max_position_difference_m"] < .1


def test_reference_does_not_depend_on_candidate_ou_sigma():
    import pytest
    from dataclasses import replace
    pytest.importorskip("jax")
    from orbit_poc.solvers import initialize, fit
    data,spec=orbital_fixture()
    first=initialize(data,replace(spec,sigma=.1))
    second=initialize(data,replace(spec,sigma=.8))
    assert_allclose(first,second,rtol=1e-12,atol=1e-12)
    baseline=fit(data,spec,solver="deterministic")
    assert baseline.states.shape[1] == 7
    assert_allclose(baseline.states[:,6],baseline.states[0,6],rtol=0,atol=1e-12)


def test_marginally_small_correlated_update_cannot_stop_early():
    from orbit_poc.solvers import _convergence_gate
    # An update can be tiny relative to both marginal sigmas while large in a
    # tightly constrained difference direction. This caused the v1 IEKS pilot
    # to stop one iteration before the common joint objective was optimized.
    covariance=np.array([[1.,1.-1e-8],[1.-1e-8,1.]])
    delta=np.array([5e-4,-5e-4])
    marginal_fraction=np.max(np.abs(delta)/np.sqrt(np.diag(covariance)))
    whitened=np.linalg.solve(np.linalg.cholesky(covariance),delta)
    decrement=float(whitened@whitened)
    assert marginal_fraction < 1e-3
    passed,limit=_convergence_gate(marginal_fraction,decrement,180.,8e-5)
    assert not passed
    assert decrement > limit
    # A genuinely negligible joint update may fall within the explicit process
    # representational bound; that allowance must not relax marginal smallness.
    assert _convergence_gate(1e-5,4e-5,180.,8e-5)[0]
    assert not _convergence_gate(.1,4e-5,180.,8e-5)[0]


def test_v1_real_colored_failure_fixture_if_available():
    import os
    from pathlib import Path
    import pytest
    pytest.importorskip("jax")
    pytest.importorskip("gtsam")
    from orbit_poc.config import ModelSpec
    from orbit_poc.data import load_dataset
    from orbit_poc.solvers import fit
    root=Path(os.environ.get("ORBIT_POC_REGRESSION_DATA_ROOT",
              "runs/timing-pilot/worker-05/data/leo500-disturbed-normal-seed43"))
    if not (root/"dataset.npz").exists():
        pytest.skip("Optional archived real v1 pilot fixture is not present")
    reference=next(np.load(p) for p in root.glob("reference-*.npy")
                   if np.load(p,mmap_mode="r").shape[1]==9)
    dataset=load_dataset(root/"dataset.npz")
    spec=ModelSpec(model="colored",substep=2.5)
    first=fit(dataset,spec,solver="ieks",reference=reference)
    second=fit(dataset,spec,solver="gtsam",reference=reference)
    assert first.converged and second.converged
    assert first.iterations >= 3
    assert abs(first.objective-second.objective)/max(1.,first.objective) < 1e-4
    assert first.metadata["undamped_step_whitened_squared_norm"] <= first.metadata["joint_decrement_squared_limit"]
