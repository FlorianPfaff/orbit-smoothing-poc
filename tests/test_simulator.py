import numpy as np
import pytest

from orbit_poc.simulator import (MU, RADIUS, density_parameters, initial_state,
                                 station_states, geometric_observables, log_density_correction,
                                 generate)


def test_initial_orbit_geometry():
    state = initial_state("eccentric")
    radius = np.linalg.norm(state[:3])
    energy = np.dot(state[3:], state[3:])/2 - MU/radius
    semimajor = -MU/(2*energy)
    assert radius == pytest.approx(RADIUS+300e3)
    assert 2*semimajor-radius == pytest.approx(RADIUS+800e3)


def test_range_rate_is_time_derivative_including_station_rotation():
    t, dt = 130., 1e-3
    state = initial_state("leo500")
    p, v = station_states(np.array([t-dt,t,t+dt]))
    shifted = np.tile(state, (3,1))
    shifted[:, :3] += np.array([-dt,0,dt])[:,None]*state[3:]
    y = geometric_observables(shifted, p[:,0], v[:,0])
    assert y[1,1] == pytest.approx((y[2,0]-y[0,0])/(2*dt), abs=2e-6)


def test_storm_is_exact_density_multiplier_at_peak():
    params = density_parameters(42)
    delta = log_density_correction(43200.,"disturbed",params)-log_density_correction(43200.,"quiet",params)
    assert np.exp(delta) == pytest.approx(2.)


def test_generation_is_reproducible_and_truth_is_separate(tmp_path):
    from orbit_poc.data import load_dataset
    cfg = {"duration_hours": 2, "seed": 202, "orbit": "leo300"}
    a = generate(cfg,tmp_path/"a",truth_backend="scipy")
    b = generate(cfg,tmp_path/"b",truth_backend="scipy")
    da, db = load_dataset(a["dataset"]), load_dataset(b["dataset"])
    assert len(da.observations["node"]) > 0
    np.testing.assert_array_equal(da.observations["y"],db.observations["y"])
    assert da.metadata["benchmark_truth"] is False
    with np.load(a["dataset"],allow_pickle=False) as archive:
        assert "states" not in archive.files
        assert "log_density_correction" not in archive.files
    blackout = generate({**cfg,"coverage":"blackout","blackout_hours":[.5,1.]},tmp_path/"gap",truth_backend="scipy")
    dg = load_dataset(blackout["dataset"])
    obs_t = dg.times[dg.observations["node"]]
    assert not np.any((obs_t >= 1800.) & (obs_t <= 3600.))
    normal_t = da.times[da.observations["node"]]
    surviving = (normal_t < 1800.) | (normal_t > 3600.)
    np.testing.assert_array_equal(dg.observations["y"], da.observations["y"][surviving])


def test_scipy_cannot_misrepresent_stress(tmp_path):
    with pytest.raises(ValueError,match="Stress truth requires TudatPy"):
        generate({"duration_hours":1,"truth_profile":"stress"},tmp_path,truth_backend="scipy")
