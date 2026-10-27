"""Candidate build admission/reentry tests; all external commands are mocked."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).parents[1]
FLAGS = ["--numerics", "--segmented", "--nuisance-performance", "--variational-memory-candidate"]


def setup(tmp_path, monkeypatch, *, installed=(), flags=None, configure_only=True):
    spec = importlib.util.spec_from_file_location("candidate_builder", ROOT / "scripts/build_groops.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    source, build = tmp_path / "source", tmp_path / "build"
    (source / "source").mkdir(parents=True)
    (source / "source/preserved.cpp").write_text("original installed source\n")
    for name in installed:
        (source / f"orbit-poc-{name}-extension.json").write_text(json.dumps({"kind": name}))
    commands, reads = [], []

    def read(command, **kwargs):
        reads.append([str(x) for x in command])
        assert command == ["git", "-C", str(source), "rev-parse", "HEAD"]
        return builder.COMMIT + "\n"

    def run(command, **kwargs):
        commands.append([str(x) for x in command])

    monkeypatch.setattr(builder.subprocess, "check_output", read)
    monkeypatch.setattr(builder, "run", run)
    argv = [str(ROOT / "scripts/build_groops.py"), "--source-dir", str(source),
            "--build-dir", str(build), *(FLAGS if flags is None else flags)]
    if configure_only:
        argv.append("--configure-only")
    monkeypatch.setattr(sys, "argv", argv)
    before = snapshot(source)
    return builder, source, build, commands, reads, before


def snapshot(source):
    return {str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*") if p.is_file()}


@pytest.mark.parametrize("flags", [[], ["--numerics"], ["--numerics", "--segmented"],
                                    ["--numerics", "--nuisance-performance"]])
def test_memory_flag_missing_prerequisites_rejects_before_source_access(tmp_path, monkeypatch, flags):
    builder, source, build, calls, reads, before = setup(
        tmp_path, monkeypatch, flags=[*flags, "--variational-memory-candidate"])
    with pytest.raises(SystemExit) as error:
        builder.main()
    assert error.value.code == 2
    assert calls == [] and reads == []
    assert snapshot(source) == before and not build.exists()


@pytest.mark.parametrize("installed_memory,selected_memory", [(True, False), (False, True)])
def test_memory_profile_mismatch_precedes_every_installer(tmp_path, monkeypatch,
                                                        installed_memory, selected_memory):
    installed = ["nuisance-performance", "segmented"]
    if installed_memory:
        installed.append("variational-memory")
    flags = FLAGS if selected_memory else FLAGS[:-1]
    builder, source, build, calls, reads, before = setup(tmp_path, monkeypatch,
                                                       installed=installed, flags=flags)
    with pytest.raises(ValueError, match="profile|memory"):
        builder.main()
    assert len(reads) == 1 and calls == []
    assert snapshot(source) == before and not build.exists()


@pytest.mark.parametrize("selected_memory", [False, True])
def test_memory_without_nuisance_manifest_cannot_be_overwritten(tmp_path, monkeypatch, selected_memory):
    flags = FLAGS if selected_memory else FLAGS[:-1]
    builder, source, build, calls, reads, before = setup(tmp_path, monkeypatch,
        installed=["segmented", "variational-memory"], flags=flags)
    with pytest.raises(ValueError, match="profile|memory|nuisance"):
        builder.main()
    assert calls == []
    assert snapshot(source) == before and not build.exists()


@pytest.mark.parametrize("wide", [False, True])
def test_exact_profile_reentry_only_verifies_then_configures(tmp_path, monkeypatch, wide):
    installed = ["nuisance-performance", "segmented", "variational-memory"]
    flags = list(FLAGS)
    if wide:
        installed.append("wide-tangent")
        flags.append("--wide-tangent-candidate")
    builder, source, build, calls, reads, before = setup(tmp_path, monkeypatch,
                                                       installed=installed, flags=flags)
    builder.main()
    assert len(calls) == 3
    assert [Path(calls[i][1]).name for i in range(2)] == ["native_nuisance_performance.py",
                                                                       "native_variational_memory.py"]
    assert calls[2][:2] == ["cmake", "-S"]
    assert snapshot(source) == before
    assert not build.exists()  # Even configure is mocked.


@pytest.mark.parametrize("failing_installer", ["native_nuisance_performance.py", "native_variational_memory.py"])
def test_verifier_failure_cannot_reinstall_or_configure(tmp_path, monkeypatch, failing_installer):
    builder, source, build, calls, reads, before = setup(tmp_path, monkeypatch,
        installed=["nuisance-performance", "segmented", "variational-memory"])

    def fail(command, **kwargs):
        calls.append([str(x) for x in command])
        if Path(str(command[1])).name == failing_installer:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(builder, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        builder.main()
    assert all(c[0] != "cmake" for c in calls)
    assert all(Path(c[1]).name != "apply_extension.py" for c in calls)
    assert snapshot(source) == before and not build.exists()


def test_fresh_candidate_installs_in_order(tmp_path, monkeypatch):
    builder, source, build, calls, reads, before = setup(
        tmp_path, monkeypatch, flags=[*FLAGS, "--wide-tangent-candidate"])
    builder.main()
    assert [Path(c[1]).name for c in calls[:-1]] == ["apply_extension.py", "native_segmented.py",
        "native_tangent_wide.py", "native_nuisance_performance.py", "native_variational_memory.py"]
    assert calls[-1][:2] == ["cmake", "-S"]
    assert snapshot(source) == before


def test_default_profile_does_not_silently_install_memory_candidate(tmp_path, monkeypatch):
    builder, source, build, calls, reads, before = setup(tmp_path, monkeypatch,
        installed=["nuisance-performance", "segmented"], flags=FLAGS[:-1])
    builder.main()
    assert len(calls) == 2
    assert Path(calls[0][1]).name == "native_nuisance_performance.py"
    assert calls[1][0] == "cmake"
    assert snapshot(source) == before


def test_completed_build_manifest_retains_memory_installer_identity(tmp_path, monkeypatch):
    builder, source, build, calls, reads, before = setup(tmp_path, monkeypatch,
        installed=["nuisance-performance", "segmented", "variational-memory"], configure_only=False)
    (source / "orbit-poc-extension.json").write_text('{"base":"pinned"}')
    before = snapshot(source)
    build.mkdir()
    (build / "groops").write_bytes(b"synthetic binary, never executed")
    (build / "CMakeCache.txt").write_text("synthetic cache")

    def read(command, **kwargs):
        if command[0] == "git":
            return builder.COMMIT + "\n"
        assert command[-1] == "--version"
        return "mock tool version\n"

    monkeypatch.setattr(builder.subprocess, "check_output", read)
    builder.main()
    manifest = json.loads((build / "build-manifest.json").read_text())
    assert manifest["variational_memory_extension"] == {"kind": "variational-memory"}
    assert manifest["nuisance_performance_extension"] == {"kind": "nuisance-performance"}
    assert "source/preserved.cpp" in manifest["patched_source"]["files"]
    assert snapshot(source) == before
    assert any(c[:2] == ["cmake", "--build"] for c in calls)
    assert any(c == [str(build / "groops"), "--help"] for c in calls)  # Mock only.
