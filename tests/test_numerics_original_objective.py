"""Original-residual nonlinear costs must not depend on nuisance QR rotations.

The hook checks are lightweight. Native arithmetic checks require an explicitly
selected correctness candidate; they never use a frozen benchmark executable.
"""
from decimal import Decimal, localcontext
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]


def _hook():
    path = ROOT / "groops/extension/native_row_qr.py"
    spec = importlib.util.spec_from_file_location("original_objective_patch", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._original_objective_hook


@pytest.mark.parametrize("prefix", ["", "// ORBIT_POC_SCALED_ROW_QR_V31\n"])
def test_original_objective_hook_precedes_empty_group_and_is_idempotent(tmp_path, prefix):
    path = tmp_path / "gnssObservation.cpp"
    path.write_text(prefix + "void GnssObservationEquation::eliminateGroupParameters(Bool removeRows)\n"
                    "{\n  try\n  {\n    if(!B.size())\n      return;\n"
                    "    const Vector tau = QR_decomposition(B);\n  }\n}\n")
    hook = _hook()
    hook(path)
    first = path.read_bytes()
    hook(path)
    assert path.read_bytes() == first
    text = first.decode()
    assert text.count("orbitPocRowQr().retainObservationResiduals") == 1
    assert text.index("orbitPocRowQr().retainObservationResiduals") < text.index("if(!B.size())")
    assert "if(orbitPocQr::enabled()) orbitPocRowQr().retainObservationResiduals" in text


def test_original_objective_hook_rejects_changed_upstream_anchor(tmp_path):
    path = tmp_path / "gnssObservation.cpp"
    path.write_text("void unrelated() {\n    if(!B.size())\n      return;\n}\n")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Pinned original-objective"):
        _hook()(path)
    assert path.read_bytes() == before


@pytest.fixture
def native():
    value = os.environ.get("ORBIT_POC_CORRECTNESS_NATIVE")
    if not value:
        pytest.skip("ORBIT_POC_CORRECTNESS_NATIVE must select the separate correctness build")
    return value


def _fixture(native, directory, rows, failure=None):
    directory.mkdir()
    np.savetxt(directory / "rows.txt", rows, fmt="%.17g", comments="",
               header=f"groops matrix version=20200123\nMatrix( {len(rows)} x 5 )")
    root = ET.Element("groops")
    program = ET.SubElement(ET.SubElement(root, "program"), "OrbitPocQrSolve")
    for key, value in {"inputfileRows": directory / "rows.txt",
                       "outputfileSolution": directory / "objective.json",
                       "outputPrefix": directory / "qr", "objectiveLedgerFixture": 1}.items():
        ET.SubElement(program, key).text = str(value)
    if failure:
        ET.SubElement(program, "objectiveLedgerFailure").text = failure
    ET.ElementTree(root).write(directory / "fixture.xml", encoding="utf-8", xml_declaration=True)
    result = subprocess.run([native, str(directory / "fixture.xml")], text=True, capture_output=True,
                            env=dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1"), timeout=30)
    if failure:
        assert result.returncode != 0
        assert not (directory / "objective.json").exists()
        return result.stdout + result.stderr
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads((directory / "objective.json").read_text())


def _rows():
    rng = np.random.default_rng(310071)
    # The first group's last original row can represent its nonzero STEC prior;
    # all five role-0 entries are captured before group QR and counted once.
    rows = np.zeros((11, 5))
    rows[:5, :2] = rng.normal(size=(5, 2))
    rows[:, 2] = [1e6, -2e6, 3e6, 1.25e6, -4.5, 7., -11., 13., 2.25, -.75, 1.125]
    rows[:, 3] = rows[:, 2]
    rows[:, 4] = [0, 0, 0, 0, 0, 1, 1, 1, 2, 3, 3]
    return rows


def _decimal_cost(rows, column):
    with localcontext() as context:
        context.prec = 80
        return float(sum(Decimal.from_float(float(x)) ** 2 for x in rows[:, column]) / 2)


def _decimal_reduction(rows):
    with localcontext() as context:
        context.prec = 80
        return float(sum((Decimal.from_float(float(a)) - Decimal.from_float(float(b))) *
                         (Decimal.from_float(float(a)) + Decimal.from_float(float(b))) / 2
                         for a, b in rows[:, 2:4]))


def test_native_original_objective_is_invariant_to_changing_group_qr_basis(native, tmp_path):
    rows = _rows()
    result = _fixture(native, tmp_path / "basis", rows)
    assert result["before"] == result["after"] == _decimal_cost(rows, 2)
    assert result["actual_reduction"] == 0
    assert result["original_rows_before"] == result["original_rows_after"] == len(rows)
    # The identical raw residuals acquire artificial energy changes when their
    # two different Householder representations are compared in float64.
    assert abs(result["transformed_basis_reduction"]) > 1e-7


def test_native_original_objective_keeps_tiny_reduction_and_all_priors_once(native, tmp_path):
    rows = _rows()
    rows[0, 3] = np.nextafter(rows[0, 2], 0.)
    rows[5, 3] += 1e-9  # B-empty observation.
    rows[8, 3] += 1e-8  # Epoch prior.
    rows[9, 3] -= 1e-8  # Global prior.
    rows[4, 3] += 1e-8  # The original group prior.
    result = _fixture(native, tmp_path / "change", rows)
    expected = _decimal_reduction(rows)
    assert result["before"] == _decimal_cost(rows, 2)
    assert result["after"] == _decimal_cost(rows, 3)
    assert result["original_rows_before"] == result["original_rows_after"] == len(rows)
    assert result["actual_reduction"] == pytest.approx(expected, rel=2e-15, abs=1e-18)
    assert abs((result["before"] - result["after"]) - expected) > 1e-5


def test_native_original_objective_row_order_and_group_units_invariance(native, tmp_path):
    rows = _rows()
    rows[0, 3] = np.nextafter(rows[0, 2], 0.)
    original = _fixture(native, tmp_path / "original", rows)
    shuffled = rows[np.random.default_rng(713).permutation(len(rows))].copy()
    shuffled[:, 0] *= 1e-9
    shuffled[:, 1] *= -1e6
    reordered = _fixture(native, tmp_path / "reordered", shuffled)
    for key in ("before", "after", "actual_reduction", "original_rows_before", "original_rows_after"):
        assert reordered[key] == original[key]


@pytest.mark.parametrize("mode", ["", "_cost_only"])
@pytest.mark.parametrize("failure,message", [
    ("missing_capture", "Group QR lacks its original objective block"),
    ("misclassified_prior", "Original objective row accounting differs"),
])
def test_native_original_objective_rejects_incomplete_ledger(native, tmp_path, mode, failure, message):
    output = _fixture(native, tmp_path / "incomplete", _rows(), failure + mode)
    assert message in output
