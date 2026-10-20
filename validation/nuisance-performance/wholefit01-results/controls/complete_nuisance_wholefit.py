#!/usr/bin/env python3
"""Wait for an existing controller, then report once without changing its work."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time

SCHEMA = "orbit-poc-nuisance-wholefit-completion-plan-v1"
FIELDS = {"schema", "freeze", "controller_launch", "helper", "checker", "python",
          "dependencies", "annotations", "report_directory", "cpu", "poll_seconds", "wait_seconds"}
THREADS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "BLIS_NUM_THREADS", "GOTO_NUM_THREADS")


def digest(path):
    path = Path(path)
    before = path.stat()
    identity = (path.resolve(), before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    after = path.stat()
    if identity != (path.resolve(), after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError("Pinned file changed while reading: " + str(path))
    return value.hexdigest()


def verify(pin):
    if not isinstance(pin, dict) or set(pin) != {"path", "sha256"}:
        raise ValueError("Pins require exactly path and sha256")
    if not Path(pin["path"]).is_absolute() or not re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]):
        raise ValueError("Invalid artifact pin")
    if digest(pin["path"]) != pin["sha256"]:
        raise ValueError("Pinned identity changed: " + pin["path"])
    return Path(pin["path"])


def read_json(path, limit=2 * 1024 * 1024):
    path = Path(path)
    if path.stat().st_size > limit:
        raise ValueError("Structured receipt exceeds size bound")
    before = digest(path)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != before:
        raise ValueError("Receipt changed during read")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError("Nonfinite JSON value: " + value)
    value = json.loads(data, object_pairs_hook=pairs, parse_constant=invalid)
    if not isinstance(value, dict):
        raise ValueError("Expected an object receipt")
    return value


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def process(pid):
    root = Path("/proc") / str(pid)
    try:
        raw = (root / "stat").read_text()
        fields = raw[raw.rfind(")") + 2:].split()
        return {"pid": pid, "start_ticks": int(fields[19]), "state": fields[0],
                "argv": [part.decode() for part in (root / "cmdline").read_bytes().split(b"\0") if part]}
    except (FileNotFoundError, ProcessLookupError):
        return None


def controller(plan, freeze, launch):
    verify(plan["freeze"])
    verify(plan["controller_launch"])
    if boot_id() != freeze["boot_id"] or boot_id() != launch["boot_id"]:
        raise ValueError("Controller boot identity changed")
    current = process(launch["pid"])
    if current is None:
        return "dead"
    if current["start_ticks"] != launch["start_ticks"]:
        raise ValueError("Controller PID was reused")
    if current["state"] == "Z":
        return "dead"
    if current["argv"] != launch["argv"]:
        raise ValueError("Controller command identity changed")
    return "alive"


def check_tools(plan):
    for name in ("helper", "checker", "python"):
        verify(plan[name])
    for pin in plan["dependencies"]:
        verify(pin)
    for annotation in plan["annotations"]:
        verify(annotation["observation"])
        verify(annotation["supervisor_snapshot"])


def check_annotations(plan, freeze, launch):
    annotations = plan["annotations"]
    if not isinstance(annotations, list) or len(annotations) > 1:
        raise ValueError("Expected at most one pinned clock annotation")
    for entry in annotations:
        if (not isinstance(entry, dict) or set(entry) != {"kind", "observation", "supervisor_snapshot"}
                or entry["kind"] != "clock_discrepancy"):
            raise ValueError("Unknown report annotation")
        observation = read_json(verify(entry["observation"]))
        snapshot = read_json(verify(entry["supervisor_snapshot"]))
        if (observation.get("schema") != "orbit-poc-clock-discrepancy-observation-v1" or
                snapshot.get("schema") != "orbit-poc-segmented-supervision-v1" or
                not isinstance(snapshot.get("supervisor"), dict) or
                snapshot["supervisor"].get("parent") != launch["pid"] or
                observation.get("boot_id") != freeze["boot_id"] or snapshot.get("boot_id") != freeze["boot_id"] or
                observation.get("controller_launch_sha256") != plan["controller_launch"]["sha256"] or
                observation.get("controller_pid") != launch["pid"] or
                observation.get("controller_start_ticks") != launch["start_ticks"] or
                observation.get("supervisor_capture_sha256") != entry["supervisor_snapshot"]["sha256"] or
                observation.get("supervisor_elapsed_seconds") != snapshot.get("elapsed_seconds")):
            raise ValueError("Clock annotation controller/snapshot attribution differs")
        for name in ("supervisor_elapsed_seconds", "utc_since_controller_launch_seconds", "difference_seconds"):
            if type(observation.get(name)) not in (int, float) or not math.isfinite(observation[name]):
                raise ValueError("Invalid clock observation")


def load_plan(path, expected):
    verify({"path": str(Path(path).resolve()), "sha256": expected})
    plan = read_json(path)
    if set(plan) != FIELDS or plan["schema"] != SCHEMA or type(plan["cpu"]) is not int or plan["cpu"] != 4:
        raise ValueError("Unsupported completion plan")
    for name, lower, upper in (("poll_seconds", .01, 30), ("wait_seconds", 0, 86400)):
        if type(plan[name]) not in (int, float) or not math.isfinite(plan[name]) or not lower <= plan[name] <= upper:
            raise ValueError("Invalid bounded wait")
    if not isinstance(plan["dependencies"], list):
        raise ValueError("Dependency pins are required")
    all_pins = [plan[k] for k in ("helper", "checker", "python")] + plan["dependencies"]
    paths = [p["path"] for p in all_pins]
    if len(paths) != len(set(paths)):
        raise ValueError("Duplicate tool dependency path")
    checker_parent = Path(plan["checker"]["path"]).parent
    required = {str(checker_parent / name) for name in
                ("check_nuisance_performance_pair.py", "analyze_nuisance_profile.py")}
    if not required <= {p["path"] for p in plan["dependencies"]}:
        raise ValueError("The checker imports two pinned sibling scripts")
    if Path(plan["helper"]["path"]).resolve() != Path(__file__).resolve():
        raise ValueError("Completion helper path differs")
    freeze = read_json(verify(plan["freeze"]))
    launch = read_json(verify(plan["controller_launch"]))
    root = Path(plan["freeze"]["path"]).resolve().parent
    if (Path(plan["freeze"]["path"]).name != "freeze.json" or
            freeze.get("schema") != "orbit-poc-nuisance-wholefit-freeze-v1" or
            Path(freeze["root"]) != root or Path(plan["controller_launch"]["path"]).resolve().parent != root or
            launch.get("freeze_sha256") != plan["freeze"]["sha256"] or
            launch.get("schema") != "orbit-poc-wholefit-controller-launch-v1" or
            type(launch.get("pid")) is not int or launch["pid"] <= 0 or
            type(launch.get("start_ticks")) is not int or launch["start_ticks"] < 0 or
            not isinstance(launch.get("argv"), list) or not launch["argv"]):
        raise ValueError("Controller launch attribution differs")
    check_annotations(plan, freeze, launch)
    check_tools(plan)
    if [(j["name"], j["cache"]) for j in freeze["jobs"]] != [("cache1", 1), ("cache0", 0)]:
        raise ValueError("Expected the predeclared two-attempt order")
    report = Path(plan["report_directory"])
    protected = [root, Path(freeze["source_root"]).resolve(), checker_parent.resolve()]
    if not report.is_absolute() or report != report.resolve() or not report.parent.is_dir():
        raise ValueError("Report requires a canonical absolute directory with an existing parent")
    if any(report.is_relative_to(p) or p.is_relative_to(report) for p in protected):
        raise ValueError("Report directory overlaps read-only execution inputs")
    if report.exists():
        raise ValueError("Refusing to overwrite an existing report directory")
    return plan, freeze, launch, root, report


def terminal(root, freeze, freeze_sha):
    complete, stopped = root / "execution-complete.json", root / "execution-stopped.json"
    if complete.exists() and stopped.exists():
        raise ValueError("Contradictory terminal controller receipts")
    path = complete if complete.exists() else stopped if stopped.exists() else None
    if path is None:
        return None
    value = read_json(path)
    expected = [j["name"] for j in freeze["jobs"]]
    outcomes = value.get("outcomes")
    if (not isinstance(outcomes, list) or not 1 <= len(outcomes) <= len(expected) or
            any(not isinstance(x, dict) for x in outcomes) or
            [x.get("name") for x in outcomes] != expected[:len(outcomes)] or
            any(not re.fullmatch(r"[0-9a-f]{64}", str(x.get("result_sha256", ""))) for x in outcomes)):
        raise ValueError("Invalid terminal controller outcomes")
    if path == complete:
        if value.get("all_attempts_executed") is not True or len(outcomes) != 2 or value.get("freeze_sha256") != freeze_sha:
            raise ValueError("Invalid execution-complete attribution")
    elif value.get("all_attempts_executed") is not False:
        raise ValueError("Invalid execution-stopped attribution")
    return {"kind": "execution_complete" if path == complete else "execution_stopped",
            "receipt": {"path": str(path), "sha256": digest(path)}}


def wait_controller(plan, freeze, launch, root):
    deadline = time.monotonic() + plan["wait_seconds"]
    while True:
        lifecycle = controller(plan, freeze, launch)
        try:
            ended = terminal(root, freeze, plan["freeze"]["sha256"])
        except (ValueError, OSError) as error:
            if lifecycle == "dead":
                return {"kind": "controller_dead", "terminal_receipt_issue": str(error)}
            ended = None  # An exclusive-create receipt may still be being written.
        if ended:
            return {**ended, "controller_status": lifecycle}
        if lifecycle == "dead":
            return {"kind": "controller_dead", "controller_status": lifecycle}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {"kind": "wait_expired", "controller_status": lifecycle}
        time.sleep(min(plan["poll_seconds"], remaining))


def closed_attempts(root, freeze, freeze_sha):
    """Only small terminal receipts; never enumerate/read point or row trees."""
    attempts = []
    for job in freeze["jobs"]:
        directory = root / job["name"]
        row = {"name": job["name"], "outcome": "not_started", "closed": True}
        if directory.exists():
            row.update(outcome="unclosed_or_unknown", closed=False)
            try:
                supervisor = read_json(directory / "supervisor.json")
                supervisor_plan = read_json(directory / "supervisor.plan.json")
                post = read_json(directory / "post-input-check.json")
                result = read_json(directory / "result.json")
                argv = [freeze["python"]["path"], "-s", "-B", freeze["worker"]["path"],
                        freeze["source_root"], str(directory / "request.json"),
                        str(directory / "worker-result.json"), str(job["cache"]),
                        str(root / "freeze.json"), freeze_sha]
                if (supervisor.get("status") not in
                        {"complete", "timeout", "memory_limit", "disk_limit", "interrupted", "failed"} or
                        supervisor.get("owned_process_group_cleaned") is not True or
                        not isinstance(supervisor.get("cleanup"), dict) or
                        supervisor["cleanup"].get("verified") is not True or
                        supervisor.get("boot_id") != freeze["boot_id"] or
                        supervisor_plan.get("boot_id") != freeze["boot_id"] or
                        supervisor.get("argv") != argv or supervisor_plan.get("argv") != argv or
                        supervisor_plan.get("working_directory") != str(directory) or
                        supervisor.get("plan_sha256") != digest(directory / "supervisor.plan.json") or
                        post.get("verified") is not True or post.get("freeze_sha256") != freeze_sha or
                        post.get("pinned_file_count") != len(freeze["pinned_files"]) or
                        result.get("harness_execution") != supervisor or result.get("freeze_sha256") != freeze_sha or
                        result.get("request_sha256") != job["request"]["sha256"]):
                    raise ValueError("Terminal cleanup/attribution is unverified")
                row.update(outcome="closed_pending_checker", closed=True)
            except (OSError, ValueError, TypeError, KeyError) as error:
                row["issue"] = str(error)
        attempts.append(row)
    return {"safe_to_analyze": all(r["closed"] for r in attempts), "attempts": attempts}


def invoke_checker(plan, root, report, freeze):
    check_tools(plan)
    argv = [plan["python"]["path"], "-s", "-B", plan["checker"]["path"], str(root),
            "--output", str(report / "checker.json")]
    environment = {k: v for k, v in os.environ.items()
                   if k not in ("PYTHONPATH", "PYTHONHOME") and not k.startswith(("ORBIT_POC_", "LD_"))}
    environment.update({key: "1" for key in THREADS})
    environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
    if freeze.get("environment", {}).get("LD_LIBRARY_PATH"):
        environment["LD_LIBRARY_PATH"] = freeze["environment"]["LD_LIBRARY_PATH"]
    save(report / "checker-invocation.json", {"argv": argv, "cpu": 4, "threads": 1,
                                              "checker": plan["checker"], "retry": False})
    with (report / "checker.stdout").open("x") as stdout, (report / "checker.stderr").open("x") as stderr:
        # No timeout/kill: this helper never signals any process. The checker is read-only.
        execution = subprocess.run(argv, env=environment, cwd=report, stdout=stdout, stderr=stderr)
    check_tools(plan)
    save(report / "checker-execution.json", {"returncode": execution.returncode})
    result = read_json(report / "checker.json", limit=64 * 1024 * 1024)
    if (result.get("schema") != "orbit-poc-nuisance-wholefit-analysis-v1" or
            result.get("analysis_status") not in ("valid", "pending", "invalid") or
            not isinstance(result.get("runs"), list) or any(not isinstance(r, dict) for r in result["runs"]) or
            not isinstance(result.get("scientific_equivalence"), dict) or
            execution.returncode != (0 if result["analysis_status"] == "valid" else 2)):
        raise ValueError("Checker execution and report attribution disagree")
    return result


def finish(report, freeze, observation, result, issue=None, annotations=None):
    reported = {r.get("name"): r for r in (result or {}).get("runs", [])}
    keys = ("outcome", "analysis_status", "scientific_complete", "accepted_covariance",
            "wall_seconds", "peak_process_tree_rss_bytes", "issues")
    attempts = []
    for job in freeze["jobs"]:
        raw = reported.get(job["name"])
        row = {"name": job["name"], "cache": job["cache"]}
        row.update({k: raw.get(k) for k in keys} if raw else {
            "outcome": "not_established", "analysis_status": "not_reported",
            "scientific_complete": False, "accepted_covariance": False,
            "issues": ["The checker has not established an outcome for this planned attempt."]})
        if raw is None:
            observed = next((r for r in observation.get("attempts", []) if r["name"] == job["name"]), None)
            if observed:
                row["outcome"] = observed["outcome"]
                if observed.get("issue"):
                    row["issues"].append(observed["issue"])
        attempts.append(row)
    summary = {"schema": "orbit-poc-nuisance-wholefit-completion-report-v1",
               "created_at": datetime.now(timezone.utc).isoformat(), "observation": observation,
               "checker_invoked": (report / "checker-invocation.json").exists(), "issue": issue,
               "analysis_status": (result or {}).get("analysis_status", "not_run"),
               "scientific_equivalence": (result or {}).get("scientific_equivalence", {"status": "not_evaluable"}),
               "whole_fit_complete_pair": (result or {}).get("whole_fit_complete_pair", False),
               "attempts": attempts, "checker_issues": (result or {}).get("issues", []),
               "annotations": annotations or [],
               "timing_comparison": "compromised" if annotations else "not_established",
               "utc_two_hour_budget_compliance": "not_established", "speedup_claim": None,
               "release_authority": False, "independent_outcome_audit": "pending",
               "scope": "Passive one-shot reporting. Checker decisions are unchanged; controller death is not fit completion. Missing or uncertain arms remain unestablished."}
    save(report / "summary.json", summary)
    esc = lambda value: html.escape(str(value))
    rows = "".join("<tr>" + "".join("<td>" + esc(row.get(key, "unknown")) + "</td>"
                   for key in ("name", "outcome", "analysis_status", "scientific_complete", "accepted_covariance", "wall_seconds")) + "</tr>"
                   for row in attempts)
    timing_notice = ("<p><strong>Timing comparison is compromised.</strong> A pinned observation records a discrepancy between elapsed UTC and supervisor time; its cause is unverified. The supervisor continues to enforce its unchanged monotonic 7200-second limit, but compliance with a two-hour elapsed-UTC budget is not established. This pair supports no speedup conclusion or full benchmark acceptance. Numerical outcomes are reported separately below.</p>"
                     if annotations else "<p>Timing and elapsed-UTC budget compliance are not established by this report; no speedup conclusion or full benchmark acceptance is made.</p>")
    body = ("<!doctype html><meta charset='utf-8'><title>Nuisance whole-fit report</title>"
            "<style>body{font:16px system-ui;max-width:1100px;margin:3em auto;padding:0 1em}td,th{padding:.6em;border:1px solid #bbb}table{border-collapse:collapse}pre{white-space:pre-wrap}</style>"
            "<h1>Nuisance whole-fit report</h1><p>Controller observation: " + esc(observation.get("kind")) +
            ". Receipt analysis: " + esc(summary["analysis_status"]) + ".</p>"
            + timing_notice +
            "<p><strong>A valid receipt analysis is not a successful fit or a passing fix. Two valid timeouts remain two failed fits.</strong></p>"
            "<p>Whole-fit complete pair: " + esc(summary["whole_fit_complete_pair"]) + ". Scientific equivalence: " +
            esc(summary["scientific_equivalence"].get("status")) + ".</p>"
            "<p>Independent audit of actual outcomes: <strong>pending</strong>. Reviews of the checker and this reporting helper are not an independent audit of the experiment results. This report has no release authority.</p>"
            "<table><tr><th>Attempt</th><th>Outcome</th><th>Evidence</th><th>Scientific completion</th><th>Accepted covariance</th><th>Wall seconds</th></tr>" + rows + "</table>"
            "<p>Controller disappearance and completed nuisance profiles do not establish full-fit convergence. Pending, invalid or partial-prefix evidence cannot authorize covariance. One observed off/on pair provides no statistical speedup claim. CPU admission was cooperative, not an exclusive machine reservation.</p>"
            "<p><a href='summary.json'>Summary JSON</a>" + (" · <a href='checker.json'>Unchanged checker report</a>" if (report / "checker.json").exists() else "") + "</p>"
            + ("<p><a href='annotation-0-observation.json'>Preserved clock observation</a> · <a href='annotation-0-supervisor_snapshot.json'>Preserved supervisor snapshot</a></p>" if annotations else "") +
            "<pre>" + esc(json.dumps({"helper_issue": issue, "controller_receipt_issue": observation.get("terminal_receipt_issue"), "checker_issues": summary["checker_issues"]}, indent=2)) + "</pre>")
    with (report / "index.html").open("x") as stream:
        stream.write(body + "\n")
    return summary


def run(path, expected):
    plan, freeze, launch, root, report = load_plan(path, expected)
    os.sched_setaffinity(0, {4})
    if os.sched_getaffinity(0) != {4}:
        raise ValueError("CPU4 unavailable")
    controller(plan, freeze, launch)  # Reject boot/PID changes before creating a report.
    report.mkdir()
    save(report / "plan.json", plan)
    result, observation, issue = None, {"kind": "refused"}, None
    try:
        for number, annotation in enumerate(plan["annotations"]):
            for key in ("observation", "supervisor_snapshot"):
                source = verify(annotation[key])
                data = source.read_bytes()
                if hashlib.sha256(data).hexdigest() != annotation[key]["sha256"]:
                    raise ValueError("Annotation changed while copying")
                with (report / ("annotation-" + str(number) + "-" + key + ".json")).open("xb") as stream:
                    stream.write(data)
        observation = wait_controller(plan, freeze, launch, root)
        verify({"path": str(Path(path).resolve()), "sha256": expected})
        check_tools(plan)
        if observation["kind"] != "wait_expired":
            controller(plan, freeze, launch)
            closure = closed_attempts(root, freeze, plan["freeze"]["sha256"])
            observation.update(closure)
            if closure["safe_to_analyze"]:
                result = invoke_checker(plan, root, report, freeze)
                verify({"path": str(Path(path).resolve()), "sha256": expected})
                controller(plan, freeze, launch)
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
        issue = type(error).__name__ + ": " + str(error)
        result = None
        observation = {**observation, "reporting_refused": True}
    return finish(report, freeze, observation, result, issue, plan["annotations"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    args = parser.parse_args()
    result = run(args.plan, args.plan_sha256)
    print(json.dumps({k: result[k] for k in ("analysis_status", "whole_fit_complete_pair", "checker_invoked", "issue")}))
    return 0 if result["issue"] is None else 2


if __name__ == "__main__":
    raise SystemExit(main())
