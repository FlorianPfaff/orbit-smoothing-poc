#!/usr/bin/env python3
"""Summarize existing, closed nuisance-fit receipts without running an estimator.

This tool reports recorded evidence, not convergence/covariance certification.
Missing timings remain unknown, and child CPU is never called profile wall time.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
from datetime import datetime, timezone

POINT = re.compile(r"point-\d+-.+")
SEARCH = re.compile(r"qr\.(\d+)\.nuisance_line_search\.json")
PERFORMANCE = re.compile(r"qr\.(\d+)\.nuisance_performance\.json")
TERMINAL = {"complete", "failed", "timeout", "interrupted", "memory_limit", "disk_limit", "resource_limit",
            "native_failure", "nuisance_failure", "closure_failed", "invalid_objective",
            "rank_deficient", "unresolved_rank", "iteration_limit", "step_stalled",
            "changed_support", "stale_covariance", "invalid_covariance", "missing_factor",
            "parameter_order", "worker_failed"}


def artifact(path):
    path = Path(path).resolve(strict=True)
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        data = stream.read()
        after = os.fstat(stream.fileno())
    identity = lambda stat: (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    if identity(before) != identity(after) or len(data) != after.st_size:
        raise ValueError("Input changed while being read: " + str(path))
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}, data


def finite_nonnegative(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def metric(records, key):
    """Keep an explicitly partial sum distinct from a complete or absent sum."""
    values = [item[key] for item in records if finite_nonnegative(item.get(key))]
    missing = len(records) - len(values)
    return {"recorded_sum": math.fsum(values) if values else None,
            "recorded_count": len(values), "record_count": len(records),
            "unknown_count": missing,
            "coverage": "unknown" if not records or not values else "partial" if missing else "complete"}


def cpu_summary(records):
    total = metric([{ "cpu_seconds": item["child_user_seconds"] + item["child_system_seconds"]}
                    if finite_nonnegative(item.get("child_user_seconds"))
                    and finite_nonnegative(item.get("child_system_seconds")) else {}
                    for item in records], "cpu_seconds")
    return {"user_seconds": metric(records, "child_user_seconds"),
            "system_seconds": metric(records, "child_system_seconds"),
            "total_cpu_seconds": total,
            "scope": "Recorded child CPU only; not elapsed wall time or a complete profile-stage breakdown."}


def row_build_summary(rows):
    measured = [row if row.get("available") is True else {} for row in rows]
    return {"build_wall_seconds": metric(measured, "build_wall_seconds"),
            "observation_design_wall_seconds": metric(measured, "observation_design_wall_seconds"),
            "observation_design_calls": metric(measured, "observation_design_calls"),
            "interpolation_wall_seconds": metric(measured, "interpolation_wall_seconds"),
            "interpolation_calls": metric(measured, "interpolation_calls"),
            "interpolation_cache_hits": metric(measured, "interpolation_cache_hits"),
            "interpolation_evaluations": metric(measured, "interpolation_evaluations"),
            "cache_enabled_build_count": sum(row.get("interpolation_cache") is True for row in measured),
            "completed_count": sum(row.get("completed") is True for row in rows),
            "incomplete_count": sum(row.get("completed") is False and row.get("available") is True for row in rows),
            "cost_only_count": sum(row.get("cost_only") is True and row.get("available") is True for row in rows),
            "scope": "Interpolation time is included in observation-design wall time, which is included in row-build wall time; do not add them."}


def performance_summary(sidecars):
    groups = {name: [] for name in ("ordinary_trials", "arithmetic_audits", "probe_rounds", "zero_update_replay")}
    for sidecar in sidecars:
        groups["zero_update_replay"].append(sidecar.get("zero_update_replay", {}))
        for name in ("ordinary_trials", "arithmetic_audits"):
            groups[name].extend(sidecar.get(name, []))
        groups["probe_rounds"].extend(item for probe in sidecar.get("probe_rounds", []) for item in probe)
    return {"sidecar_count": sum(bool(item) for item in sidecars), "search_record_count": len(sidecars),
        "parent_row_build": row_build_summary([item.get("parent_row_build", {}) for item in sidecars]),
        "child_categories": {name: {"wall_seconds": metric(items, "wall_seconds"),
             "child_cpu": cpu_summary(items),
             "row_build": row_build_summary([item.get("row_build", {}) for item in items]),
             "failed_or_unknown_status_count": sum(type(item.get("status")) is not int or item["status"] != 0 for item in items)}
             for name, items in groups.items()},
        "scope": "Optional sidecars only; categories are disjoint. Probe history is counted once. "
                 "Child row-build time is nested in child wall time; these diagnostics overlap profile elapsed time. "
                 "Do not add sidecar child CPU to the canonical trial/replay CPU summaries. "
                 "Final linearization, nuisance solves, local recovery and parameter updates are not covered by search sidecars."}


def validate_performance(value, search):
    if value.get("schema") != "orbit-poc-nuisance-performance-v1":
        raise ValueError("Unknown nuisance performance schema")
    for name in ("parent_row_build", "zero_update_replay"):
        if not isinstance(value.get(name), dict):
            raise ValueError("Missing performance " + name)
    for name in ("ordinary_trials", "arithmetic_audits"):
        if not isinstance(value.get(name), list) or not all(isinstance(item, dict) for item in value[name]):
            raise ValueError("Invalid performance " + name)
    if not isinstance(value.get("probe_rounds"), list) or not all(isinstance(items, list)
            and all(isinstance(item, dict) for item in items) for items in value["probe_rounds"]):
        raise ValueError("Invalid performance probe history")
    if not isinstance(search.get("trials"), list) or not all(isinstance(item, dict) for item in search["trials"]):
        raise ValueError("Performance sidecar has no valid line-search trial identity")
    if len(value["ordinary_trials"]) != len(search["trials"]):
        raise ValueError("Performance/line-search trial counts disagree")
    children = [value["zero_update_replay"], *value["ordinary_trials"], *value["arithmetic_audits"],
                *(item for items in value["probe_rounds"] for item in items)]
    if any(not isinstance(item.get("row_build"), dict) for item in children):
        raise ValueError("Missing performance child row-build metrics")
    for extra, primary in zip(value["ordinary_trials"], search.get("trials", [])):
        merge_performance_timing(primary, extra)
    merge_performance_timing(search.get("zero_update_replay", {}), value["zero_update_replay"])
    canonical_audits = search.get("nuisance_floor_audit", [])
    if not isinstance(canonical_audits, list) or not all(isinstance(item, dict) for item in canonical_audits):
        raise ValueError("Invalid canonical nuisance-floor audit")
    arithmetic = [item for item in canonical_audits if item.get("kind") == "equivalent_arithmetic"]
    if len(arithmetic) != len(value["arithmetic_audits"]):
        raise ValueError("Performance/canonical arithmetic-audit counts disagree")
    for extra, primary in zip(value["arithmetic_audits"], arithmetic):
        if type(primary.get("status")) is not int or primary["status"] != extra.get("status") or type(extra.get("status")) is not int:
            raise ValueError("Performance/canonical arithmetic-audit status disagrees")
    probes = [item for item in canonical_audits if item.get("kind") == "two_amplitude_symmetric_nuisance_probe"]
    if len(probes) > 1:
        raise ValueError("Multiple canonical symmetric-probe records")
    history = probes[0].get("probe_history", []) if probes else []
    count = search.get("completed_probe_rounds", 0)
    if (type(count) is not int or not isinstance(history, list) or count != len(history)
            or count != len(value["probe_rounds"])):
        raise ValueError("Performance/canonical probe-round counts disagree")
    for extra_round, primary_round in zip(value["probe_rounds"], history):
        primary = primary_round.get("probes") if isinstance(primary_round, dict) else None
        if not isinstance(primary, list) or len(primary) != len(extra_round):
            raise ValueError("Performance/canonical probe counts disagree")
        for extra, original in zip(extra_round, primary):
            if not isinstance(original, dict) or type(original.get("status")) is not int or type(extra.get("status")) is not int or original["status"] != extra["status"]:
                raise ValueError("Performance/canonical probe status disagrees")
    return value


def merge_performance_timing(primary, extra):
    result = dict(primary)
    for key in ("status", "child_user_seconds", "child_system_seconds", "peak_child_rss_bytes"):
        if key in extra and key in primary and (type(extra[key]) is not type(primary[key]) or extra[key] != primary[key]):
            # Integer and float times may both represent the same finite number.
            if key == "status" or not finite_nonnegative(extra[key]) or not finite_nonnegative(primary[key]) or extra[key] != primary[key]:
                raise ValueError("Performance/line-search measurement conflict: " + key)
        if key in extra and key not in primary:
            result[key] = extra[key]
    return result


def supervisor_matches(supervisor, terminal_status):
    """A successful worker exit can carry a failed numerical result."""
    status = supervisor.get("status")
    return (status in TERMINAL and (status == terminal_status
            or (status == "complete" and type(supervisor.get("returncode")) is int and supervisor["returncode"] == 0)
            or (terminal_status == "failed" and supervisor.get("owned_process_group_cleaned") is False)))


def analyze(roots, *, terminal, supervisor=None, manifests=()):
    provenance, issues = {}, []

    def register(pin):
        if pin["path"] in provenance and pin != provenance[pin["path"]]:
            raise ValueError("Input changed during analysis: " + pin["path"])
        provenance[pin["path"]] = pin

    def read(path):
        pin, data = artifact(path)
        register(pin)
        try:
            def invalid_constant(token):
                raise ValueError("Nonfinite JSON number: " + token)
            def finite_float(token):
                value = float(token)
                if not math.isfinite(value):
                    invalid_constant(token)
                return value
            value = json.loads(data, parse_constant=invalid_constant, parse_float=finite_float)
            if not isinstance(value, dict):
                raise ValueError("expected a JSON object")
            return value
        except (ValueError, UnicodeDecodeError) as error:
            issues.append({"path": pin["path"], "error": str(error), "sha256": pin["sha256"]})
            return None

    terminal_value = read(terminal)
    if terminal_value is None or terminal_value.get("status") not in TERMINAL:
        raise ValueError("A recognized terminal fit receipt is required; running/missing status is not closed evidence")
    supervisor_value = read(supervisor) if supervisor else None
    if supervisor_value is not None and not supervisor_matches(supervisor_value, terminal_value["status"]):
        raise ValueError("Supervisor and terminal receipt statuses disagree")
    manifest_checks = []
    for path in manifests:
        path = Path(path).resolve(strict=True)
        value = read(path)
        if not value or not isinstance(value.get("files"), list):
            raise ValueError("Capture manifest must contain a files list")
        count = 0
        for row in value["files"]:
            relative = Path(row["relative"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Capture manifest path escapes its directory")
            pin, _ = artifact(path.parent / relative)
            if pin["sha256"] != row["sha256"] or pin["bytes"] != row["bytes"]:
                raise ValueError("Capture manifest input identity mismatch: " + str(relative))
            register(pin)
            count += 1
        manifest_checks.append({"path": str(path), "verified_files": count})

    files = {}
    for root in roots:
        root = Path(root).resolve(strict=True)
        for guard_name in ("supervisor.json", "result-record.json", "result.json"):
            guard_path = root / guard_name
            if not guard_path.is_file():
                continue
            guard = read(guard_path)
            compatible = (supervisor_matches(guard, terminal_value["status"]) if guard_name == "supervisor.json" and guard is not None
                          else guard is not None and guard.get("status") == terminal_value["status"])
            if guard is None or guard.get("status") not in TERMINAL or not compatible:
                raise ValueError("Captured root has live, invalid or conflicting terminal evidence")
            if guard.get("attempt_id") and terminal_value.get("attempt_id") and guard["attempt_id"] != terminal_value["attempt_id"]:
                raise ValueError("Captured root and terminal attempt identities disagree")
            expected_result = terminal_value.get("result")
            if guard_name == "result.json" and isinstance(expected_result, dict) and expected_result.get("sha256"):
                if artifact(guard_path)[0]["sha256"] != expected_result["sha256"]:
                    raise ValueError("Captured full result differs from terminal result pin")
        point_dirs = [root] if POINT.fullmatch(root.name) else sorted(
            item for item in root.iterdir() if item.is_dir() and POINT.fullmatch(item.name))
        candidates = [("iterations.json", root / "iterations.json")] if (root / "iterations.json").is_file() else []
        for folder in point_dirs:
            for path in folder.iterdir():
                if path.is_file() and (path.name in {"closure.json", "profile.execution.json", "qr.profile.json"}
                                       or SEARCH.fullmatch(path.name) or PERFORMANCE.fullmatch(path.name)):
                    candidates.append((folder.name + "/" + path.name, path))
        for relative, path in candidates:
            pin, _ = artifact(path)
            if relative in files and pin["sha256"] != artifact(files[relative])[0]["sha256"]:
                raise ValueError("Conflicting captured receipt for " + relative)
            # Pin duplicate copies too, but count their identical payload once.
            register(pin)
            files.setdefault(relative, path)

    loaded = {key: read(path) for key, path in sorted(files.items())}
    points, all_trials, all_replays, executions, all_performance = [], [], [], [], []
    execution_attempts = set()
    for name in sorted({key.split("/")[0] for key in loaded if "/" in key}):
        execution = loaded.get(name + "/profile.execution.json")
        command = execution.get("command") if execution else None
        if isinstance(command, list) and len(command) == 2 and isinstance(command[1], str):
            profile_path = Path(command[1])
            if profile_path.name != "profile.xml" or profile_path.parent.name != name:
                raise ValueError("Profile execution command does not match the captured point")
            execution_attempts.add(profile_path.parent.parent.name)
        profile = loaded.get(name + "/qr.profile.json")
        closure = loaded.get(name + "/closure.json")
        searches = [(int(SEARCH.fullmatch(Path(key).name)[1]), key, value)
                    for key, value in loaded.items() if key.startswith(name + "/")
                    and SEARCH.fullmatch(Path(key).name)]
        searches.sort()
        trials, replays, outcomes, performance = [], [], [], []
        performance_keys = {key for key in loaded if key.startswith(name + "/") and PERFORMANCE.fullmatch(Path(key).name)}
        for generation, key, search in searches:
            sidecar_key = key.replace(".nuisance_line_search.json", ".nuisance_performance.json")
            sidecar = loaded.get(sidecar_key)
            performance_keys.discard(sidecar_key)
            if search is None:
                outcomes.append({"generation": generation, "receipt": key, "status": "invalid_receipt"})
                performance.append({})
                if sidecar is not None:
                    issues.append({"path": str(files[sidecar_key]), "error": "Performance sidecar has no valid line-search identity"})
                continue
            child_trials = search.get("trials")
            if not isinstance(child_trials, list) or not all(isinstance(item, dict) for item in child_trials):
                issues.append({"path": str(files[key]), "error": "Missing or malformed trial list"})
                child_trials = []
            replay = search.get("zero_update_replay")
            if sidecar is not None:
                sidecar = validate_performance(sidecar, search)
                child_trials = [merge_performance_timing(primary, extra)
                                for primary, extra in zip(child_trials, sidecar["ordinary_trials"])]
                replay = merge_performance_timing(replay if isinstance(replay, dict) else {}, sidecar["zero_update_replay"])
            performance.append(sidecar or {})
            replays.append(replay if isinstance(replay, dict) else {})
            trials.extend(child_trials)
            outcomes.append({"generation": generation, "receipt": key,
                "accepted": search.get("accepted"), "stationary_without_update": search.get("stationary_without_update"),
                "floor_limited": search.get("nuisance_floor_limited"),
                "floor_rejection": search.get("floor_rejection"),
                "trial_statuses": [item.get("status") for item in child_trials],
                "failed_trials": [{"index": i, "status": item.get("status"), "alpha": item.get("alpha"),
                                   "error": item.get("error")} for i, item in enumerate(child_trials)
                                  if type(item.get("status")) is not int or item["status"] != 0],
                "zero_replay_status": replay.get("status") if isinstance(replay, dict) else None})
        for key in sorted(performance_keys):
            issues.append({"path": str(files[key]), "error": "Orphan performance sidecar excluded from timing totals"})
        all_trials.extend(trials)
        all_replays.extend(replays)
        all_performance.extend(performance)
        executions.append(execution or {})
        iterations = profile.get("iterations") if profile else None
        history = profile.get("history") if profile else None
        strict = (profile.get("nuisance_converged") is True and profile.get("nuisance_floor_limited") is False) if profile else None
        points.append({"point": name, "profile_execution_recorded": execution is not None,
            "profile_returncode": execution.get("returncode") if execution else None,
            "profile_timed_out": execution.get("timed_out") if execution else None,
            "profile_wall_seconds": execution.get("elapsed_seconds") if execution and finite_nonnegative(execution.get("elapsed_seconds")) else None,
            "native_binary_sha256": execution.get("native_binary_sha256") if execution else None,
            "profile_configuration_sha256": execution.get("config_sha256") if execution else None,
            "closure_converged_reported": closure.get("converged") if closure else None,
            "tighter_closure": closure.get("tighter") if closure else None,
            "nuisance_iterations": iterations, "strict_nuisance_converged_reported": strict,
            "floor_limited_reported": profile.get("nuisance_floor_limited") if profile else None,
            "threshold_m": profile.get("threshold_m") if profile else None,
            "maximum_update_m": profile.get("maximum_update_m") if profile else None,
            "update_history_m": [row.get("maximum_update_m") for row in history if isinstance(row, dict)] if isinstance(history, list) else None,
            "search_receipt_count": len(searches),
            "search_receipts_match_reported_iterations": len(searches) == iterations if isinstance(iterations, int) else None,
            "trial_child_cpu": cpu_summary(trials), "zero_replay_child_cpu": cpu_summary(replays),
            "performance": performance_summary(performance),
            "line_search_outcomes": outcomes})

    if len(execution_attempts) > 1 or (terminal_value.get("attempt_id") and execution_attempts
            and execution_attempts != {terminal_value["attempt_id"]}):
        raise ValueError("Profile execution and terminal attempt identities disagree")
    wall = metric(executions, "elapsed_seconds")
    whole_wall = supervisor_value.get("elapsed_seconds") if supervisor_value else None
    whole_wall = whole_wall if finite_nonnegative(whole_wall) else None
    iteration_record = loaded.get("iterations.json")
    trial_points = [point["point"] for point in points if re.fullmatch(r"point-\d+-trial-\d+", point["point"])]
    count = iteration_record.get("trial_evaluations") if iteration_record else None
    lm_evidenced = bool(trial_points) or (isinstance(count, int) and not isinstance(count, bool) and count > 0)
    phase = {"lm_trial_evidenced": lm_evidenced,
        "lm_trial_count_reported": count, "lm_trial_points": trial_points,
        "scope": "Absence of captured LM evidence does not prove no LM work occurred; captures may be partial.",
        "observed_point_labels": [point["point"] for point in points]}
    for path, original in provenance.items():
        if artifact(path)[0] != original:
            raise ValueError("Input changed during analysis: " + path)
    return {"schema": "orbit-poc-nuisance-profile-analysis-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "analyzer": artifact(__file__)[0],
        "scope": "Offline analysis of terminal-fit receipts; no estimator execution or benchmark mutation.",
        "terminal_status": terminal_value["status"],
        "attempt_id": terminal_value.get("attempt_id"), "job_sha256": terminal_value.get("job_sha256"),
        "recorded_execution_attempts": sorted(execution_attempts),
        "terminal_to_execution_identity": "matches" if execution_attempts and terminal_value.get("attempt_id") else "unknown",
        "whole_fit": {"converged_reported": terminal_value.get("converged"),
            "covariance_valid_reported": terminal_value.get("covariance_valid"),
            "error_reported": terminal_value.get("error"),
            "wall_seconds": whole_wall, "status": terminal_value["status"],
            "supervisor_process_status": supervisor_value.get("status") if supervisor_value else None,
            "cleanup_verified_reported": (supervisor_value or {}).get("cleanup", {}).get("verified")},
        "profile_wall_seconds": wall,
        "recorded_profile_wall_fraction_of_supervised_fit": wall["recorded_sum"] / whole_wall
            if wall["recorded_sum"] is not None and whole_wall and wall["recorded_sum"] <= whole_wall else None,
        "trial_child_cpu": cpu_summary(all_trials), "zero_replay_child_cpu": cpu_summary(all_replays),
        "performance": performance_summary(all_performance),
        "input_stability_checked": True,
        "phase_evidence": phase, "points": points, "input_issues": issues,
        "verified_capture_manifests": manifest_checks,
        "provenance": sorted(provenance.values(), key=lambda value: value["path"]),
        "limitations": ["Recorded nuisance convergence is not whole-fit convergence or covariance authorization.",
            "Timing sums cover available receipts only; missing or invalid metrics are unknown, not zero.",
            "No exact parent QR, likelihood, I/O or exhaustive cost breakdown is inferred.",
            "Terminal receipts and stable input files are checked; this offline tool does not verify current remote process liveness.",
            "This report does not certify native correctness, benchmark completeness or release readiness."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", type=Path, nargs="+", help="Closed fit directory or captured point-receipt roots")
    parser.add_argument("--terminal", type=Path, required=True, help="Terminal result.json or result-record.json")
    parser.add_argument("--supervisor", type=Path, help="Optional matching terminal supervisor receipt")
    parser.add_argument("--manifest", type=Path, action="append", default=[], help="Optional capture manifest to hash-verify")
    parser.add_argument("--output", type=Path, required=True, help="New JSON report; existing files are never replaced")
    args = parser.parse_args()
    result = analyze(args.roots, terminal=args.terminal, supervisor=args.supervisor, manifests=args.manifest)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
