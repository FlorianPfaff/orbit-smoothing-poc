#!/usr/bin/env python3
"""Run a pinned, isolated engineering build using the audited recovery supervisor.

This is an engineering gate, not a v4 release or benchmark result. The source,
controls and runtime are immutable pins; all native outputs are fresh. The
borrowed supervisor owns private PID namespaces and checks host admission.
"""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import sys

COMMIT = "7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee"
PLAN_KEYS = {"schema", "execution", "driver", "runner", "source_freeze", "previous_source_freeze", "global_lock", "tests", "linearization_inputs"}
ORIGINAL = ["tests/test_numerics_native_qr.py", "tests/test_numerics_original_objective.py",
            "tests/test_numerics_mean_residual.py", "tests/test_numerics_derivatives.py",
            "tests/test_numerics_geometry_precision.py", "tests/test_numerics_synthetic_force_arithmetic.py"]
CORRECTIONS = ["tests/test_numerics_query_precision.py", "tests/test_numerics_reference_precision.py",
               "tests/test_numerics_precise_residual.py", "tests/test_numerics_precise_objective.py",
               "tests/test_numerics_light_time_precision.py"]
TESTS = [{"name": "native-tests", "files": ORIGINAL, "count": 106},
         {"name": "correction-tests", "files": CORRECTIONS, "count": 51},
         {"name": "segmented-qr-tests", "files": ["tests/test_segmented_native_qr.py"], "count": 47},
         {"name": "segmented-tangent-tests", "files": ["tests/test_segmented_native_tangent.py"], "count": 3}]


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def require(ok, why):
    if not ok:
        raise RuntimeError(why)


def checked(pin):
    require(isinstance(pin, dict) and set(pin) == {"path", "sha256"}, "Invalid artifact pin")
    require(Path(pin["path"]).is_absolute() and sha(pin["path"]) == pin["sha256"], "Artifact changed: " + pin["path"])


def load_plan(path, digest):
    require(sha(path) == digest, "Engineering plan changed")
    plan = json.loads(Path(path).read_text())
    require(set(plan) == PLAN_KEYS and plan["schema"] == "orbit-poc-segmented-engineering-plan-v2", "Unknown engineering plan")
    for key in ("execution", "driver", "runner", "source_freeze", "previous_source_freeze"):
        checked(plan[key])
    require(plan["tests"] == TESTS, "Engineering test scope changed")
    require(set(plan["linearization_inputs"]) == {"pulses", "log_drag_ou", "initial"}, "Linearization input scope changed")
    for pin in plan["linearization_inputs"].values():
        require(set(pin) == {"path", "sha256"}, "Invalid linearization input pin")
    require(Path(plan["global_lock"]).is_absolute(), "Absolute host lock required")
    return plan


def pytest_command(paths, native, item, solver=None):
    name = item["name"]
    return ["/usr/bin/taskset", "-c", "24", "/usr/bin/prlimit", "--as=8589934592", "--",
            "env", "ORBIT_POC_V31_NATIVE=" + str(native), "ORBIT_POC_GROOPS=" + str(native),
            "ORBIT_POC_CORRECTNESS_NATIVE=" + str(native), "ORBIT_POC_SEGMENTED_GROOPS=" + str(native),
            *(["ORBIT_POC_SEGMENTED_SOLVER=" + str(solver), "ORBIT_POC_SEGMENTED_SOLVER_SHA256=" + sha(solver)] if solver else []),
            str(paths["python"]), "-m", "pytest", "-q", "-s", "-p", "no:cacheprovider",
            "--basetemp=" + str(paths["run"] / (name + "-temp")),
            "--junitxml=" + str(paths["run"] / (name + ".xml")), *item["files"]]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args(argv)
    plan = load_plan(args.plan, args.sha256)
    require(plan["runner"]["sha256"] == sha(__file__), "Engineering runner changed")
    spec = importlib.util.spec_from_file_location("audited_owned_supervisor", plan["driver"]["path"])
    d = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(d)
    e = d.load_execution(plan["execution"]["path"])
    paths = {key: Path(value) for key, value in e["paths"].items()}
    require(e["build_cpus"] == [24, 25, 26, 27] and e["fit_cpu"] == 24, "Engineering CPU allocation changed")
    freeze = json.loads(Path(plan["source_freeze"]["path"]).read_text())
    previous = json.loads(Path(plan["previous_source_freeze"]["path"]).read_text())
    frozen = freeze["source"]
    require(freeze["scope"] == "engineering_only_not_release_or_frozen_benchmark", "Engineering scope changed")
    for name in ORIGINAL + CORRECTIONS:
        require(frozen["files"][name] == previous["source"]["files"][name], "Protected native test changed: " + name)
    registry, handlers, journal = [], {}, {}
    run = paths["run"]

    def guard(*, source=True):
        require(load_plan(args.plan, args.sha256) == plan, "Plan changed")
        if source:
            require(d.source_receipt(paths["source"]) == frozen, "Engineering source snapshot changed")
        for name, pin in e["runtime_artifacts"].items():
            require(sha(d.resolved_host_path(pin["path"], e)) == pin["sha256"], "Runtime changed: " + name)
        for pin in plan["linearization_inputs"].values():
            require(sha(d.resolved_host_path(pin["path"], e)) == pin["sha256"], "Linearization input changed")
        for key in ("native", "solver"):
            if key in journal:
                require(sha(journal[key]["path"]) == journal[key]["sha256"], "Engineering executable changed")
        return d.admission(e, registry)

    def save():
        d.save(run / "pipeline.json", journal)

    def command(name, command, timeout, *, required=True):
        guard()
        entry = {"name": name, "status": "running", "command": list(map(str, command)), "started_at": d.stamp()}
        journal["steps"].append(entry)
        wrapped = [e["runtime_artifacts"]["control_python"]["path"], str(paths["wrapper"]),
                   "--execution", plan["execution"]["path"], "--execution-sha256", plan["execution"]["sha256"],
                   "--", "/usr/bin/time", "-v", "-o", str(run / (name + ".time.txt")), *command]
        env = dict(os.environ, PYTHONPATH=str(paths["source"] / "src"), PYTHONDONTWRITEBYTECODE="1",
                   OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1")
        for key in list(env):
            if key.startswith("ORBIT_POC_"):
                env.pop(key)
        def started(pid):
            entry["process"] = d.proc(pid)
            save()
        def finished(value):
            entry.update(value)
            save()
        try:
            save()
            with (run / (name + ".log")).open("x") as log:
                code = d.supervise(wrapped, cwd=paths["source"], env=env, log=log, limit=timeout,
                                   guard_live=lambda: d.admission(e, registry), on_started=started,
                                   on_finished=finished, registry=registry)
            entry.update(returncode=code, status="completed" if code == 0 else "failed", finished_at=d.stamp())
            save()
            guard()
            require(code == 0 or not required, name + " failed")
            return code
        except BaseException as error:
            entry.update(status="failed", error=type(error).__name__ + ": " + str(error), finished_at=d.stamp())
            save()
            raise

    with Path(plan["global_lock"]).open("a") as lock, (paths["control"] / "engineering.lock").open("a") as local_lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(local_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        admitted = guard()
        d.prepare_writable_directories(e["paths"])
        journal = {"schema": "orbit-poc-segmented-engineering-run-v1", "status": "running", "started_at": d.stamp(),
                   "scope": freeze["scope"], "release_ready": False, "plan": d.artifact(args.plan), "admission": admitted,
                   "source": frozen, "steps": [], "fit_memory_limit_bytes": 8589934592,
                   "memory_scope": "per-process inherited RLIMIT_AS; /usr/bin/time reports peak process RSS"}
        try:
            for number in (signal.SIGINT, signal.SIGTERM):
                handlers[number] = signal.getsignal(number)
                signal.signal(number, d.interrupted)
            save()
            smoke = "import ctypes,subprocess,numpy,scipy,gtsam,pytest; from pathlib import Path; " \
                    "assert ctypes.CDLL(None).gnu_get_libc_version; " \
                    "p=Path(" + repr(str(paths["source"])) + "); " \
                    "assert not __import__('os').access(p,__import__('os').W_OK); " \
                    "r=subprocess.check_output(['git','--git-dir'," + repr(str(paths["upstream_repository"])) + ",'rev-parse','" + COMMIT + "^{tree}'],text=True).strip(); " \
                    "assert r=='097cb2de82c483262e82a1ef2ea8acde850a7ec2'; " \
                    "subprocess.run(['git','--git-dir'," + repr(str(paths["upstream_repository"])) + ",'archive','--format=tar','" + COMMIT + "'],stdout=subprocess.DEVNULL,check=True); print('namespace/upstream/scientific runtime smoke passed')"
            command("namespace-smoke", [paths["python"], "-c", smoke], 300)
            command("clone", ["git", "clone", "--no-hardlinks", "--no-checkout", paths["upstream_repository"], paths["native_source"]], 600)
            command("checkout", ["git", "-C", paths["native_source"], "checkout", "--detach", COMMIT], 600)
            command("build", ["/usr/bin/taskset", "-c", "24,25,26,27", paths["python"], paths["source"] / "scripts/build_groops.py",
                              "--source-dir", paths["native_source"], "--build-dir", paths["build"], "--prefix", paths["prefix"],
                              "--cmake-executable", paths["cmake"], "--numerics", "--segmented", "--jobs", "4"], 7200)
            native = paths["binaries"] / ("groops-" + sha(paths["build"] / "groops")[:16])
            shutil.copy2(paths["build"] / "groops", native)
            native.chmod(0o555)
            manifest = paths["binaries"] / "build-manifest.json"
            shutil.copy2(paths["build"] / "build-manifest.json", manifest)
            journal["native"], journal["build_manifest"] = d.artifact(native), d.artifact(manifest)
            save()
            compiler = e["runtime_artifacts"]["cxx_compiler"]
            lapack, blas = (e["runtime_artifacts"][key] for key in ("lapack", "blas"))
            solver_output = paths["build"] / "segmented-qr"
            solver_command = ["/usr/bin/taskset", "-c", "24", compiler["path"], "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                paths["source"] / "groops/extension/segmentedQrMain.cpp", lapack["path"], blas["path"],
                "-Wl,-rpath,"+str(paths["prefix"] / "lib"), "-o", solver_output]
            command("build-segmented-qr", solver_command, 600)
            solver = paths["binaries"] / ("segmented-qr-" + sha(solver_output)[:16])
            shutil.copy2(solver_output, solver); solver.chmod(0o555)
            journal["solver"] = d.artifact(solver)
            journal["solver_build"] = {"argv": list(map(str, solver_command)), "compiler": compiler,
                "lapack": lapack, "blas": blas, "header_sha256": sha(paths["source"] / "groops/extension/segmentedQr.h"),
                "main_sha256": sha(paths["source"] / "groops/extension/segmentedQrMain.cpp")}
            save()
            outcomes = []
            for item in TESTS:
                code = command(item["name"], pytest_command(paths, native, item, solver), 3600, required=False)
                try:
                    inventory = d.verify_native_junit(run / (item["name"] + ".xml"), item["count"])
                    require(code == 0, "Nonzero native test process")
                    outcomes.append(True)
                except Exception as error:
                    inventory = {"status": "failed", "error": repr(error)}
                    outcomes.append(False)
                journal["steps"][-1]["test_inventory"] = inventory
                save()
            for method in ("pulses", "log_drag_ou"):
                name = "native-linearization-" + method
                argv = ["/usr/bin/taskset", "-c", "24", "/usr/bin/prlimit", "--as=8589934592", "--", paths["python"],
                    paths["source"] / "scripts/validate_segmented_linearization.py", "--request", plan["linearization_inputs"][method]["path"],
                    "--binary", native, "--solver", solver, "--initial-state-from", plan["linearization_inputs"]["initial"]["path"],
                    "--output", paths["run"] / name]
                code = command(name, argv, 7200, required=False)
                path = paths["run"] / name / "validation.json"
                try:
                    result = json.loads(path.read_text())
                    require(code == 0 and result.get("passed") is True and result.get("physical_evaluations") == 1,
                            "Native linearization gate did not pass")
                    require(result["native"]["sha256"] == journal["native"]["sha256"] and
                            result["solver"]["sha256"] == journal["solver"]["sha256"], "Linearization executable identity changed")
                    journal["steps"][-1]["validation"] = d.artifact(path)
                    outcomes.append(True)
                except Exception as error:
                    journal["steps"][-1]["validation_error"] = repr(error)
                    outcomes.append(False)
                save()
            journal["status"] = "completed" if all(outcomes) else "failed"
            save()
        except BaseException as error:
            journal.update(status="failed", error=type(error).__name__ + ": " + str(error))
            raise
        finally:
            with d.cleanup_signals():
                errors = []
                for owned in registry:
                    try:
                        owned.cleanup(force=owned.child.poll() is None)
                    except BaseException as error:
                        errors.append(repr(error))
                journal["final_cleanup"] = {"verified": not errors, "errors": errors, "commands": [v.last_cleanup for v in registry]}
                journal["finished_at"] = d.stamp()
                if errors:
                    journal["status"] = "failed"
                try:
                    save()
                finally:
                    for number, handler in handlers.items():
                        signal.signal(number, handler)
    print(json.dumps({"status": journal["status"], "pipeline": str(run / "pipeline.json")}))


if __name__ == "__main__":
    main()
