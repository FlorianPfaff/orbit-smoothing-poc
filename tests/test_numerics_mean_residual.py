"""Residual mean arithmetic against Decimal and an exact coupled-system oracle.

These cheap tests compile the actual scalar arithmetic in the staged native
header. The independent rational system checks the coordinate transformation,
including velocity coupling and both fitted homogeneous components. They do
not establish native trajectory closure or the failed objective gate.
"""
from decimal import Decimal, localcontext
from fractions import Fraction as F
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def mean_arithmetic(tmp_path_factory):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("C++ compiler required for the native arithmetic fixture")
    directory = tmp_path_factory.mktemp("mean-residual-arithmetic")
    source = (ROOT / "groops/extension/stagedVariationalBody.h").read_text()
    begin = "  // BEGIN ORBIT_POC_MEAN_RESIDUAL_ARITHMETIC (also compiled by the focused test)\n"
    end = "  // END ORBIT_POC_MEAN_RESIDUAL_ARITHMETIC"
    assert source.count(begin) == source.count(end) == 1
    (directory / "mean_residual_arithmetic.inc").write_text(source.split(begin)[1].split(end)[0])
    executable = directory / "check"
    subprocess.run([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-I", str(directory),
                    str(ROOT / "tests/fixtures/mean_residual_arithmetic.cpp"), "-o", str(executable)],
                   check=True, capture_output=True, text=True)

    def evaluate(rows):
        payload = "".join(" ".join(format(float(x), ".17g") for x in row)+"\n" for row in rows)
        result = subprocess.run([str(executable)], input=payload, text=True, capture_output=True,
                                check=True, timeout=5)
        return np.array([[float(x) for x in line.split()] for line in result.stdout.splitlines()])
    return evaluate


def _decimal_result(row, residual):
    with localcontext() as context:
        context.prec = 100
        reference, approximate, integral = (Decimal.from_float(float(x)) for x in row)
        return float(reference-approximate+integral if residual else approximate+integral)


def test_actual_residual_retains_sub_ulp_signal(mean_arithmetic):
    rows = [[position, position, sign*2.**exponent]
            for position in (6878137., -6878137., 7600., -7600.)
            for sign in (-1, 1) for exponent in (-48, -45, -42)]
    actual = mean_arithmetic(rows)
    np.testing.assert_array_equal(actual[:, 0], [_decimal_result(r, True) for r in rows])
    # The original full-state add/subtract loses every one of these signals.
    assert np.all(actual[:, 2] == 0)
    assert np.all(actual[:, 0] != 0)


def test_actual_residual_is_translation_invariant(mean_arithmetic):
    rows = [[origin+offset, origin, -offset+small]
            for origin in (0., 6878137., -6878137., 2.**32)
            for offset in (-2048., 1024.) for small in (-2.**-28, 2.**-28)]
    actual = mean_arithmetic(rows)[:, 0]
    np.testing.assert_array_equal(actual, [_decimal_result(r, True) for r in rows])
    np.testing.assert_array_equal(actual.reshape(4, 4), np.tile(actual[:4], (4, 1)))


def test_actual_absolute_restore_rounds_once(mean_arithmetic):
    rows = [[0., position, correction]
            for position in (0., 6878137., -6878137., 7600., -7600.)
            for correction in (-.01, .01, -2.**-29, 2.**-29, 2.**-42)]
    np.testing.assert_array_equal(mean_arithmetic(rows)[:, 1],
                                  [_decimal_result(r, False) for r in rows])


def _solve_exact(matrix, rhs):
    """Independent rational Gauss-Jordan solve, without floating arithmetic."""
    a = [list(map(F, row))+[F(value)] for row, value in zip(matrix, rhs)]
    n = len(a)
    for j in range(n):
        pivot = next(i for i in range(j, n) if a[i][j])
        a[j], a[pivot] = a[pivot], a[j]
        factor = a[j][j]
        a[j] = [v/factor for v in a[j]]
        for i in range(n):
            if i != j:
                factor = a[i][j]
                a[i] = [v-factor*w for v, w in zip(a[i], a[j])]
    return [row[-1] for row in a]


def _matvec(a, x):
    return [sum((v*w for v, w in zip(row, x)), F(0)) for row in a]


def _fit_exact(a, b):
    columns = list(zip(*a))
    # Exact rational products introduce no normal-equation conditioning error;
    # this is an algebra oracle, not the production least-squares solver.
    gram = [[sum((x*y for x, y in zip(c, d)), F(0)) for d in columns] for c in columns]
    return _solve_exact(gram, [sum((x*y for x, y in zip(c, b)), F(0)) for c in columns])


def test_residual_coordinates_match_exact_coupled_mean_problem(mean_arithmetic):
    # Three position and three velocity epochs; the nonzero off-diagonal
    # blocks exercise both d(a)/d(r) and d(a)/d(v) effects.
    a = [[F(i == j) for j in range(6)] for i in range(6)]
    for i in range(3):
        for j in range(i):
            a[i][j] += F(i-j, 64)
            a[i][3+j] += F(i-j, 1024)
            a[3+i][j] += F(1, 64)
            a[3+i][3+j] += F(1, 1024)
    basis = [[F(1), F(i, 2)] for i in range(3)]+[[F(0), F(1, 4)] for _ in range(3)]
    reference_orbit = [F(x) for x in (6878137, 6200000, 5100000, 7600, 7000, 6200)]
    offsets = [F(x) for x in (1024, -2048, 512, 4, -8, 2)]
    signals = [F(1, 2**27), -F(3, 2**27), F(5, 2**27), F(1, 2**37), -F(3, 2**37), F(5, 2**37)]
    enke = [x+d for x, d in zip(reference_orbit, offsets)]
    integrated_force = [-d+s for d, s in zip(offsets, signals)]

    # Oracle follows the original full-state equations, entirely as rationals.
    forced = [x+y for x, y in zip(enke, integrated_force)]
    initial = _fit_exact(basis[:3], [x-y for x, y in zip(reference_orbit[:3], forced[:3])])
    forced = [x+y for x, y in zip(forced, _matvec(basis, initial))]
    correction = _solve_exact(a, [x-y for x, y in zip(forced, reference_orbit)])
    tangent = list(map(list, zip(*[_solve_exact(a, column) for column in zip(*basis)])))
    absolute = [x+y for x, y in zip(reference_orbit, correction)]
    homogeneous = _fit_exact(tangent[:3], [x-y for x, y in zip(reference_orbit[:3], absolute[:3])])
    exact = [x+y for x, y in zip(absolute, _matvec(tangent, homogeneous))]

    # Residual coordinate formulation uses the compiled native scalar path.
    residual = mean_arithmetic(zip(enke, reference_orbit, integrated_force))[:, 0]
    aa, bb, tt = (np.array(value, dtype=float) for value in (a, basis, tangent))
    initial = np.linalg.lstsq(bb[:3], -residual[:3], rcond=None)[0]
    correction = np.linalg.solve(aa, residual+bb@initial)
    homogeneous = np.linalg.lstsq(tt[:3], -correction[:3], rcond=None)[0]
    correction += tt@homogeneous
    actual = mean_arithmetic([[0., x, d] for x, d in zip(reference_orbit, correction)])[:, 1]
    np.testing.assert_array_equal(actual, [float(v) for v in exact])
    exact_correction = np.array([float(x-y) for x, y in zip(exact, reference_orbit)])
    np.testing.assert_allclose(correction, exact_correction, rtol=2e-13, atol=1e-22)
