"""Actual native zero-column validation; explicitly selected completed build only.

No native or compiler invocation happens unless all three
ORBIT_POC_COST_QUERY_NATIVE_{SOURCE,BUILD,CXX} variables are set.  The fixture
links the selected build's actual objects/libraries; it cannot certify a GNSS
fit, statistical covariance, or derivative-specific nonfinite handling.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/native_cost_only_query.cpp"
SELECTORS = tuple("ORBIT_POC_COST_QUERY_NATIVE_" + name for name in ("SOURCE", "BUILD", "CXX"))


def _pin(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path), "sha256": digest.hexdigest(), "bytes": path.stat().st_size}


def _link_arguments(text: str, build: Path) -> tuple[list[Path], list[str]]:
    """Read one exact native link edge; do not glob incomplete object trees."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("build groops: ")]
    if len(starts) != 1:
        raise ValueError("expected exactly one groops link edge")
    start = starts[0]
    edge = lines[start]
    if "$" in edge:
        raise ValueError("unresolved Ninja escaping in native link edge")
    tokens = shlex.split(edge.split(": ", 1)[1])
    if not tokens or not tokens[0].startswith("CXX_EXECUTABLE_LINKER"):
        raise ValueError("unexpected native link rule")
    objects = []
    for token in tokens[1:]:
        if token in ("|", "||"):
            break
        if not token.endswith(".o") or Path(token).is_absolute() or ".." in Path(token).parts:
            raise ValueError("unexpected native object path")
        objects.append(token)
    main = "CMakeFiles/groopscore.dir/groops.cpp.o"
    parallel = "CMakeFiles/groops.dir/parallel/parallelSingle.cpp.o"
    if objects.count(main) != 1 or objects.count(parallel) != 1 or len(objects) != len(set(objects)):
        raise ValueError("missing or duplicate native main/serial object")
    if any(not (p.startswith("CMakeFiles/groopscore.dir/") or p == parallel) for p in objects):
        raise ValueError("unexpected object outside native core/serial implementation")
    libraries = []
    for line in lines[start + 1:]:
        if line and not line.startswith(" "):
            break
        if line.startswith("  LINK_LIBRARIES = "):
            value = line.removeprefix("  LINK_LIBRARIES = ")
            if "$" in value:
                raise ValueError("unresolved Ninja library variables")
            libraries.append(shlex.split(value))
    if len(libraries) != 1 or not libraries[0]:
        raise ValueError("missing exact native LINK_LIBRARIES")
    return [build / name for name in objects if name != main], libraries[0]


def _environment() -> dict[str, str]:
    # These fixtures must not inherit row exporters, interpolation audits or
    # seed controls from a surrounding fit. Keep the caller's pinned loader.
    env = {key: value for key, value in os.environ.items() if not key.startswith("ORBIT_POC_")}
    env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
               MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1")
    return env


@pytest.fixture(scope="module")
def native_query(tmp_path_factory) -> Path:
    selected = [os.environ.get(name) for name in SELECTORS]
    if not any(selected):
        pytest.skip("select the completed native source/build/compiler for real Polynomial tests")
    assert all(selected), "all three native query selectors are required"
    source, build, compiler = map(Path, selected)
    assert all(path.is_absolute() for path in (source, build, compiler))
    native_source = source / "source"
    cache = {}
    for line in (build / "CMakeCache.txt").read_text().splitlines():
        if not line.startswith(("//", "#")) and "=" in line:
            key, value = line.split("=", 1)
            cache[key.split(":", 1)[0]] = value
    assert Path(cache["CMAKE_CXX_COMPILER"]).resolve() == compiler.resolve()
    assert Path(cache["CMAKE_HOME_DIRECTORY"]).resolve() == native_source.resolve()
    objects, libraries = _link_arguments((build / "build.ninja").read_text(), build)
    assert all(path.is_file() for path in objects), "native build has missing object files"
    library_files = [Path(arg) for arg in libraries if Path(arg).is_absolute()]
    assert all(path.is_file() for path in library_files)
    directory = tmp_path_factory.mktemp("native-cost-query")
    binary = directory / "query"
    inputs = [FIXTURE, compiler, build / "build.ninja", build / "CMakeCache.txt",
              native_source / "base/polynomial.h", native_source / "base/polynomial.cpp",
              native_source / "base/matrix.h", native_source / "misc/orbitPoc/nuisancePerformance.h",
              *objects, *library_files]
    pins = [_pin(path) for path in inputs]
    command = [str(compiler), "-std=c++17", "-O2", "-I", str(native_source), str(FIXTURE),
               *map(str, objects), *libraries, "-o", str(binary)]
    # Only the fresh fixture directory receives compiler/linker output; the
    # selected CMake dependency-file LINK_FLAGS are intentionally not replayed.
    result = subprocess.run(command, cwd=directory, env=_environment(), text=True,
                            capture_output=True, timeout=180)
    (directory / "compile.log").write_text(result.stdout + result.stderr)
    unchanged = all(_pin(Path(record["path"])) == record for record in pins)
    (directory / "compile.json").write_text(json.dumps({"command": command,
        "returncode": result.returncode, "input_pins": pins, "inputs_unchanged": unchanged,
        "excluded_main_object": "CMakeFiles/groopscore.dir/groops.cpp.o",
        "native_serial_object_included": True, "native_source_api": True,
        "binary": _pin(binary) if binary.exists() else None}, indent=2) + "\n")
    assert unchanged, "native build inputs changed during fixture compilation"
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


def _run(binary: Path, directory: Path, query: str, scope: str, flag: str) -> dict:
    env = _environment()
    env.update(ORBIT_POC_NUMERICS_QR_PREFIX=str(directory / "qr"),
               ORBIT_POC_NUISANCE_PERFORMANCE="1", ORBIT_POC_NUISANCE_INTERPOLATION_CACHE="0",
               ORBIT_POC_NUISANCE_COST_ONLY_DESIGN=flag)
    command = [str(binary), query, scope]
    result = subprocess.run(command, cwd=directory, env=env, capture_output=True, text=True, timeout=15)
    (directory / f"{scope}-{query}-{flag}.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["context_active_after"] is False
    return report


@pytest.mark.parametrize("query", ["grid", "offgrid", "remainder", "negative_remainder", "negative_zero"])
def test_real_native_zero_column_query_validates_and_returns_zero_matrix(native_query, tmp_path, query):
    full = _run(native_query, tmp_path, query, "cost", "0")
    skipped = _run(native_query, tmp_path, query, "cost", "1")
    assert not full["rejected"] and not skipped["rejected"]
    assert (full["computations"], full["validations"]) == (1, 0)
    assert (skipped["computations"], skipped["validations"]) == (0, 1)
    assert full["difference_from_native_full_interpolation"] == 0
    assert full["maximum_absolute_value"] > 0
    assert not full["all_zero"]
    assert skipped["all_zero"] and skipped["all_finite"]
    assert (skipped["rows"], skipped["columns"]) == (3, 5)
    assert skipped["omitted_dynamic_designs"] == 1
    assert full["omitted_dynamic_designs"] == 0


@pytest.mark.parametrize("query,error", [
    ("outside_before", "cannot interpolate at"), ("outside_after", "cannot interpolate at"),
    ("nan_remainder", "Relative polynomial query exceeds sub-Time remainder"),
    ("infinite_remainder", "Relative polynomial query exceeds sub-Time remainder"),
    ("oversized_remainder", "Relative polynomial query exceeds sub-Time remainder"),
])
def test_real_native_invalid_query_rejects_identically_with_omission(native_query, tmp_path, query, error):
    full = _run(native_query, tmp_path, query, "cost", "0")
    skipped = _run(native_query, tmp_path, query, "cost", "1")
    for result in (full, skipped):
        assert result["rejected"] and error in result["error"]
        assert result["omitted_dynamic_designs"] == 0
    assert full["error"] == skipped["error"]
    assert (full["computations"], full["validations"]) == (1, 0)
    assert (skipped["computations"], skipped["validations"]) == (0, 1)


@pytest.mark.parametrize("scope", ["full", "outside"])
@pytest.mark.parametrize("flag", ["0", "1"])
def test_real_native_full_rows_and_outside_scope_compute_all_columns(native_query, tmp_path, scope, flag):
    result = _run(native_query, tmp_path, "remainder", scope, flag)
    assert not result["rejected"]
    assert (result["computations"], result["validations"]) == (1, 0)
    assert result["omitted_dynamic_designs"] == 0
    assert result["difference_from_native_full_interpolation"] == 0
    assert result["all_finite"] and not result["all_zero"]
    assert (result["rows"], result["columns"]) == (3, 5)


def test_native_link_selection_excludes_only_main_and_keeps_serial_object(tmp_path):
    text = ("build groops: CXX_EXECUTABLE_LINKER__groops_Release "
            "CMakeFiles/groopscore.dir/base/polynomial.cpp.o CMakeFiles/groopscore.dir/groops.cpp.o "
            "CMakeFiles/groops.dir/parallel/parallelSingle.cpp.o | /native/libblas.so || groopscore\n"
            "  LINK_LIBRARIES = /native/libblas.so -lgfortran\n")
    objects, libraries = _link_arguments(text, tmp_path)
    assert [path.relative_to(tmp_path).as_posix() for path in objects] == [
        "CMakeFiles/groopscore.dir/base/polynomial.cpp.o", "CMakeFiles/groops.dir/parallel/parallelSingle.cpp.o"]
    assert libraries == ["/native/libblas.so", "-lgfortran"]
    for bad in (text.replace("parallelSingle", "parallelMpi"),
                text.replace("CMakeFiles/groopscore.dir/groops.cpp.o ", ""),
                text.replace("/native/libblas.so -lgfortran", "$LIBRARIES"),
                text.replace("base/polynomial.cpp.o", "../polynomial.cpp.o")):
        with pytest.raises(ValueError):
            _link_arguments(bad, tmp_path)
