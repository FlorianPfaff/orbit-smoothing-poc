"""Independent Decimal oracles for the actual native light-time query helpers."""
from decimal import Decimal as D, localcontext
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "groops/extension"
C = D(299792458)


@pytest.fixture
def native():
    path = os.environ.get("ORBIT_POC_CORRECTNESS_NATIVE")
    if not path:
        pytest.skip("ORBIT_POC_CORRECTNESS_NATIVE must select the separate correctness build")
    return path


def run(native, directory, rows):
    directory.mkdir()
    rows = np.asarray([list(row) + [0.] * (7 - len(row)) for row in rows], dtype=float)
    source = directory / "rows.txt"
    np.savetxt(source, rows, fmt="%.17g", comments="",
               header=f"groops matrix version=20200123\nMatrix( {len(rows)} x 7 )")
    root = ET.Element("groops")
    program = ET.SubElement(ET.SubElement(root, "program"), "OrbitPocQrSolve")
    output = directory / "result.json"
    for key, value in {"inputfileRows": source, "outputfileSolution": output,
                       "outputPrefix": directory / "qr", "lightTimePrecisionFixture": 1}.items():
        ET.SubElement(program, key).text = str(value)
    config = directory / "fixture.xml"
    ET.ElementTree(root).write(config, encoding="utf-8", xml_declaration=True)
    process = subprocess.run([native, str(config)], capture_output=True, text=True, timeout=30,
                             env=dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1"))
    return process, output


def success(native, directory, rows):
    process, output = run(native, directory, rows)
    assert process.returncode == 0, process.stdout + process.stderr
    return json.loads(output.read_text())["cases"]


def pair(record, name):
    return D(record[name + "_high"]) + D(record[name + "_low"])


def exact_query(row):
    return D.from_float(float(row[3])) + sum((D.from_float(float(part)) for part in row[4:]), D(0)) / C


def grid_shift(record, row, prefix="rounded"):
    return ((D(record[prefix + "_day"]) - D.from_float(float(row[1]))) +
            (D(record[prefix + "_fraction"]) - D.from_float(float(row[2])))) * 86400


def measured_rows():
    # Actual D03 generation4, observation(0,24,8,4), baseline/full-step operands.
    # Preserved analysis04 SHA0d8f32c7bb1729d5507515f7bc47bd6000ef297cfc39fb111646ac36d567da1e.
    distances = [
        "20975235.539833105424615985882288119246994425998156762477734167560302312727227302957544452510774135589599609375",
        "20975235.539833105424616014501657053198288699823259089079593558754680861222485788175617926754057407379150390625",
    ]
    clocks = ["3.3837027908881377164014721790896711439700084156356751918792724609375E-7",
              "3.383702790888210243597580828556203869084129109978675842285156250E-7"]
    with localcontext() as context:
        context.prec = 120
        rows = []
        for distance, clock in zip(distances, clocks):
            parts = []
            remainder = D(distance)
            for _ in range(3):
                parts.append(float(remainder))
                remainder -= D.from_float(parts[-1])
            assert remainder == 0  # All recorded expansion bits survive the matrix input.
            rows.append([0., 60424., float("0.0027777777777782119983385200612246990203857421875"), float(clock), *parts])
        return rows


def test_native_measured_clock_step_preserves_duration_low_part(native, tmp_path):
    rows = measured_rows()
    records = success(native, tmp_path / "measured", rows)
    with localcontext() as context:
        context.prec = 120
        exact = [exact_query(row) for row in rows]
        precise = [-grid_shift(record, row) - D(record["offset_rounded"]) for record, row in zip(records, rows)]
        old = [-grid_shift(record, row, "legacy") - D(record["legacy_offset"]) for record, row in zip(records, rows)]
        expected = exact[1] - exact[0]
        new_error = abs(precise[1] - precise[0] - expected)
        old_error = abs(old[1] - old[0] - expected)
        assert expected > 0 and old_error > D("1e-22")
        assert new_error < D("1e-30")
        assert new_error < old_error * D("1e-8")


@pytest.mark.parametrize("fraction", [0., np.nextafter(1., 0.), 1., .5])
def test_native_split_time_boundaries_keep_same_query(fraction, native, tmp_path):
    rows = [[0., 60424., fraction, clock, 20975235.539833106, -7.2e-10]
            for clock in [0., -3.38e-7, 3.38e-7, -1e-19, 1e-19]]
    records = success(native, tmp_path / "boundary", rows)
    with localcontext() as context:
        context.prec = 120
        for record, row in zip(records, rows):
            expected = -exact_query(row) - grid_shift(record, row)
            assert abs(pair(record, "offset") - expected) < D("1e-32")
            assert abs(D(record["offset_rounded"]) - expected) < D("1e-27")
            assert abs(D(record["offset_rounded"])) < D("1e-8")
            assert abs(D(record["rounded_day"]) - D(60424)) <= 1


def nonlinear_oracle(clock):
    """Solve the moving-endpoint Euclidean light-time equation in120 digits."""
    clock = D.from_float(float(clock))
    r0 = list(map(D, ["6871000.125", "-1200300.375", "2450060.5"]))
    t0 = list(map(D, ["15400000.75", "21300000.125", "11600000.5"]))
    vr, vt = list(map(D, [100, 7400, 20])), list(map(D, [-700, 2800, 1000]))
    receiver = [r - v * clock for r, v in zip(r0, vr)]
    distance = D(20200000)
    for _ in range(40):
        transmitter = [t - v * (clock + distance / C) for t, v in zip(t0, vt)]
        updated = sum((r - t) ** 2 for r, t in zip(receiver, transmitter)).sqrt()
        if abs(updated - distance) < D("1e-90"):
            return updated + C * clock
        distance = updated
    raise AssertionError("Independent light-time oracle did not converge")


@pytest.mark.parametrize("fraction", [0., .002777777777778212, .5])
def test_native_nonlinear_clock_perturbations_match_independent_geometry(fraction, native, tmp_path):
    center = float(measured_rows()[0][3])
    clocks = [center + shift for shift in [-2e-20, -1e-20, 0., 1e-20, 2e-20]]
    rows = [[1., 60424., fraction, clock, 0., 0.] for clock in clocks]
    records = success(native, tmp_path / "nonlinear", rows)
    with localcontext() as context:
        context.prec = 120
        truth = [nonlinear_oracle(clock) for clock in clocks]
        precise = [pair(record, "precise_model") for record in records]
        legacy = [pair(record, "legacy_model") for record in records]
        new_errors = [abs((value - precise[2]) - (expected - truth[2])) for value, expected in zip(precise, truth)]
        old_errors = [abs((value - legacy[2]) - (expected - truth[2])) for value, expected in zip(legacy, truth)]
        assert max(new_errors) < D("1e-22")
        assert max(old_errors) > D("1e-19")
        assert max(new_errors) < max(old_errors) * D("1e-4")
        assert all(1 <= int(record["precise_iterations"]) <= 10 for record in records)


def test_native_non_nearest_rounding_is_rejected(native, tmp_path):
    process, _ = run(native, tmp_path / "rounding", [[2., 60424., .5, 1e-7, 0., 0.]])
    assert process.returncode != 0
    assert "requires round-to-nearest" in process.stdout + process.stderr


def test_light_time_upgrade_preserves_limits_legacy_api_and_version():
    helper = (EXT / "gnssRangeResidual.h").read_text()
    installer = (EXT / "positionRemainder.py").read_text()
    assert "timeRemainder(const Time &nominal,long double clockSeconds" in helper
    assert "inline long double preciseDistance(" in helper
    assert "preciseDistanceExpansion(a,aLow,b,bLow).rounded()" in helper
    assert "const orbitPocQr::TwofoldGeometry &travel" in installer
    assert "for(UInt i=0;i<10;i++)" in installer
    assert "preciseDistance(posTrans,transLow,old,oldLow)<1e-10L" in installer
    assert "twofold_duration_to_relative_query_v1" in (EXT / "scaledRowQr.h").read_text()


def test_install_rejects_a_preexisting_old_generated_query(tmp_path):
    (tmp_path / "gnss").mkdir()
    path = tmp_path / "gnss/gnssObservation.cpp"
    path.write_text("// ORBIT_POC_PRECISE_POSITION_REMAINDER_V31_PAIR2\nold query")
    sys.path.insert(0, str(EXT))
    try:
        spec = importlib.util.spec_from_file_location("light_time_installer", EXT / "positionRemainder.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with pytest.raises(ValueError, match="twofold light time requires a fresh"):
            module.require_install_state(tmp_path)
    finally:
        sys.path.remove(str(EXT))
    assert path.read_text().endswith("old query")
