"""Independent equality-constrained QR tests; no GROOPS installation is needed.

The oracle parameterizes the equality null space and uses SciPy Householder QR.
It does not reuse the native elimination schedule or form normal equations.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest
from scipy import linalg

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def segmented_native_binary(tmp_path_factory):
    supplied = os.environ.get("ORBIT_POC_SEGMENTED_SOLVER")
    if supplied:
        binary = Path(supplied)
        assert binary.is_file() and os.access(binary, os.X_OK), "Supplied constrained QR executable is unavailable"
        expected = os.environ.get("ORBIT_POC_SEGMENTED_SOLVER_SHA256")
        if expected:
            assert hashlib.sha256(binary.read_bytes()).hexdigest() == expected, "Supplied constrained QR executable hash changed"
        return binary
    output = tmp_path_factory.mktemp("segmented-native") / "segmented-qr"
    compiler = shutil.which("g++")
    assert compiler, "The native constrained QR tests require a C++17 compiler"
    libraries = []
    for name in ("lapack", "blas"):
        paths = [Path(f"/usr/lib/x86_64-linux-gnu/lib{name}.so.3")]
        library = next((str(path) for path in paths if path.is_file()), f"-l{name}")
        libraries.append(library)
    subprocess.run(
        [compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
         str(ROOT / "groops/extension/segmentedQrMain.cpp"), *libraries,
         "-o", str(output)], check=True, capture_output=True, text=True,
    )
    return output


def problem(E, d, A, b, *, scales=None, original=None, groups=None, queries=None):
    A = np.asarray(A, dtype=float)
    E = np.asarray(E, dtype=float).reshape((-1, A.shape[1]))
    n = A.shape[1]
    if original is None:
        original = [i >= E.shape[0] for i in range(n)]
    if groups is None:
        groups = [(0, list(range(E.shape[0])), list(range(E.shape[0], n)))]
    return {
        "E": E, "d": np.asarray(d, dtype=float), "A": A,
        "b": np.asarray(b, dtype=float), "original": original,
        "scales": np.ones(n) if scales is None else np.asarray(scales),
        "last_use": [0] * n, "groups": groups,
        "e_stage": [0] * len(E), "a_stage": [0] * len(A),
        "queries": np.eye(n) if queries is None else np.asarray(queries, dtype=float).reshape((-1, n)),
    }


def encode(p):
    n = p["A"].shape[1]
    blocked = "query_blocks" in p
    lines = ["SEGMENTED_QR_BLOCKS_V1" if blocked else "SEGMENTED_QR_V1",
             f"{n} {len(p['E'])} {len(p['A'])} {len(p['groups'])} {len(p['queries'])}" +
             (f" {len(p['query_blocks'])}" if blocked else "")]
    for i in range(n):
        lines.append(f"{i} {int(p['original'][i])} {p['scales'][i]:.17g} {p['last_use'][i]}")
    row_id = 0
    for key, rhs, stages in (("E", "d", "e_stage"), ("A", "b", "a_stage")):
        for row, target, stage in zip(p[key], p[rhs], p[stages], strict=True):
            terms = [(j, a) for j, a in enumerate(row) if a != 0]
            suffix = " ".join(f"{j} {a:.17g}" for j, a in terms)
            lines.append(f"{row_id} {stage} {target:.17g} {len(terms)} {suffix}")
            row_id += 1
    for stage, det, stochastic in p["groups"]:
        lines.append(f"{stage} {len(det)} {len(stochastic)} " + " ".join(map(str, det + stochastic)))
    for row in p["queries"]:
        terms = [(j, a) for j, a in enumerate(row) if a != 0]
        lines.append(f"{len(terms)} " + " ".join(f"{j} {a:.17g}" for j, a in terms))
    if blocked:
        lines.append(" ".join(map(str, p["query_blocks"])))
    return "\n".join(lines) + "\n"


def run(binary, p, *, error=None):
    completed = subprocess.run([str(binary)], input=encode(p), text=True, capture_output=True,
                               env={**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"})
    assert not completed.stderr
    value = json.loads(completed.stdout)
    if error is not None:
        assert completed.returncode != 0
        assert value["status"] == "failed"
        assert value["reason"] == error
        assert "step" not in value and "covariance" not in value
    else:
        assert completed.returncode == 0, value
        assert value["status"] == "complete"
    return value


def independent(p):
    E, A, d, b = p["E"], p["A"], p["d"], p["b"]
    if len(E):
        x0 = linalg.lstsq(E, d, lapack_driver="gelsd")[0]
        Z = linalg.null_space(E)
    else:
        x0, Z = np.zeros(A.shape[1]), np.eye(A.shape[1])
    if Z.shape[1]:
        Q, R = linalg.qr(A @ Z, mode="economic")
        x = x0 + Z @ linalg.solve_triangular(R, Q.T @ (b - A @ x0))
        selected = linalg.solve_triangular(R.T, (p["queries"] @ Z).T, lower=True).T
        covariance = selected @ selected.T
    else:
        x, covariance = x0, np.zeros((len(p["queries"]), len(p["queries"])))
    return x, covariance, float(np.linalg.norm(b - A @ x) ** 2)


def assert_oracle(binary, p, *, rtol=3e-11, atol=3e-12):
    got = run(binary, p)
    x, covariance, energy = independent(p)
    np.testing.assert_allclose(got["step"], x, rtol=rtol, atol=atol)
    np.testing.assert_allclose(got["covariance"], covariance, rtol=rtol, atol=atol)
    assert got["residual_energy"] == pytest.approx(energy, rel=rtol, abs=atol)
    assert got["orthogonal_residual_energy"] == pytest.approx(energy, rel=rtol, abs=atol)
    assert got["stochastic_objective"] == 0.5 * got["residual_energy"]
    recorded_energy = got["input_constant_energy"] + sum(r["constant_energy"] for r in got["row_provenance"])
    assert recorded_energy == pytest.approx(got["orthogonal_residual_energy"], rel=2e-13, abs=1e-14)
    assert got["rank_scope"] == "local_front_checks;original_chart_certificate_external"
    assert all(c["rank"]["status"] == "full" for c in got["conditionals"])
    return got


def chain(length=5, seed=7301):
    rng = np.random.default_rng(seed)
    # Grid accumulators y_i and a forcing coefficient q. y_i are auxiliary;
    # x0 and q are the original independent chart. No continuity noise exists.
    n = length + 2
    E = np.zeros((length, n))
    E[0, 0], E[0, length] = 1, -1
    for i in range(1, length):
        E[i, i], E[i, i - 1], E[i, length + 1] = 1, -1, -(0.4 + 0.1 * i)
    A = np.zeros((2 * length + 2, n))
    for i in range(length):
        A[2*i, i], A[2*i+1, i] = 0.7 + i / 10, -0.4
    A[-2, length], A[-1, length + 1] = 0.8, 1.3
    # Eliminate original x0 deterministically; then old accumulator states.
    # The last accumulator and q are stochastic. Role != coordinate kind.
    groups = [(0, [length], [])]
    groups += [(i, [i-1], []) for i in range(1, length)]
    groups += [(length, [], [length-1, length+1])]
    return problem(E, rng.normal(size=length), A, rng.normal(size=len(A)), groups=groups)


def test_nonzero_equality_rhs_map_covariance_and_energy(segmented_native_binary):
    p = problem([[1, -2, 0.3], [0, 1, -0.7]], [0.25, -0.4],
                [[1, 0, 0], [0, 2, 0], [0.5, 0, 1], [0, 0, 0]], [1, 3, -2, 2.5])
    got = assert_oracle(segmented_native_binary, p)
    assert got["equality_max_residual"] < 1e-13
    E = p["E"]
    np.testing.assert_allclose(E @ np.asarray(got["covariance"]) @ E.T, 0, atol=1e-15)
    assert got["residual_energy"] >= 2.5**2


@pytest.mark.parametrize("seed", [7301, 7302, 7303, 7304])
def test_sparse_chain_mixed_pivot_roles(segmented_native_binary, seed):
    p = chain(seed=seed)
    got = assert_oracle(segmented_native_binary, p)
    assert got["max_front_columns"] < len(p["original"])
    assert [c["kind"] for c in got["conditionals"]].count("deterministic") == 5
    # Original x0 has a deterministic conditional, auxiliary terminal y is random.
    assert got["conditionals"][0]["pivot_ids"] == [5]
    assert got["conditionals"][-1]["pivot_ids"] == [4, 6]


def test_selected_cross_covariance_and_zero_noise_query(segmented_native_binary):
    p = chain()
    Q = np.vstack((p["E"][2], np.eye(7)[[0, 4, 6]], np.arange(7)))
    p["queries"] = Q
    got = assert_oracle(segmented_native_binary, p)
    assert np.asarray(got["covariance"]).shape == (5, 5)
    np.testing.assert_allclose(np.asarray(got["covariance"])[0], 0, atol=1e-14)
    assert abs(got["covariance"][1][2]) > 0


def test_no_queries_does_not_form_full_covariance(segmented_native_binary):
    p = chain()
    p["queries"] = np.empty((0, 7))
    got = run(segmented_native_binary, p)
    assert got["covariance"] == []


def test_unit_changes_row_order_and_grouping(segmented_native_binary):
    p = chain()
    base = assert_oracle(segmented_native_binary, p)
    # x_native=unit*x_new; queries continue to ask for old physical outputs.
    units = np.array([1e3, 1e-3, 1e2, 0.1, 10, 1e6, 1e-6])
    changed = copy.deepcopy(p)
    changed["E"] *= units
    changed["A"] *= units
    changed["queries"] *= units
    changed["scales"] /= units
    changed["E"] = changed["E"][::-1]
    changed["d"] = changed["d"][::-1]
    changed["A"] = changed["A"][::-1]
    changed["b"] = changed["b"][::-1]
    got = run(segmented_native_binary, changed)
    np.testing.assert_allclose(np.asarray(got["step"]) * units, base["step"], rtol=2e-12, atol=2e-12)
    np.testing.assert_allclose(got["covariance"], base["covariance"], rtol=2e-12, atol=2e-12)
    # One all-variable front versus sparse elimination of the identical rows.
    together = copy.deepcopy(p)
    together["groups"] = [(5, [5, 0, 1, 2, 3], [4, 6])]
    got = assert_oracle(segmented_native_binary, together)
    np.testing.assert_allclose(got["step"], base["step"], rtol=2e-12, atol=2e-12)
    np.testing.assert_allclose(got["covariance"], base["covariance"], rtol=2e-12, atol=2e-12)


def test_local_global_nuisance_elimination_equivalent(segmented_native_binary):
    rng = np.random.default_rng(912)
    A = rng.normal(size=(30, 7))
    p = problem([], [], A, rng.normal(size=30), groups=[(0, [], [0, 1]), (1, [], [2, 3]), (2, [], [4, 5, 6])])
    local = assert_oracle(segmented_native_binary, p)
    p["groups"] = [(2, [], list(range(7)))]
    global_ = assert_oracle(segmented_native_binary, p)
    np.testing.assert_allclose(local["covariance"], global_["covariance"], atol=1e-14)
    np.testing.assert_allclose(local["step"], global_["step"], atol=1e-14)


def test_deterministic_only_system_has_zero_covariance(segmented_native_binary):
    p = problem([[1, 0.2], [0.3, 2]], [1, -2], np.empty((0, 2)), [], queries=np.eye(2))
    got = assert_oracle(segmented_native_binary, p)
    assert got["covariance"] == [[0, 0], [0, 0]]


@pytest.mark.parametrize("small,status", [(0.0, "deficient"), (1e-16, "deficient"), (2e-15, "unresolved")])
def test_stochastic_rank_classification_no_covariance(segmented_native_binary, small, status):
    p = problem([], [], [[1, 0], [0, small]], [1, 1])
    run(segmented_native_binary, p, error=f"stochastic_front_rank_{status}")


@pytest.mark.parametrize("small", [0.0, 1e-16, 2e-15])
def test_constraint_pivot_rank_never_drops_direction(segmented_native_binary, small):
    # Full equality row normalization must not hide a weak selected pivot.
    p = problem([[1, 0, 0], [0, small, 1]], [0, 0], [[0, 0, 1]], [1])
    run(segmented_native_binary, p, error="constraint_rank_inconsistent")


def test_full_rank_above_uncertainty_band(segmented_native_binary):
    p = problem([], [], [[1, 0], [0, 1e-13]], [1, 1e-13])
    got = run(segmented_native_binary, p)
    np.testing.assert_allclose(got["step"], [1, 1], rtol=1e-14)
    assert got["covariance"][1][1] == pytest.approx(1e26)


@pytest.mark.parametrize("mutation,error", [
    (lambda p: p.update(original=[True] * 7), "constraint_rank_inconsistent"),
    (lambda p: p["groups"].pop(), "invalid_schedule"),
    (lambda p: p["groups"].append((6, [], [6])), "invalid_schedule"),
    (lambda p: p["scales"].__setitem__(0, 0), "invalid_scale"),
    (lambda p: p["scales"].__setitem__(0, -1), "invalid_scale"),
    (lambda p: p["last_use"].__setitem__(5, 1), "chronology_violation"),
    (lambda p: p["a_stage"].__setitem__(0, 1), "chronology_violation"),
    (lambda p: p["groups"].__setitem__(2, (0, [1], [])), "chronology_violation"),
])
def test_fail_closed_metadata(segmented_native_binary, mutation, error):
    p = chain()
    mutation(p)
    run(segmented_native_binary, p, error=error)


def test_unused_stochastic_parameter_rejected(segmented_native_binary):
    p = problem([], [], [[1, 0]], [2])
    run(segmented_native_binary, p, error="stochastic_front_rank_deficient")


def test_constraint_touches_stochastic_pivot_rejected(segmented_native_binary):
    p = problem([[1, 1, 0]], [0], [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [1, 2, 3],
                groups=[(0, [], [1]), (1, [0], [2])])
    run(segmented_native_binary, p, error="unsupported_pivot_schedule")


def test_row_provenance_and_chronology(segmented_native_binary):
    p = chain()
    got = run(segmented_native_binary, p)
    seen = set()
    for conditional in got["conditionals"]:
        seen.update(conditional["row_ids"])
        assert conditional["row_ids"] == sorted(set(conditional["row_ids"]))
    initial = set(range(len(p["E"]) + len(p["A"])))
    known = set(initial)
    for record in got["row_provenance"]:
        assert set(record["source_row_ids"]) <= known
        assert not (set(record["row_ids"]) & known)
        known.update(record["row_ids"])
        seen.update(record["source_row_ids"])
    assert initial <= seen
    assert seen <= known
    assert [c["stage"] for c in got["conditionals"]] == sorted(c["stage"] for c in got["conditionals"])


@pytest.mark.parametrize("text", ["", "BAD\n", "SEGMENTED_QR_V1\n-1 0 0 0 0\n"])
def test_malformed_protocol_fails_without_covariance(segmented_native_binary, text):
    proc = subprocess.run([str(segmented_native_binary)], input=text, text=True, capture_output=True)
    assert proc.returncode != 0
    result = json.loads(proc.stdout)
    assert result["status"] == "failed" and result["reason"] == "invalid_input"
    assert "covariance" not in result


def test_duplicate_row_ids_rejected(segmented_native_binary):
    text = encode(chain()).splitlines()
    # Metadata7lines + protocol/header2: equality rows start at9.
    text[10] = "0 " + text[10].split(" ", 1)[1]
    proc = subprocess.run([str(segmented_native_binary)], input="\n".join(text), text=True, capture_output=True)
    assert proc.returncode != 0
    assert json.loads(proc.stdout)["reason"] == "invalid_rows"


def test_nonzero_coefficient_underflow_fails_closed(segmented_native_binary):
    p = problem([], [], [[1e-200]], [1], scales=[1e-200])
    run(segmented_native_binary, p, error="arithmetic_underflow")


def test_front_provenance_is_a_linear_size_dag(segmented_native_binary):
    p = chain(length=80)
    p["queries"] = np.eye(82)[[0, 40, 79, 81]]
    got = assert_oracle(segmented_native_binary, p, rtol=3e-9, atol=1e-10)
    references = sum(len(c["row_ids"]) for c in got["conditionals"])
    references += sum(len(c["source_row_ids"]) + len(c["row_ids"]) for c in got["row_provenance"])
    assert references < 30 * len(p["original"])
    assert got["max_front_columns"] <= 3


def test_trailing_exact_constraints_are_forwarded_without_noise(segmented_native_binary):
    p = problem([[1, 1, 2, 0], [1, -1, 0, 3]], [0.3, -0.6],
                [[1, 0, 0, 0], [2, 0, 0, 0], [3, 0, 0, 0],
                 [4, 0, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
                [1, 2, 4, 5, 0.5, -0.2],
                groups=[(0, [0], []), (1, [1], [2, 3])])
    got = assert_oracle(segmented_native_binary, p)
    assert any(record["ledger"] == "equality" for record in got["row_provenance"])
    np.testing.assert_allclose(p["E"] @ np.asarray(got["covariance"]), 0, atol=2e-15)


def test_multivariate_deterministic_and_stochastic_fronts(segmented_native_binary):
    rng = np.random.default_rng(431)
    E = np.hstack((np.eye(3), rng.normal(size=(3, 4))))
    A = rng.normal(size=(15, 7))
    p = problem(E, rng.normal(size=3), A, rng.normal(size=15),
                groups=[(0, [0, 1], []), (1, [2], [3, 4]), (2, [], [5, 6])])
    got = assert_oracle(segmented_native_binary, p)
    assert [len(c["pivot_ids"]) for c in got["conditionals"]] == [2, 1, 2, 2]


def test_grouped_six_state_and_joint_cross_block_covariance(segmented_native_binary):
    p = chain(length=16)
    rng = np.random.default_rng(119)
    # Two selected six-state maps and one joint12-row cross-segment request.
    grid = rng.normal(size=(12, 18))
    p["queries"] = np.vstack((grid[:6], grid[6:], grid))
    reference = assert_oracle(segmented_native_binary, p)
    p["query_blocks"] = [6, 6, 12]
    result = run(segmented_native_binary, p)
    assert result["covariance"] == []
    assert result["max_covariance_query_block"] == 12
    assert result["covariance_scratch_shape"] == [18, 12]
    first = 0
    for block, count in zip(result["covariance_blocks"], [6, 6, 12], strict=True):
        assert block["query_start"] == first and block["query_count"] == count
        expected = np.asarray(reference["covariance"])[first:first+count, first:first+count]
        np.testing.assert_allclose(block["covariance"], expected, rtol=1e-13, atol=1e-13)
        first += count
    joint = np.asarray(result["covariance_blocks"][-1]["covariance"])
    np.testing.assert_allclose(joint[:6, :6], result["covariance_blocks"][0]["covariance"])
    np.testing.assert_allclose(joint[6:, 6:], result["covariance_blocks"][1]["covariance"])
    assert np.linalg.norm(joint[:6, 6:]) > 0


def test_covariance_blocks_preserve_zero_noise_and_unit_scaling(segmented_native_binary):
    p = chain()
    p["queries"] = np.vstack((p["E"][:3], np.eye(7)[[0, 3, 6]]))
    p["query_blocks"] = [3, 3]
    original = run(segmented_native_binary, p)
    np.testing.assert_allclose(original["covariance_blocks"][0]["covariance"], 0, atol=1e-25)
    unit = np.array([1e-6, 1e6, 0.3, 3., 0.5, 1e3, 1e-3])
    p["A"] *= unit
    p["E"] *= unit
    p["queries"] *= unit
    p["scales"] /= unit
    changed = run(segmented_native_binary, p)
    for a, b in zip(original["covariance_blocks"], changed["covariance_blocks"], strict=True):
        np.testing.assert_allclose(a["covariance"], b["covariance"], rtol=2e-12, atol=2e-13)


def test_covariance_blocks_do_not_cache_damped_factor(segmented_native_binary):
    p = chain()
    p["queries"] = np.eye(7)[[0, 4, 6]]
    p["query_blocks"] = [3]
    base = run(segmented_native_binary, p)
    damped = copy.deepcopy(p)
    damping = np.zeros((2, 7))
    damping[0, 5], damping[1, 6] = 1e3, 1e3
    damped["A"] = np.vstack((p["A"], damping))
    damped["b"] = np.r_[p["b"], [0, 0]]
    damped["a_stage"] += [0, 0]
    other = run(segmented_native_binary, damped)
    assert not np.allclose(base["covariance_blocks"][0]["covariance"], other["covariance_blocks"][0]["covariance"])
    fresh = run(segmented_native_binary, p)
    assert fresh["covariance_blocks"] == base["covariance_blocks"]


@pytest.mark.parametrize("blocks", [[0, 7], [3], [8], [4, 4], []])
def test_invalid_covariance_block_coverage_fails_closed(segmented_native_binary, blocks):
    p = chain()
    p["query_blocks"] = blocks
    run(segmented_native_binary, p, error="invalid_query_blocks")


def test_empty_covariance_block_request(segmented_native_binary):
    p = chain()
    p["queries"] = np.empty((0, 7))
    p["query_blocks"] = []
    result = run(segmented_native_binary, p)
    assert result["covariance"] == [] and result["covariance_blocks"] == []
    assert result["max_covariance_query_block"] == 0


def test_many_blocks_never_allocate_joint_covariance(segmented_native_binary):
    p = chain()
    p["queries"] = np.tile(np.eye(7)[[0, 4, 6]], (100, 1))
    p["query_blocks"] = [3]*100
    result = run(segmented_native_binary, p)
    assert result["covariance"] == []
    assert result["covariance_scratch_shape"] == [7, 3]
    assert len(result["covariance_blocks"]) == 100
    for block in result["covariance_blocks"]:
        assert np.asarray(block["covariance"]).shape == (3, 3)


def test_small_gtsam42_constrained_qr_map_and_covariance_oracle(segmented_native_binary):
    # GTSAM is an independent, well-scaled small-problem oracle only. Its
    # internal coefficient thresholds are not used by the production solver.
    import importlib.metadata
    import gtsam
    assert importlib.metadata.version("gtsam") == "4.2"
    p = problem([[1, -2, 0.3], [0, 1, -0.7]], [0.25, -0.4],
                [[1, 0, 0], [0, 2, 0], [0.5, 0, 1], [0, 0, 0]], [1, 3, -2, 2.5])
    native = assert_oracle(segmented_native_binary, p)
    graph = gtsam.GaussianFactorGraph()
    noise = gtsam.noiseModel.Constrained.MixedSigmas(1., np.r_[np.zeros(2), np.ones(4)])
    graph.add(gtsam.JacobianFactor(0, np.vstack((p["E"], p["A"])), np.r_[p["d"], p["b"]], noise))
    conditional = graph.eliminateSequential().at(0)
    mean = linalg.solve_triangular(conditional.R(), conditional.d())
    square_root = linalg.solve_triangular(conditional.R(), np.diag(conditional.get_model().sigmas()))
    covariance = square_root @ square_root.T
    posterior_std = np.sqrt(np.diag(covariance))
    assert np.max(np.abs(np.asarray(native["step"]) - mean) / posterior_std) < 1e-7
    assert np.linalg.norm(np.asarray(native["covariance"]) - covariance) / np.linalg.norm(covariance) < 1e-8
