"""Supplemental compiled checks; separate from the frozen 106/51 suites."""
from fractions import Fraction
from pathlib import Path
import json
import os
import shutil
import subprocess
import time

from orbit_poc.segmented.tangent_export import V2, decode_stencil

ROOT = Path(__file__).resolve().parents[1]


def run_logged(argv, tmp_path, label, timeout):
    """Keep partial output and attempt status even when a command times out."""
    stdout = tmp_path / (label + ".stdout")
    stderr = tmp_path / (label + ".stderr")
    attempt = {"argv": argv, "timeout_seconds": timeout, "status": "running"}
    started = time.monotonic()
    try:
        with stdout.open("wb") as out, stderr.open("wb") as err:
            result = subprocess.run(argv, stdout=out, stderr=err, timeout=timeout)
        attempt.update(status="completed", returncode=result.returncode)
    except BaseException as error:
        attempt.update(status="failed", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        attempt["elapsed_seconds"] = time.monotonic() - started
        (tmp_path / (label + ".json")).write_text(json.dumps(attempt, indent=2) + "\n")
    output = stdout.read_text(errors="replace")
    errors = stderr.read_text(errors="replace")
    assert result.returncode == 0, output + errors
    return subprocess.CompletedProcess(argv, result.returncode, output, errors)


def compile_fixture(tmp_path, name):
    compiler = shutil.which(os.environ.get("CXX", "c++"))
    assert compiler is not None, "C++ compiler required for the supplemental native gate"
    binary = tmp_path / name
    run_logged(
        [compiler, "-std=c++17", "-O3", "-DNDEBUG", "-Wall", "-Wextra",
         "-I", str(ROOT / "groops/extension/wide_tangent/proposed/misc/orbitPoc"),
         "-I", str(ROOT / "groops/extension"),
         str(ROOT / "tests/fixtures" / (name + ".cpp")), "-o", str(binary)],
        tmp_path, name + ".compile", timeout=90,
    )
    return run_logged([str(binary)], tmp_path, name + ".run", timeout=30)


def test_wide_state_and_batch_capture(tmp_path):
    result = compile_fixture(tmp_path, "wide_interpolation_fixture")
    assert result.stdout == ""


def test_native_serializer_exact_decoder_roundtrip(tmp_path):
    result = compile_fixture(tmp_path, "wide_interpolation_export_fixture")
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(rows) == 2
    exact, anchored = [decode_stencil(row, V2, 5) for row in rows]
    assert exact.indices == (3,)
    low_state = Fraction(1) + Fraction(1, 2**80)
    assert exact.evaluate([0, 0, 0, low_state, 0]) == low_state
    assert anchored.indices == (4, 1) and anchored.anchor == 1
    assert anchored.low[0] == Fraction(1, 2**70)
    assert anchored.evaluate([0, 2, 0, 0, 3]) == Fraction(5, 2) + Fraction(1, 2**70)
