"""Native derivative kernels, complete synthetic STM, and fail-closed profiles."""
from decimal import Decimal
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

import numpy as np
import pytest
from scipy.integrate import solve_ivp
from scipy.special import eval_legendre

from orbit_poc.comparison.backend import read_native_table

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def derivative_kernel(tmp_path_factory):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("C++ compiler required for native derivative kernels")
    target = tmp_path_factory.mktemp("native-derivatives") / "test"
    subprocess.run([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-I", str(ROOT / "groops/extension"),
                    str(ROOT / "tests/fixtures/six_state_tangent.cpp"), "-o", str(target)], check=True,
                   capture_output=True, text=True)
    return target


@pytest.mark.parametrize("mode", ["forces", "finite_difference", "oscillator", "day_oscillator", "day_kepler"])
def test_native_derivative_kernel(derivative_kernel, mode):
    completed = subprocess.run([str(derivative_kernel), mode], capture_output=True, text=True, timeout=90)
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.fixture
def native_v31():
    executable = os.environ.get("ORBIT_POC_GROOPS")
    if not executable:
        pytest.skip("ORBIT_POC_GROOPS must name the built v3.1 executable for native integration gates")
    assert Path(executable).is_file()
    return executable


def _add(parent, name, value=None):
    node = ET.SubElement(parent, name)
    if value is not None:
        node.text = str(value)
    return node


def _run(executable, config, directory):
    path = directory / "config.xml"
    ET.ElementTree(config).write(path, encoding="utf-8", xml_declaration=True)
    completed = subprocess.run([executable, str(path)], cwd=directory, capture_output=True, text=True, timeout=180)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed


def _forces(parent, density=None):
    forces = _add(parent, "forces")
    _add(_add(forces, "miscAccelerations"), "syntheticGravity")
    wrapper = _add(forces, "miscAccelerations")
    if density is not None:
        wrapper = _add(wrapper, "logDensity")
        _add(wrapper, "inputfileLogDensity", density)
        wrapper = _add(wrapper, "nominalDrag")
    # Amplified, explicitly configured density makes missing drag velocity
    # derivatives observable without changing the mathematical force model.
    drag = _add(wrapper, "syntheticDrag")
    _add(drag, "referenceDensity", "5e-10")


def _acceleration(state, density=1., harmonic12=False):
    p, v = state[:3], state[3:]
    r = np.linalg.norm(p)
    factor = 1.5 * 1.08262668e-3 * 3.986004418e14 * 6378137.**2 / r**5
    gravity = -3.986004418e14 * p / r**3 + factor * p * (5 * p[2]**2 / r**2 - np.array([1., 1., 3.]))
    if harmonic12:
        n, q = 12, p[2]/r
        polynomial = eval_legendre(n, q)
        derivative = n*(eval_legendre(n-1, q)-q*polynomial)/(1-q*q)
        gravity += 3.986004418e14/r**2 * (6378137./r)**n * np.sqrt(2*n+1)*1e-5 * (
            -(n+1)*polynomial*p/r + derivative*(np.array([0., 0., 1.])-q*p/r))
    relative = v - np.cross([0., 0., 7.2921150e-5], p)
    rho = 5e-10 * np.exp(-(r-6378137.-500000.) / 60000.) * density
    return gravity - .5 * .022 * rho * np.linalg.norm(relative) * relative


def test_actual_native_synthetic_force_instances(native_v31, tmp_path):
    states = np.array([[60000., 6878137., 200000., 400000., -500., 7300., 1500.],
                       [60000.+60/86400, 7500000., 100000., -700000., -1000., 6500., 1800.]])
    knots = np.array([[60000., .2], [60000.+60/86400, -.1], [60000.+120/86400, .3]])
    np.savetxt(tmp_path / "density.txt", knots, fmt="%.17e")
    def execute(values):
        np.savetxt(tmp_path / "states.txt", values, fmt="%.17e")
        config = ET.Element("groops")
        program = _add(_add(config, "program"), "OrbitPocStateDerivatives")
        _add(program, "inputfileStates", tmp_path / "states.txt")
        _add(program, "outputfileForceJacobian", tmp_path / "jacobian.txt")
        _forces(program, tmp_path / "density.txt")
        _run(native_v31, config, tmp_path)
        return read_native_table(tmp_path / "jacobian.txt", 22)
    actual = execute(states)
    jacobian = np.concatenate((actual[:, 4:13].reshape(-1, 3, 3), actual[:, 13:22].reshape(-1, 3, 3)), axis=2)
    for column in range(6):
        plus, minus = states.copy(), states.copy()
        # A larger velocity step keeps tiny high-altitude drag changes above
        # cancellation against the roughly 8 m/s² gravitational acceleration.
        step = .5
        plus[:, 1+column] += step
        minus[:, 1+column] -= step
        observed = (execute(plus)[:, 1:4] - execute(minus)[:, 1:4]) / (2*step)
        np.testing.assert_allclose(observed, jacobian[:, :, column], rtol=3e-4, atol=2e-14)


def _native_reference(directory, times, states):
    for filename, kind, values in (("orbit.txt", -6, np.column_stack((states, np.array([_acceleration(s) for s in states])))),
                                   ("attitude.txt", -7, np.tile([1., 0., 0., 0.], (len(times), 1)))):
        with (directory / filename).open("w") as stream:
            stream.write(f"groops instrument version=20200123\n{kind} 1\n{len(times)}\n")
            for time, row in zip(times, values):
                epoch = Decimal(60000) + Decimal(str(time))/Decimal(86400)
                stream.write(f"{epoch:.18f} " + " ".join(f"{x:.17e}" for x in row) + "\n")


@pytest.mark.parametrize("profile,density_knots", [("synthetic_complete_v1", False),
                                                   ("synthetic_complete_v1", True),
                                                   ("flight_gravity_drag_v1", False)])
def test_actual_native_complete_synthetic_transition(native_v31, tmp_path, profile, density_knots):
    times = np.arange(0., 605., 5.)
    initial = np.array([6878137., 0., 200000., 0., 7400., 500.])
    knot_times = np.arange(0., 660., 60.)
    knot_values = .3*np.sin(knot_times/160.)
    def density(t, values):
        return np.exp(np.interp(t, knot_times, values)) if density_knots else 1.
    def trajectory(x, values=knot_values):
        # The independent integration also stops at every nonsmooth density
        # knot; adaptive RK steps spanning a knot contaminate finite differences.
        edges = knot_times if density_knots else [times[0], times[-1]]
        pieces, initial_state = [], x
        for left, right in zip(edges[:-1], edges[1:]):
            grid = times[(times >= left) & (times <= right)]
            result = solve_ivp(lambda t, y: np.r_[y[3:], _acceleration(y, density(t, values), profile=="flight_gravity_drag_v1")],
                               (left, right), initial_state, method="DOP853", t_eval=grid,
                               rtol=3e-14, atol=1e-9, max_step=5.)
            assert result.success
            pieces.append(result.y.T if not pieces else result.y.T[1:])
            initial_state = result.y[:, -1]
        return np.concatenate(pieces)
    reference = trajectory(initial)
    _native_reference(tmp_path, times, reference)
    config = ET.Element("groops")
    program = _add(_add(config, "program"), "PreprocessingVariationalEquation")
    for name, value in (("outputfileVariational", "variational.dat"), ("outputfileOrbit", "integrated.txt"),
                        ("inputfileOrbit", "orbit.txt"), ("inputfileStarCamera", "attitude.txt"),
                        ("orbitPocDerivativeDiagnostics", "derivatives.json")):
        _add(program, name, tmp_path / value)
    _add(program, "orbitPocDerivativeProfile", profile)
    if density_knots:
        path = tmp_path / "density.txt"
        path.write_text("".join(f"{Decimal(60000)+Decimal(str(t))/Decimal(86400):.18f} {g:.17e}\n"
                                for t, g in zip(knot_times, knot_values)))
        _forces(program, path)
        boundaries = _add(_add(program, "integrationBoundaries"), "uniformSampling")
        for name, value in (("timeStart", "60000"), ("timeEnd", "60000+600/86400"), ("sampling", "60/86400")):
            _add(boundaries, name, value)
    else:
        _forces(program)
    if profile == "flight_gravity_drag_v1":
        # Exercise the flight adapter against independently known forces. The
        # nonzero degree-12 term exposes accidental reuse of a degree-2 Hessian.
        # This is not a flight-data or JB2008 validation claim.
        gravity_path = tmp_path / "gravity.gfc"
        gravity_path.write_text("modelname numerical_test\nproduct_type gravity_field\n"
            "earth_gravity_constant 3.986004418e14\nradius 6378137\nmax_degree 12\n"
            "norm fully_normalized\nerrors no\nend_of_head\n"
            f"gfc 0 0 1 0\ngfc 2 0 {-1.08262668e-3/np.sqrt(5):.17e} 0\ngfc 12 0 1e-5 0\n\n")
        forces = program.find("forces")
        forces.remove(forces.find("miscAccelerations"))
        coefficients = _add(_add(forces, "gravityfield"), "potentialCoefficients")
        _add(coefficients, "inputfilePotentialCoefficients", gravity_path)
        _add(coefficients, "maxDegree", 12)
        _add(program, "orbitPocAtmosphericForce").append(deepcopy(forces.find("miscAccelerations/syntheticDrag")))
        _add(program, "orbitPocAtmosphericQuadratureStep", 1)
    rotation = _add(_add(program, "earthRotation"), "zAxis")
    for name, value in (("initialAngle", 0), ("angularVelocity", 0), ("time0", 60000)):
        _add(rotation, name, value)
    _add(program, "integrationDegree", 7)
    _add(_add(program, "useEnke"), "GM", "3.986004418e14")
    export = _add(_add(config, "program"), "OrbitPocStateDerivatives")
    _add(export, "inputfileVariational", tmp_path / "variational.dat")
    _add(export, "outputfileStateTransition", tmp_path / "transition.txt")
    _run(native_v31, config, tmp_path)
    rows = read_native_table(tmp_path / "transition.txt", 43)
    stm = rows[:, 7:].reshape(-1, 6, 6)
    for column in range(6):
        step = 2. if column < 3 else .002
        plus, minus = initial.copy(), initial.copy()
        plus[column] += step
        minus[column] -= step
        observed = (trajectory(plus)-trajectory(minus)) / (2*step)
        np.testing.assert_allclose(stm[:, :, column], observed, rtol=3e-7, atol=1e-5)
    diagnostics = json.loads((tmp_path / "derivatives.json").read_text())
    assert diagnostics["omitted_terms"] == ([] if profile=="synthetic_complete_v1" else [
        "thermal_history_sensitivities", "non_gravity_non_drag_force_gradients", "atmospheric_event_time_derivatives"])
    if profile=="flight_gravity_drag_v1":
        assert diagnostics["drag_fd_evaluations"] > 0
        assert diagnostics["drag_fd_maximum_relative_difference"] < .002
        assert diagnostics["drag_fd_position_absolute_tolerance_s_minus2"] == 2e-18
        assert diagnostics["drag_fd_position_derivative_floor_s_minus2"] == 1e-15
        assert diagnostics["drag_fd_velocity_absolute_tolerance_s_minus1"] == 2e-20
        assert diagnostics["drag_fd_initial_position_step_m"] == 1000
        assert 0 < diagnostics["drag_fd_position_step_range_m"][0] <= diagnostics["drag_fd_position_step_range_m"][1] <= 500
        assert diagnostics["drag_fd_initial_velocity_step_m_s"] == .001
    assert diagnostics["maximum_tangent_relative_residual"] <= 2e-12
    assert diagnostics["tangent_integral_accumulation"] == "long_double_local_moments"
    assert diagnostics["tangent_accumulator_binary_digits"] >= 64
    assert diagnostics["initial_velocity_parameter_scale"] == pytest.approx(1/600)
    # The independent forward reference is already closed. A correct tangent
    # correction must not displace it by more than the measurement refinement gate.
    assert np.max(np.linalg.norm(rows[:, 1:4]-reference[:, :3], axis=1)) < 3e-5
    if profile=="synthetic_complete_v1":
        config = ET.Element("groops")
        evaluate = _add(_add(config, "program"), "OrbitPocEvaluateVariational")
        _add(evaluate, "inputfileVariational", tmp_path / "variational.dat")
        _add(evaluate, "outputfileOrbit", tmp_path / "dynamic-design.txt")
        _add(evaluate, "inputfileParameters", tmp_path / "parameters.txt")
        if density_knots:
            # New complete STM must also feed the existing direct density
            # design through native variation of constants.
            density_node = _add(_add(evaluate, "parametrizationAcceleration"), "logDensity")
            _add(density_node, "inputfileLogDensity", tmp_path / "density.txt")
            _add(_add(_add(density_node, "nominalDrag"), "syntheticDrag"), "referenceDensity", "5e-10")
            step, column = 1e-3, 5
            parameters = np.zeros(len(knot_times)+6)
            parameters[column] = step
            plus, minus = knot_values.copy(), knot_values.copy()
            plus[column] += step
            minus[column] -= step
            independently_perturbed = (trajectory(initial, plus)-trajectory(initial, minus))/(2*step)
        else:
            # A fixed native inertial pulse is µm/s, and its stored epoch must
            # export velocity AFTER the jump. Independently integrate the two
            # physical post-pulse arcs in SI units.
            series = _add(_add(evaluate, "stochasticPulse"), "uniformSampling")
            for name, value in (("timeStart", "60000"), ("timeEnd", "60000"), ("sampling", 1), ("offsetSeconds", 300)):
                _add(series, name, value)
            step = .001
            parameters = np.zeros(9)
            parameters[0] = step*1e6
            after = times >= 300
            def pulsed(sign):
                start = reference[np.flatnonzero(after)[0]].copy()
                start[3] += sign*step
                result = solve_ivp(lambda t, y: np.r_[y[3:], _acceleration(y)], (300., times[-1]), start,
                                   method="DOP853", t_eval=times[after], rtol=3e-14, atol=1e-9, max_step=5.)
                assert result.success
                full = reference.copy()
                full[after] = result.y.T
                return full
            independently_perturbed = (pulsed(1)-pulsed(-1))/(2*step)
        np.savetxt(tmp_path / "parameters.txt", parameters[:, None], fmt="%.17e")
        _run(native_v31, config, tmp_path)
        evaluated = read_native_table(tmp_path / "dynamic-design.txt", 10)
        actual_design = (evaluated[:, 1:7]-rows[:, 1:7])/step
        np.testing.assert_allclose(actual_design, independently_perturbed, rtol=5e-4, atol=3e-5)
        if not density_knots:
            np.testing.assert_allclose(evaluated[60, 4:7]-rows[60, 4:7], [step, 0, 0], rtol=0, atol=1e-10)
