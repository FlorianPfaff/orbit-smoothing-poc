"""Default-path/installer checks and separately selected actual native pairs.

The source fixture is exact generated corrected+segmented evaluator source
(SHA256 recorded in the test), not a replica of its control flow. Native pairs
require a separately built candidate; offline tests do not certify a fit.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "groops/extension"
FIXTURE = ROOT / "tests/fixtures/variational_memory_evaluator.cpp"
FIXTURE_SHA256 = "78353a18de1a8795a470316f02430215a102e5d20bc7ff6e772d96c415339c0c"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = _load(EXT / "native_variational_memory.py", "variational_memory_installer")


def _tree(tmp_path):
    root = tmp_path / "native"
    path = root / installer.PROGRAM
    path.parent.mkdir(parents=True)
    path.write_bytes(FIXTURE.read_bytes())
    return root


def test_installer_default_branch_is_original_evaluator(tmp_path):
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == FIXTURE_SHA256
    root = _tree(tmp_path)
    result = installer.apply(root)
    actual = (root / installer.PROGRAM).read_text()
    original = FIXTURE.read_text()
    start = "    auto equation=model.integrateArc(arc.times.front(),arc.times.back(),TRUE,TRUE);"
    stop = "    std::vector<Time> outputTimes=equation.times;"
    expected = original[original.index(start):original.index(stop)]
    expected = expected.replace("    auto equation=model.integrateArc", "    equation=model.integrateArc")
    expected = expected.replace("    Vector x(count);", "    x=Vector(count);")
    expected = expected.replace("    Matrix position=equation.pos0, velocity=equation.vel0;\n    matMult",
                                "    position=equation.pos0; velocity=equation.vel0;\n    matMult")
    assert actual.count(expected) == 1
    assert actual[actual.index(stop):] == original[original.index(stop):]
    assert result["default"] == "0"
    assert result["scope"] == "fixed_parameter_evaluator_only_not_GNSS_profile"
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert installer.apply(root) == result
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("mutation", ["anchor", "missing_segmented", "partial", "header", "symlink"])
def test_installer_rejects_before_any_write(tmp_path, mutation):
    root = _tree(tmp_path)
    path = root / installer.PROGRAM
    if mutation == "anchor":
        path.write_text(path.read_text().replace("    Vector x(count);", "    Vector x(count,0.);"))
    elif mutation == "missing_segmented":
        path.write_bytes((EXT / "orbitPocEvaluateVariational.cpp").read_bytes())
    elif mutation == "partial":
        path.write_text("// " + installer.MARKER + "\n" + path.read_text())
    elif mutation == "header":
        header = root / installer.HEADER
        header.parent.mkdir(parents=True)
        header.write_text("unattributed")
    elif mutation == "symlink":
        target = tmp_path / "external.cpp"
        path.rename(target)
        path.symlink_to(target)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises(ValueError):
        installer.apply(root)
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("changed", [installer.PROGRAM, installer.HEADER, installer.MANIFEST])
def test_installer_reentry_rejects_changed_identity(tmp_path, changed):
    root = _tree(tmp_path)
    installer.apply(root)
    path = root / changed
    if changed == installer.MANIFEST:
        data = json.loads(path.read_text())
        data["installer_inputs"]["blockedVariationalEvaluation.h"] = "0" * 64
        path.write_text(json.dumps(data))
    else:
        path.write_bytes(path.read_bytes() + b"\n// changed\n")
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises(ValueError):
        installer.apply(root)
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_installer_accepts_identical_base_copied_header(tmp_path):
    root = _tree(tmp_path)
    header = root / installer.HEADER
    header.parent.mkdir(parents=True)
    header.write_bytes((EXT / "blockedVariationalEvaluation.h").read_bytes())
    assert installer.apply(root)["installed_files"][installer.HEADER] == hashlib.sha256(header.read_bytes()).hexdigest()


def test_current_native_api_syntax(tmp_path):
    """Opt-in real native headers; never substitute an approximate Matrix API."""
    source = os.environ.get("ORBIT_POC_VARIATIONAL_NATIVE_SOURCE")
    if not source:
        pytest.skip("set ORBIT_POC_VARIATIONAL_NATIVE_SOURCE for the real-header compile check")
    source = Path(source)
    probe = tmp_path / "probe.cpp"
    probe.write_text('#include "misc/observation/variationalEquationFromFile.h"\n'
                     '#include "blockedVariationalEvaluation.h"\n'
                     'void probe(VariationalEquationFromFile &model,const std::vector<Time>& times)\n'
                     '{auto result=OrbitPoc::evaluateVariationalBlocks(model,times,64,FileName(),FileName(),FileName());}\n')
    command = [os.environ.get("CXX", "c++"), "-std=c++17", "-fsyntax-only", "-I", str(source / "source"),
               "-I", str(EXT), str(probe)]
    run = subprocess.run(command, text=True, capture_output=True, timeout=60)
    (tmp_path / "compile.json").write_text(json.dumps({"command": command, "returncode": run.returncode,
        "stdout": run.stdout, "stderr": run.stderr}, indent=2) + "\n")
    assert run.returncode == 0, run.stderr


@pytest.fixture(scope="module")
def block_option_parser(tmp_path_factory):
    directory = tmp_path_factory.mktemp("block-option-parser")
    header = (EXT / "blockedVariationalEvaluation.h").read_text()
    function = header[header.index("inline UInt variationalBlockEpochs()"):
                      header.index("\nstruct BlockedVariationalEvaluation")]
    source = directory / "option.cpp"
    source.write_text('#include <cstdlib>\n#include <string>\n#include <stdexcept>\n#include <iostream>\n'
        'using UInt=unsigned long;using Exception=std::runtime_error;\n' + function + '\n'
        'int main(){try {std::cout<<variationalBlockEpochs()<<"\\n";return 0;}'
        'catch(const std::exception &error){std::cerr<<error.what()<<"\\n";return 2;}}\n')
    executable = directory / "option"
    compile_ = subprocess.run([os.environ.get("CXX", "c++"), "-std=c++17", str(source), "-o", str(executable)],
                              text=True, capture_output=True, timeout=60)
    (directory / "compile.log").write_text(compile_.stdout + compile_.stderr)
    assert compile_.returncode == 0, compile_.stderr
    return executable


@pytest.mark.parametrize("value,expected", [(None, 0), ("0", 0), ("1", 1), ("64", 64), ("65536", 65536)])
def test_native_option_parser_canonical_values(block_option_parser, value, expected):
    environment = {k: v for k, v in os.environ.items() if k != "ORBIT_POC_VARIATIONAL_BLOCK_EPOCHS"}
    if value is not None:
        environment["ORBIT_POC_VARIATIONAL_BLOCK_EPOCHS"] = value
    run = subprocess.run([str(block_option_parser)], env=environment, text=True, capture_output=True, timeout=5)
    assert run.returncode == 0
    assert run.stdout == f"{expected}\n"


@pytest.mark.parametrize("value", ["", "-1", "+1", "01", "1.0", " 1", "1 ", "65537", "999999999999999999", "1e2"])
def test_native_option_parser_rejects_invalid(block_option_parser, value):
    run = subprocess.run([str(block_option_parser)],
        env=dict(os.environ, ORBIT_POC_VARIATIONAL_BLOCK_EPOCHS=value), text=True, capture_output=True, timeout=5)
    assert run.returncode == 2
    assert "canonical integer" in run.stderr


@pytest.mark.parametrize("density", [False, True])
def test_actual_native_block_pairs(tmp_path, monkeypatch, density):
    """Actual same native operator, including nonzero forces/reanchoring/query cuts."""
    executable = os.environ.get("ORBIT_POC_VARIATIONAL_MEMORY_GROOPS")
    if not executable:
        pytest.skip("set ORBIT_POC_VARIATIONAL_MEMORY_GROOPS for actual native pairs")
    fixture = _load(ROOT / "tests/test_numerics_derivatives.py", "memory_native_reference_fixture")
    read = fixture.read_native_table
    original_run = fixture._run
    comparisons = []
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "1")
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.setenv("ORBIT_POC_NUMERICS_QR_PREFIX", str(tmp_path / "precise-query"))
    monkeypatch.delenv("ORBIT_POC_VARIATIONAL_BLOCK_EPOCHS", raising=False)

    def paired_run(binary, config, directory):
        result = original_run(binary, config, directory)
        node = config.find(".//OrbitPocEvaluateVariational")
        if node is None:
            return result
        original = read(directory / "dynamic-design.txt", 10)
        # Keep the independent derivative assertion in the existing fixture.
        # Additional runs relocate outputs, preserving that original file.
        for reanchor in (False, True):
            for queries in (False, True):
                outputs = {}
                for block in (0, 1, 7, 13, 64, 256):
                    run_dir = directory / f"memory-{int(reanchor)}-{int(queries)}-{block}"
                    run_dir.mkdir()
                    tree = deepcopy(config)
                    evaluation = tree.find(".//OrbitPocEvaluateVariational")
                    evaluation.find("outputfileOrbit").text = str(run_dir / "orbit.txt")
                    fixture._add(evaluation, "outputfileInitialStateDesign", run_dir / "design.txt")
                    fixture._add(evaluation, "outputfileParameters", run_dir / "parameters.txt")
                    if reanchor:
                        from orbit_poc.numerics.backend import write_matrix
                        initial = original[0, 1:7] + np.array([.01, -.02, .03, 1e-5, -2e-5, 3e-5])
                        write_matrix(run_dir / "initial.txt", initial)
                        fixture._add(evaluation, "inputfileInitialState", run_dir / "initial.txt")
                    if queries:
                        grid = fixture._add(fixture._add(evaluation, "timeSeries"), "uniformSampling")
                        for name, value in (("timeStart", 60000), ("timeEnd", "60000+600/86400"), ("sampling", "2.5/86400")):
                            fixture._add(grid, name, value)
                    monkeypatch.setenv("ORBIT_POC_VARIATIONAL_BLOCK_EPOCHS", str(block))
                    execution = original_run(binary, tree, run_dir)
                    (run_dir / "native.log").write_text(execution.stdout + execution.stderr)
                    rows = read(run_dir / "orbit.txt", 10)
                    params = read(run_dir / "parameters.txt")
                    design = read(run_dir / "design.txt")
                    outputs[block] = (rows, params, design)
                    if block:
                        reference = outputs[0]
                        np.testing.assert_array_equal(rows[:, 0], reference[0][:, 0])
                        np.testing.assert_array_equal(design, reference[2])
                        position = float(np.max(np.linalg.norm(rows[:, 1:4] - reference[0][:, 1:4], axis=1)))
                        velocity = float(np.max(np.linalg.norm(rows[:, 4:7] - reference[0][:, 4:7], axis=1)))
                        # Existing ordinary closure limits, unchanged. This is
                        # numerical equivalence, not full-fit acceptance.
                        assert position < 2e-6
                        assert velocity < 3e-9
                        if not reanchor:
                            np.testing.assert_array_equal(params, reference[1])
                        assert "maximum_block_epochs=" in execution.stdout
                        comparisons.append({"block_epochs": block, "density": density, "reanchor": reanchor,
                            "queries": queries, "maximum_position_difference_m": position,
                            "maximum_velocity_difference_m_s": velocity,
                            "maximum_parameter_difference": float(np.max(np.abs(params-reference[1])))})
        monkeypatch.delenv("ORBIT_POC_VARIATIONAL_BLOCK_EPOCHS", raising=False)
        return result

    fixture._run = paired_run
    fixture.test_actual_native_complete_synthetic_transition(executable, tmp_path, "synthetic_complete_v1", density)
    (tmp_path / "block-comparisons.json").write_text(json.dumps({"comparisons": comparisons,
        "native_fixed_parameter_only": True, "full_fit_verified": False}, indent=2) + "\n")
