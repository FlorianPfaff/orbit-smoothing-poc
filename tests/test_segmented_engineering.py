"""Control-only checks; these never start a native workload."""
import importlib.util
import json
from pathlib import Path
import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts/segmented_engineering.py"
SPEC = importlib.util.spec_from_file_location("segmented_engineering", PATH)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def test_native_scope_and_resource_limits():
    paths = {"python": Path("/python"), "run": Path("/run")}
    for item in M.TESTS:
        command = M.pytest_command(paths, Path("/native"), item)
        assert command[:6] == ["/usr/bin/taskset", "-c", "24", "/usr/bin/prlimit", "--as=8589934592", "--"]
        assert "ORBIT_POC_SEGMENTED_GROOPS=/native" in command
        assert command[-len(item["files"]):] == item["files"]
    assert [item["count"] for item in M.TESTS] == [106, 51, 3]


@pytest.fixture
def plan(tmp_path):
    artifact = tmp_path / "artifact"
    artifact.write_text("sealed")
    pin = {"path": str(artifact), "sha256": M.sha(artifact)}
    value = {"schema": "orbit-poc-segmented-engineering-plan-v1", "global_lock": "/tmp/engineering.lock", "tests": M.TESTS}
    value.update({key: pin for key in M.PLAN_KEYS - {"schema", "global_lock", "tests"}})
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(value))
    return path, value, artifact


def test_exact_plan_pins(plan):
    path, value, _ = plan
    assert M.load_plan(path, M.sha(path)) == value


@pytest.mark.parametrize("mutation", [
    lambda v: v.update(unknown=True),
    lambda v: v.update(schema="release"),
    lambda v: v.update(tests=[]),
    lambda v: v.update(global_lock="relative"),
    lambda v: v["runner"].update(extra=True),
    lambda v: v["execution"].update(sha256="0" * 64),
])
def test_plan_fail_closed(plan, mutation):
    path, value, _ = plan
    mutation(value)
    path.write_text(json.dumps(value))
    with pytest.raises(RuntimeError):
        M.load_plan(path, M.sha(path))


def test_changed_artifact_and_plan_rejected(plan):
    path, _, artifact = plan
    digest = M.sha(path)
    artifact.write_text("changed")
    with pytest.raises(RuntimeError, match="Artifact changed"):
        M.load_plan(path, digest)
    path.write_text("{}")
    with pytest.raises(RuntimeError, match="Engineering plan changed"):
        M.load_plan(path, digest)
