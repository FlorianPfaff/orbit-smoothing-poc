"""Independent high-precision checks of the actual opt-in interpolation helper."""
from decimal import Decimal as D, localcontext
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "groops/extension"


@pytest.fixture(scope="module")
def arithmetic(tmp_path_factory):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.fail("The query arithmetic gate requires a C++ compiler")
    output = tmp_path_factory.mktemp("twofold-query")
    executable = output / "probe"
    subprocess.run([compiler, "-std=c++17", "-O2", "-fno-fast-math", "-ffp-contract=off",
                    "-I", str(EXT), str(ROOT / "tests/fixtures/twofold_interpolation_probe.cpp"),
                    "-o", str(executable)], check=True, capture_output=True, text=True)
    result = subprocess.run([str(executable)], check=True, capture_output=True, text=True, timeout=10)
    records = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        records[tuple(map(int, fields[:3])) + (D(fields[3]),)] = list(map(D, fields[4:]))
    return records


def reference(boundary, derivative, offset):
    """Different implementation: Decimal product polynomials in absolute seconds."""
    with localcontext() as context:
        context.prec = 100
        nodes = []
        for k in range(8):
            if boundary:
                fraction = 1. + (k-4)*30./86400. if k < 4 else (k-4)*30./86400.
                nodes.append((D.from_float(fraction) - (1 if k < 4 else 0)) * 86400)
            else:
                nodes.append(D.from_float(k*30./86400.) * 86400)
        query = (D(0) if boundary else D.from_float(47./86400.)*86400) + offset
        total = D(0)
        for k, node in enumerate(nodes):
            coefficients = [D(1)]
            denominator = D(1)
            for j, other in enumerate(nodes):
                if j == k:
                    continue
                denominator *= node-other
                updated = [D(0)] * (len(coefficients)+1)
                for power, coefficient in enumerate(coefficients):
                    updated[power] -= other*coefficient
                    updated[power+1] += coefficient
                coefficients = updated
            for _ in range(derivative):
                coefficients = [D(power)*coefficients[power] for power in range(1, len(coefficients))]
            value = D(0)
            for coefficient in reversed(coefficients):
                value = value*query + coefficient
            t = k*30.
            total += D.from_float(6871000.125 + 3000*t + .0625*t*t)*value/denominator
        return total


def test_complete_values_derivatives_and_native_split_match_decimal(arithmetic):
    with localcontext() as context:
        context.prec = 100
        for (boundary, derivative, anchor, offset), values in arithmetic.items():
            high, low, rounded, remainder, _, _, part_high, part_low = values
            expected = reference(boundary, derivative, offset)
            assert abs(high+low-expected) < D("1e-22"), (boundary, derivative, anchor, offset)
            assert abs(rounded+remainder-expected) < D("1e-22"), (boundary, derivative, anchor, offset)
            assert abs(part_high+part_low-(1 if derivative == 0 else 0)) < D("1e-31")


def test_sub_long_double_query_shift_corrects_measured_legacy_wrong_sign(arithmetic):
    with localcontext() as context:
        context.prec = 100
        base = arithmetic[(0, 0, 4, D(0))]
        offset = next(key[3] for key in arithmetic if key[:3] == (0, 0, 4) and 0 < key[3] < D("1e-17"))
        shifted = arithmetic[(0, 0, 4, offset)]
        truth = reference(0, 0, offset)-reference(0, 0, D(0))
        old_shift = (shifted[4]-base[4])+(shifted[5]-base[5])
        new_shift = (shifted[0]-base[0])+(shifted[1]-base[1])
        assert truth > 0
        assert old_shift < 0  # The archived arithmetic loses and reverses this query change.
        assert abs(old_shift-truth) > abs(truth)
        assert abs(new_shift-truth) / abs(truth) < D("1e-9")


def test_anchor_modes_preserve_same_polynomial(arithmetic):
    with localcontext() as context:
        context.prec = 100
        for (boundary, derivative, anchor, offset), values in arithmetic.items():
            first = arithmetic[(boundary, derivative, 0, offset)]
            assert abs(values[0]+values[1]-first[0]-first[1]) < D("1e-22")


def load_patcher():
    spec = importlib.util.spec_from_file_location("query_precision_test", EXT / "queryPrecision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_installer_only_replaces_arithmetic_and_is_idempotent(tmp_path):
    (tmp_path / "base").mkdir()
    (tmp_path / "misc/orbitPoc").mkdir(parents=True)
    before = "legacy and exact-node shortcuts\nif(continuousQuery && !isLeastSquares) {\n"
    after = "        continue;\n}\nlegacy coefficients and adjoint window selection\n"
    old = """        std::vector<long double> nodes(count), weights(count);
// offsetAt(i) ORBIT_POC_ANCHORED_LAGRANGE_V31 coordinateRemainders
if(!adjoint) old_forward(); else old_adjoint(weights[k]*A(rowsPerEpoch*i+row,col));
"""
    path = tmp_path / "base/polynomial.cpp"
    path.write_text(before+old+after)
    patcher = load_patcher()
    patcher.apply(tmp_path)
    first = path.read_bytes()
    patcher.apply(tmp_path)
    assert path.read_bytes() == first
    text = first.decode()
    assert text.startswith(patcher.INCLUDE+before)
    assert text.endswith(after)
    assert "offsetAt(i),sampling" in text
    assert "twofoldInterpolationWeights(nodes,derivative,sampling)" in text
    assert "B(rowsPerEpoch*(idx+k)+row,col)+=" in text
    assert "value-orbitPocQr::TwofoldGeometry(B(" in text
    assert (tmp_path / "misc/orbitPoc/twofoldInterpolation.h").read_bytes() == (EXT / "twofoldInterpolation.h").read_bytes()


def test_installer_rejects_incomplete_prior_stage_before_writing(tmp_path):
    (tmp_path / "base").mkdir()
    path = tmp_path / "base/polynomial.cpp"
    path.write_text("        std::vector<long double> nodes(count), weights(count);\n        continue;")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="complete prior QR"):
        load_patcher().apply(tmp_path)
    assert path.read_bytes() == before
    assert not (tmp_path / "misc").exists()


def test_query_precision_is_explicit_and_does_not_import_gnss_range():
    helper = (EXT / "twofoldInterpolation.h").read_text()
    assert '#include "twofoldGeometry.h"' in helper
    assert "gnssRangeResidual" not in helper
    assert 'queryInterpolationPrecisionVersion="twofold_query_weights_v1"' in helper
    assert "twofold_query_weights_v1" in (EXT / "scaledRowQr.h").read_text()
    installer = (EXT / "native_row_qr.py").read_text()
    assert installer.index("position_remainder(source)") < installer.index("query_precision(source)")
