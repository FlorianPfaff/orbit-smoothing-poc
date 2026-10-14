"""Check launch provenance enforcement; mount enforcement has a separate live smoke receipt."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/verify_numerics_runtime.py"
LAUNCH_KEYS = ("wrapper", "bubblewrap", "runtime_startup_verifier",
               "run_to_report_controller", "run_to_report_entrypoint")


def artifact(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def startup(tmp_path, monkeypatch):
    root = tmp_path / "runtime"; root.mkdir()
    payload = root / "library.py"; payload.write_text("frozen = True\n")
    manifest = tmp_path / "runtime.json"
    manifest.write_text(json.dumps({"trees": [{"root": str(root), "files": [
        {"relative_path": payload.name, "bytes": payload.stat().st_size,
         "sha256": artifact(payload)["sha256"]}]}]}))
    context = {"runtime_manifest": artifact(manifest), "new_python_runtime_manifest": artifact(manifest)}
    for key in LAUNCH_KEYS:
        path = SCRIPT if key == "runtime_startup_verifier" else tmp_path / key
        if path != SCRIPT: path.write_text("pinned launch payload: " + key)
        context[key] = artifact(path)
    context_path = tmp_path / "context.json"
    config = tmp_path / "config.json"; receipt = tmp_path / "startup.json"
    bytecode = tmp_path / "empty-bytecode"; bytecode.mkdir()
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    monkeypatch.setenv("PYTHONPYCACHEPREFIX", str(bytecode))
    # This unit fixture tests digests independently of mount permissions.
    monkeypatch.setattr(os, "statvfs", lambda _: SimpleNamespace(f_flag=os.ST_RDONLY))
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--config", str(config), "--receipt", str(receipt)])

    def execute():
        context_path.write_text(json.dumps(context))
        config.write_text(json.dumps({"execution_context": artifact(context_path)}))
        runpy.run_path(str(SCRIPT), run_name="__main__")
        return json.loads(receipt.read_text())
    return context, receipt, execute


def test_startup_pins_every_launch_artifact(startup):
    context, _, execute = startup
    result = execute()
    assert result["status"] == "verified"
    assert result["launch_artifacts"] == {key: context[key] for key in LAUNCH_KEYS}
    assert len(result["trees"]) == 2


@pytest.mark.parametrize("key", LAUNCH_KEYS)
def test_changed_launch_artifact_blocks_startup(startup, key):
    context, receipt, execute = startup
    context[key]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="Pinned artifact changed"):
        execute()
    assert not receipt.exists()


def test_missing_launch_artifact_blocks_startup(startup):
    context, receipt, execute = startup
    context.pop("wrapper")
    with pytest.raises(ValueError, match="Missing pinned launch artifact"):
        execute()
    assert not receipt.exists()


def test_identical_other_verifier_path_is_not_the_executing_verifier(startup, tmp_path):
    context, receipt, execute = startup
    alternative = tmp_path / "other-verifier.py"; alternative.write_bytes(SCRIPT.read_bytes())
    context["runtime_startup_verifier"] = artifact(alternative)
    with pytest.raises(ValueError, match="Executing verifier differs"):
        execute()
    assert not receipt.exists()
