"""SOURCE ONLY, UNEXECUTED: isolated wrapper for the exact 36+16 helper tests.

Use the reviewed remote launcher. This is not an orbital acceptance gate.
"""
import sys

if not (sys.flags.isolated == 1 and sys.flags.no_site == 1
        and sys.flags.no_user_site == 1 and sys.flags.dont_write_bytecode == 1):
    raise RuntimeError("Require the reviewed Python -I -S -B invocation")
if sys.version_info[:3] != (3, 11, 15):
    raise RuntimeError("Unexpected interpreter version")
if "site" in sys.modules:
    raise RuntimeError("site must not have run before the wrapper")

import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import traceback
import unittest

ROOT = Path("/home/florianpfaff/codex-runs/orbit-helper-qualification-20261026-04")
VENV = Path("/home/florianpfaff/codex-runs/orbit-poc-20261013/env")
PYTHON = VENV / "bin/python"
SITE = VENV / "lib/python3.11/site-packages"
BOOT = "95156dd4-0d4c-499d-a214-8883a2d650fa"
PINNED_SOURCES = {
    "rank/rank_audit.py": "982f8dbc1ef4b91d015fade27d2b23e6979945b8fddb7a844a5511d330eaf872",
    "rank/test_rank_audit.py": "59b39e26bb9900a6883f685ccc35ec7108bfbb23460d720658138fa8d3e9a308",
    "exports/export_audit.py": "dbea05e6c10ccc6d30d07cda379b41e0d5a0518760090e8190e56d13dc0b8083",
    "exports/test_export_audit.py": "6dae16b69980f7af7c613be28692d428edda6e72b8a3c35ced73ce74b1aee7a9",
}


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_new(path, value):
    data = (json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=".qualification-", dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_pins(path):
    result = {}
    for line in path.read_text().splitlines():
        if len(line) < 67 or line[64:66] != "  " or any(c not in "0123456789abcdef" for c in line[:64]):
            raise RuntimeError("Unexpected sha256sum inventory encoding")
        name = Path(line[66:])
        if not name.is_absolute() or not name.is_file():
            raise RuntimeError(f"Missing/nonabsolute pinned runtime file: {name}")
        name = str(name.resolve(strict=True))
        if name in result and result[name] != line[:64]:
            raise RuntimeError(f"Contradictory runtime aliases: {name}")
        result[name] = line[:64]
    return result


def snapshot(pins, expected_path, phase):
    if sys.path != expected_path:
        raise RuntimeError(f"sys.path changed during {phase}: {sys.path!r}")
    for forbidden in ("site", "sitecustomize", "usercustomize", "_virtualenv"):
        if forbidden in sys.modules:
            raise RuntimeError(f"Forbidden startup module was loaded: {forbidden}")
    verified = {}

    def verify(name):
        path = Path(name).resolve(strict=True)
        key = str(path)
        if key not in pins:
            raise RuntimeError(f"Actual loaded file has no reviewed pin: {key}")
        if key not in verified:
            actual = digest(path)
            if actual != pins[key]:
                raise RuntimeError(f"Actual loaded file hash changed: {key}")
            verified[key] = actual
        return key

    modules = []
    for name, module in sorted(list(sys.modules.items())):
        location = getattr(module, "__file__", None)
        if location:
            modules.append({"module": name, "file": str(location), "resolved": verify(location)})
    raw_maps = Path("/proc/self/maps").read_text()
    maps = set()
    for line in raw_maps.splitlines():
        fields = line.split(None, 5)
        if len(fields) == 6 and fields[5].startswith("/"):
            if fields[5].endswith(" (deleted)"):
                raise RuntimeError("An actual mapped runtime file was deleted")
            maps.add(verify(fields[5]))
    return {"phase": phase, "sys_path": list(sys.path), "modules": modules,
            "mapped_files": sorted(maps), "mapped_lines": raw_maps.splitlines(),
            "verified_sha256": verified, "python": sys.executable,
            "python_version": sys.version, "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "startup_isolated": True, "site_processed": False}


def main():
    if len(sys.argv) != 4 or sys.argv[1] not in ("rank", "export"):
        raise RuntimeError("Expected suite, pinned runtime inventory and fresh owned job directory")
    suite_name = sys.argv[1]
    pin_path = Path(sys.argv[2])
    job = Path(sys.argv[3])
    if Path(__file__).resolve(strict=True) != ROOT / "isolated_suite.py":
        raise RuntimeError("Wrapper not at the reviewed remote path")
    if job != ROOT / "attempt01" / suite_name or job.resolve(strict=True) != job:
        raise RuntimeError("Unexpected/noncanonical output directory")
    if pin_path != ROOT / "preflight01/runtime.sha256":
        raise RuntimeError("Wrong reviewed runtime inventory")
    outcome = {"schema": "remote-helper-qualification-v4", "suite": suite_name,
               "status": "failed", "tests_launched": False,
               "scope": "untimed synthetic helper unit tests only",
               "initial_sys_path_raw": list(sys.path),
               "covariance_authority": False, "release_authority": False}
    result = None
    code = 1
    try:
        if sys.executable != str(PYTHON) or Path("/proc/sys/kernel/random/boot_id").read_text().strip() != BOOT:
            raise RuntimeError("Interpreter or boot identity differs")
        pins = read_pins(pin_path)
        for relative, expected in PINNED_SOURCES.items():
            file = ROOT / relative
            if digest(file) != expected or pins.get(str(file.resolve(strict=True))) != expected:
                raise RuntimeError(f"Helper source identity differs: {file}")
        base = PYTHON.resolve(strict=True).parent.parent
        stdlib = base / "lib/python3.11"
        zip_path = base / "lib/python311.zip"
        if len(sys.path) != 3 or sys.path[0] != str(zip_path) or zip_path.exists():
            raise RuntimeError(f"Unexpected isolated initial sys.path: {sys.path!r}")
        initial_existing = [Path(item).resolve(strict=True) for item in sys.path[1:]]
        if initial_existing != [stdlib, stdlib / "lib-dynload"]:
            raise RuntimeError(f"Isolated stdlib paths resolve outside the pinned base: {sys.path!r}")
        outcome["initial_sys_path_resolved"] = [str(zip_path)] + [str(item) for item in initial_existing]
        suite_dir = ROOT / ("rank" if suite_name == "rank" else "exports")
        expected_path = [str(stdlib), str(stdlib / "lib-dynload"), str(suite_dir), str(SITE)]
        sys.path[:] = expected_path
        # No site.addsitedir: .pth, sitecustomize and _virtualenv never run.
        # Only stdlib, these two scientific packages and the one helper may load.
        class SelectedImports:
            def find_spec(self, fullname, path=None, target=None):
                top = fullname.partition(".")[0]
                if fullname == "_sysconfigdata__linux_x86_64-linux-gnu":
                    expected = stdlib / "_sysconfigdata__linux_x86_64-linux-gnu.py"
                    expected_sha = "370767023c70ac6b2115ba239a593cf87b3b47bc624edaf3a2b386ad01e7aeff"
                    spec = importlib.machinery.PathFinder.find_spec(fullname, [str(stdlib)], target)
                    if (spec is None or not spec.origin
                            or Path(spec.origin).resolve(strict=True) != expected
                            or pins.get(str(expected)) != expected_sha or digest(expected) != expected_sha):
                        raise ImportError("Generated stdlib module origin or pinned hash differs")
                    return spec
                if top not in sys.stdlib_module_names and top not in {"numpy", "scipy", "rank_audit", "export_audit"}:
                    raise ImportError(f"Unselected package is forbidden in this qualification: {fullname}")
                return None
        sys.meta_path.insert(0, SelectedImports())
        import numpy
        import scipy
        import scipy.linalg
        if numpy.__version__ != "1.26.4" or scipy.__version__ != "1.15.3":
            raise RuntimeError("Selected scientific package version differs")
        write_new(job / "loaded-before.json", snapshot(pins, expected_path, "after-scientific-imports"))
        test_file = suite_dir / ("test_rank_audit.py" if suite_name == "rank" else "test_export_audit.py")
        spec = importlib.util.spec_from_file_location("qualified_helper_tests", test_file)
        if spec is None or spec.loader is None:
            raise RuntimeError("Cannot load exact test module")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        suite = unittest.defaultTestLoader.loadTestsFromModule(module)
        expected = 36 if suite_name == "rank" else 16
        if suite.countTestCases() != expected:
            raise RuntimeError("Exact frozen unit-test count differs")
        write_new(job / "loaded-at-discovery.json", snapshot(pins, expected_path, "after-test-discovery"))
        outcome["tests_launched"] = True
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        write_new(job / "loaded-after.json", snapshot(pins, expected_path, "after-unit-tests"))
        outcome.update(tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                       skips=len(result.skipped), expected_failures=len(result.expectedFailures),
                       unexpected_successes=len(result.unexpectedSuccesses))
        passed = (result.wasSuccessful() and result.testsRun == expected and not result.skipped
                  and not result.expectedFailures and not result.unexpectedSuccesses)
        outcome["status"] = "passed" if passed else "failed"
        code = 0 if passed else 1
    except BaseException as error:
        outcome["error_type"] = type(error).__name__
        outcome["error"] = str(error)
        outcome["traceback"] = traceback.format_exc()
        traceback.print_exc()
    finally:
        if result is not None:
            outcome["tests_run"] = result.testsRun
            outcome["failed_test_ids"] = [test.id() for test, _ in result.failures + result.errors]
        write_new(job / "wrapper-outcome.json", outcome)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
