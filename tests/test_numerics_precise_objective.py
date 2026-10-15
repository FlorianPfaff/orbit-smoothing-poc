"""Independent Decimal checks of the native complete-residual objective ledger."""
from decimal import Decimal, localcontext
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import numpy as np
import pytest


@pytest.fixture
def native():
    path = os.environ.get("ORBIT_POC_CORRECTNESS_NATIVE")
    if not path:
        pytest.skip("ORBIT_POC_CORRECTNESS_NATIVE must select the separate correctness build")
    return path


def problem():
    rows = np.array([
        [1., -2., 1., 1., 0.], [2., .5, -1., -1., 0.],
        [3., 1., 2., 2., 0.], [0., 0., .5, .5, 1.],
        [0., 0., -.5, -.5, 1.], [0., 0., .25, .25, 2.],
        [0., 0., -.75, -.75, 3.],
    ])
    expansions = np.column_stack((rows[:, 2], np.zeros(7), rows[:, 3], np.zeros(7)))
    expansions[:5, 1] = [2.**-60, -2.**-59, 2.**-60, 0., -2.**-61]
    expansions[:5, 3] = expansions[:5, 1] / 4
    assert np.array_equal(expansions[:, 0] + expansions[:, 1], rows[:, 2])
    assert np.array_equal(expansions[:, 2] + expansions[:, 3], rows[:, 3])
    return rows, expansions


def oracle(expansions):
    with localcontext() as context:
        context.prec = 100
        before = [Decimal.from_float(float(row[0])) + Decimal.from_float(float(row[1]))
                  for row in expansions]
        after = [Decimal.from_float(float(row[2])) + Decimal.from_float(float(row[3]))
                 for row in expansions]
        return {
            "before": float(sum(value * value for value in before) / 2),
            "after": float(sum(value * value for value in after) / 2),
            "actual_reduction": float(sum((a - b) * (a + b) for a, b in zip(before, after)) / 2),
        }


def run_fixture(native, path, rows, expansions=None, *, failure=None, enabled=True):
    path.mkdir()
    def matrix(name, values):
        target = path / name
        np.savetxt(target, values, fmt="%.17g", comments="",
                   header=f"groops matrix version=20200123\nMatrix( {len(values)} x {values.shape[1]} )")
        return target
    root = ET.Element("groops")
    program = ET.SubElement(ET.SubElement(root, "program"), "OrbitPocQrSolve")
    values = {"inputfileRows": matrix("rows.txt", rows), "outputfileSolution": path / "result.json",
              "outputPrefix": path / "qr", "objectiveLedgerFixture": int(enabled)}
    if expansions is not None:
        values["inputfileObjectiveExpansions"] = matrix("expansions.txt", expansions)
    if failure:
        values["objectiveLedgerFailure"] = failure
    for key, value in values.items():
        ET.SubElement(program, key).text = str(value)
    config = path / "fixture.xml"
    ET.ElementTree(root).write(config, encoding="utf-8", xml_declaration=True)
    result = subprocess.run([native, str(config)], capture_output=True, text=True, timeout=30,
                            env=dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1"))
    return result, path / "result.json"


def success(native, path, rows, expansions=None):
    process, output = run_fixture(native, path, rows, expansions)
    assert process.returncode == 0, process.stdout + process.stderr
    return json.loads(output.read_text())


def assert_oracle(value, expansions):
    expected = oracle(expansions)
    assert value["before"] == expected["before"]
    assert value["after"] == expected["after"]
    assert value["actual_reduction"] == pytest.approx(expected["actual_reduction"], rel=2e-15, abs=1e-35)
    assert value["original_rows_before"] == value["original_rows_after"] == len(expansions)


def test_equal_rounded_rows_retain_nonzero_precise_reduction(native, tmp_path):
    rows, expansions = problem()
    value = success(native, tmp_path / "precise", rows, expansions)
    assert_oracle(value, expansions)
    assert value["actual_reduction"] > 0
    assert value["before"] - value["after"] == 0
    rounded = success(native, tmp_path / "rounded", rows)
    assert rounded["actual_reduction"] == 0


def test_precise_reduction_changes_sign_when_states_are_swapped(native, tmp_path):
    rows, expansions = problem()
    forward = success(native, tmp_path / "forward", rows, expansions)
    reverse = success(native, tmp_path / "reverse", rows[:, [1, 0, 3, 2, 4]], expansions[:, [2, 3, 0, 1]])
    assert reverse["actual_reduction"] == -forward["actual_reduction"]


def test_identical_precise_state_replay_is_exactly_zero(native, tmp_path):
    rows, expansions = problem()
    expansions[:, 2:] = expansions[:, :2]
    value = success(native, tmp_path / "zero", rows, expansions)
    assert_oracle(value, expansions)
    assert value["actual_reduction"] == 0


def test_precise_cost_is_invariant_to_row_order_and_group_qr_units(native, tmp_path):
    rows, expansions = problem()
    reference = success(native, tmp_path / "original", rows, expansions)
    order = np.array([6, 2, 4, 0, 5, 3, 1])
    changed = rows[order].copy()
    changed[:, 0] *= 1e-9
    changed[:, 1] *= -1e6
    value = success(native, tmp_path / "reordered", changed, expansions[order])
    for key in ("before", "after", "actual_reduction", "original_rows_before", "original_rows_after"):
        assert value[key] == reference[key]


def test_zero_low_parts_match_exact_binary64_fixture(native, tmp_path):
    rows, expansions = problem()
    expansions[:, [1, 3]] = 0
    rows[0, 3] = np.nextafter(rows[0, 2], 0)
    expansions[0, 2] = rows[0, 3]
    precise = success(native, tmp_path / "precise", rows, expansions)
    rounded = success(native, tmp_path / "rounded", rows)
    for key in ("before", "after", "actual_reduction", "original_rows_before", "original_rows_after"):
        assert precise[key] == rounded[key]


@pytest.mark.parametrize("defect,message", [
    ("target", "Precise original observation and QR target disagree"),
    ("rows", "Objective expansion fixture dimensions differ"),
    ("columns", "Objective expansion fixture dimensions differ"),
    ("prior", "keeps native binary64 constraint targets"),
    ("nonfixture", "require the original-objective fixture"),
])
def test_invalid_precise_rows_fail_without_an_objective(native, tmp_path, defect, message):
    rows, expansions = problem()
    if defect == "target":
        expansions[0, 0] += 1
    elif defect == "rows":
        expansions = expansions[:-1]
    elif defect == "columns":
        expansions = expansions[:, :3]
    elif defect == "prior":
        expansions[-1, 1] = 2.**-60
    process, output = run_fixture(native, tmp_path / defect, rows, expansions, enabled=defect != "nonfixture")
    assert process.returncode != 0
    assert not output.exists()
    assert message in process.stdout + process.stderr


@pytest.mark.parametrize("failure,message", [
    ("missing_capture_cost_only", "Group QR lacks its original objective block"),
    ("misclassified_prior_cost_only", "Original objective row accounting differs"),
])
def test_precise_ledger_keeps_missing_support_failures(native, tmp_path, failure, message):
    rows, expansions = problem()
    process, output = run_fixture(native, tmp_path / failure, rows, expansions, failure=failure)
    assert process.returncode != 0
    assert not output.exists()
    assert message in process.stdout + process.stderr
