#!/usr/bin/env python3
"""Summarize bounded, read-only captures; never execute or resume a fit."""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
from html import escape
import json
from pathlib import Path
import re


SCHEMAS = {
    "terminal": "v4-terminal-readonly-detail-v1",
    "points": "v4-terminal-point-details-v1",
    "search": "v4-nuisance-search-evidence-v1",
    "memory": "v4-memory-closure-details-v1",
}
PRETRIAL = ["initial", "repeat", "closure-refinement"]
CHILD_TIMEOUT = "Nuisance trial exceeded 300-second limit"
REPLAY_GUARD = "Nuisance zero-update replay changed the objective or cached state"
LIMIT = 40 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key: " + key)
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("Non-finite JSON number: " + value)


def read_capture(path, schema):
    path = Path(path).resolve()
    require(path.stat().st_size <= LIMIT, "Capture exceeds 40 MiB: " + str(path))
    raw = path.read_bytes()
    obj = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
    canonical(obj)  # Also reject overflow such as 1e999.
    require(obj.get("schema") == schema, "Unexpected schema: " + str(path))
    require(isinstance(obj.get("captured_at"), str), "Missing capture timestamp")
    return obj, {"path": str(path), "sha256": digest(raw), "bytes": len(raw),
                 "captured_at": obj["captured_at"]}


def source_basis(path):
    """Pin and check the actual ordered pretrial calls, rather than assume them."""
    path = Path(path).resolve()
    raw = path.read_bytes()
    tree = ast.parse(raw)
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "minimize"]
    require(len(functions) == 1, "Optimizer must define one minimize function")
    labels = []
    found = False
    for block in functions[0].body:
        if not isinstance(block, ast.Try):
            continue
        before = []
        for stmt in block.body:
            if isinstance(stmt, ast.While):
                found = True
                break
            before.append(stmt)
        if not found:
            continue
        for stmt in before:
            for call in ast.walk(stmt):
                if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                    continue
                if isinstance(call.func.value, ast.Name) and call.func.value.id == "model":
                    require(call.func.attr != "trial", "Optimizer has a trial before baseline checks")
                    if call.func.attr == "evaluate":
                        require(len(call.args) > 1 and isinstance(call.args[1], ast.Constant),
                                "Unrecognized optimizer evaluation label")
                        labels.append(call.args[1].value)
        break
    require(found and labels == PRETRIAL, "Optimizer pretrial ordering is not recognized")
    return {"path": str(path), "sha256": digest(raw), "bytes": len(raw),
            "ordered_evaluations_before_first_loop": labels,
            "scope": "Source-based stage inference; no optimizer execution was performed"}


def index_unique(items, key, label):
    require(isinstance(items, list), label + " must be a list")
    require(len(items) <= 1000, label + " exceeds bounded record count")
    result = {}
    for item in items:
        name = key(item)
        require(isinstance(name, (str, tuple)) and name not in result,
                "Duplicate or invalid " + label + " identity: " + str(name))
        result[name] = item
    return result


def captured_pin(record, attempt_id, filename):
    """Preserve collector pins; decoded JSON cannot reproduce original formatting."""
    require(isinstance(record, dict) and "content" in record, "Missing captured " + filename)
    path = Path(record.get("path", ""))
    require(attempt_id in path.parts and path.name == filename,
            "Cross-attempt or filename substitution: " + str(path))
    sha = record.get("sha256", "")
    require(isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha),
            "Invalid captured digest: " + filename)
    return {"path": str(path), "sha256": sha,
            "original_bytes": record.get("bytes"),
            "captured_content_sha256": digest(canonical(record["content"]))}


def summarize_point(point, attempt_id):
    name = point["point"]
    files = point.get("files")
    require(isinstance(files, list), "Missing point file listing")
    filenames = [f["name"] for f in files]
    require(len(filenames) == len(set(filenames)), "Duplicate point filename")
    docs = point.get("json", {})
    pins = {}
    for filename, doc in docs.items():
        pins[filename] = captured_pin(doc, attempt_id, filename)
        require(Path(doc["path"]).parent.name == name, "Cross-point JSON substitution")
    execution = docs.get("profile.execution.json", {}).get("content", {})
    profile = docs.get("qr.profile.json", {}).get("content", {})
    closure = docs.get("closure.json", {}).get("content", {})
    complete = (type(execution.get("returncode")) is int and execution["returncode"] == 0
                and execution.get("timed_out") is False)
    strict = (complete and profile.get("nuisance_converged") is True
              and profile.get("nuisance_floor_limited") is False)
    iterations = [int(m.group(1)) for f in filenames
                  if (m := re.fullmatch(r"qr\.(\d+)\.profile\.json", f))]
    log = point.get("logs", {}).get("profile.log", {})
    if log:
        require(Path(log.get("path", "")).parent.name == name
                and attempt_id in Path(log.get("path", "")).parts,
                "Cross-point log substitution")
    # Only the captured tail is examined; absence here is not a whole-log assertion.
    guard = REPLAY_GUARD in log.get("tail", "")
    if complete:
        stage = "native_profile_completed"
    elif "profile.log" in filenames or log:
        stage = "native_profile_entered_without_success_record"
    elif closure:
        stage = "physical_closure_record_present_profile_not_observed"
    else:
        stage = "point_created_closure_progress_unknown"
    return {"point": name, "stage": stage, "native_profile_completed": complete,
            "strict_nuisance_profile_completed": strict,
            "closure_converged": closure.get("converged"),
            "execution": {k: execution[k] for k in
                          ("returncode", "timed_out", "elapsed_seconds", "native_binary_sha256")
                          if k in execution},
            "profile": {k: profile[k] for k in ("iterations", "maximum_update_m",
                        "nuisance_converged", "nuisance_floor_limited") if k in profile},
            "last_intermediate_profile_file": max(iterations, default=None),
            "zero_replay_guard_in_captured_tail": guard,
            "record_pins": pins,
            "profile_log_excerpt": {"path": log.get("path"), "original_bytes": log.get("bytes"),
                                    "excerpt_only": True}}


def summarize_search(records, attempt_id):
    result = {"records": len(records), "trial_children": 0, "failed_trial_children": 0,
              "explicit_300s_trial_timeouts": 0, "failed_zero_update_replays": 0,
              "zero_update_replay_timeout_explicit": 0, "reported_trial_child_errors": {},
              "record_pins": []}
    errors = Counter()
    for rec in records:
        pin = captured_pin(rec, attempt_id, rec["name"])
        require(Path(rec["path"]).parent.name == rec["point"], "Cross-point search substitution")
        content = rec["content"]
        require(content.get("schema") == "orbit-poc-native-nuisance-line-search-v1",
                "Unexpected native search schema")
        replay = content.get("zero_update_replay", {})
        if replay.get("status") is not None and replay["status"] != 0:
            result["failed_zero_update_replays"] += 1
            if CHILD_TIMEOUT in replay.get("error", ""):
                result["zero_update_replay_timeout_explicit"] += 1
        for trial in content.get("trials", []):
            result["trial_children"] += 1
            if trial.get("status") is not None and trial["status"] != 0:
                result["failed_trial_children"] += 1
                error = trial.get("error", "")
                errors[error or "error_not_recorded"] += 1
                if error == CHILD_TIMEOUT:
                    result["explicit_300s_trial_timeouts"] += 1
        result["record_pins"].append({"point": rec["point"], "name": rec["name"], **pin})
    result["reported_trial_child_errors"] = dict(sorted(errors.items()))
    return result


def summarize_memory(record, attempt_id):
    """Nested closure capture refines, rather than guesses from, top-level absence."""
    result = []
    directories = index_unique(record.get("directories", []), lambda d: d["name"], "closure directory")
    for name, directory in sorted(directories.items()):
        log = directory.get("logs", {}).get("propagate.log", {})
        text = log.get("head", "") + "\n" + log.get("tail", "")
        if text:
            require(attempt_id in text and "/" + name + "/" in text,
                    "Cross-attempt closure log substitution")
        programs = re.findall(r"--- ([A-Za-z0-9_]+) ---", text)
        execution = {}
        captured = directory.get("logs", {}).get("propagate.execution.json", {})
        full = captured.get("head", "")
        if full and len(full.encode()) == captured.get("bytes"):
            execution = json.loads(full, object_pairs_hook=unique_object, parse_constant=reject_constant)
            command = execution.get("command", [])
            require(len(command) == 2 and attempt_id in Path(command[1]).parts
                    and Path(command[1]).parent.name == name, "Closure execution binding mismatch")
        complete = (type(execution.get("returncode")) is int and execution["returncode"] == 0
                    and execution.get("timed_out") is False)
        result.append({"directory": name,
            "last_native_program_in_captured_log": programs[-1] if programs else None,
            "variational_archive_write_observed": "write variational equation to file" in text,
            "native_execution_completed": complete,
            "execution": {k: execution[k] for k in ("returncode", "timed_out", "elapsed_seconds")
                          if k in execution},
            "captured_directory_sha256": digest(canonical(directory)),
            "scope": "Nested captured logs/files; last logged program is not an allocation traceback"})
    return result


def analyze(terminal_path, points_path, search_path, memory_path, optimizer_source):
    terminal, tp = read_capture(terminal_path, SCHEMAS["terminal"])
    points, pp = read_capture(points_path, SCHEMAS["points"])
    search, sp = read_capture(search_path, SCHEMAS["search"])
    memory, mp = read_capture(memory_path, SCHEMAS["memory"])
    manifest = terminal.get("manifest_hash")
    require(isinstance(manifest, str) and re.fullmatch(r"[0-9a-f]{64}", manifest),
            "Missing manifest hash")
    require(points.get("manifest_hash") == manifest, "Capture manifest mismatch")
    basis = source_basis(optimizer_source)
    terms = index_unique(terminal["attempts"], lambda a: a["attempt"]["attempt_id"], "attempt")
    pmap = index_unique(points["attempts"], lambda a: a["attempt_id"], "point attempt")
    mmap = index_unique(memory["attempts"], lambda a: a["attempt_id"], "memory attempt")
    require(set(pmap) <= set(terms), "Point capture contains unknown attempts")
    require(set(mmap) <= set(terms), "Memory capture contains unknown attempts")
    searches = index_unique(search["records"],
                            lambda a: (a["attempt_id"], a["point"], a["name"]), "search")
    smap = defaultdict(list)
    for (aid, name, _), rec in searches.items():
        require(aid in terms, "Search capture contains an unknown attempt")
        require(any(p["point"] == name for p in pmap.get(aid, {}).get("points", [])),
                "Search capture contains an unknown point")
        smap[aid].append(rec)
    rows = []
    for aid, item in terms.items():
        pins = {k: captured_pin(item[k], aid, filename) for k, filename in
                (("record", "result-record.json"), ("result", "result.json"),
                 ("supervisor.json", "supervisor.json"))}
        result = item["result"]["content"]
        record = item["record"]["content"]
        supervisor = item["supervisor.json"]["content"]
        status = result.get("status")
        require(record.get("attempt_id") == aid and record.get("status") == status,
                "Terminal identity/status mismatch")
        require(record.get("result") == {"path": pins["result"]["path"],
                                          "sha256": pins["result"]["sha256"]},
                "Terminal result pin mismatch")
        require(result.get("segmented_manifest_hash") == manifest, "Result manifest mismatch")
        require(result.get("segmented_profile") == item["attempt"]["profile"], "Profile mismatch")
        require(record.get("job_sha256") == result.get("job_sha256")
                and isinstance(result.get("job_sha256"), str), "Job binding mismatch")
        require(status in ("complete", "failed", "timeout", "memory_limit", "interrupted"),
                "Unrecognized terminal status")
        expected_supervisor = "complete" if status in ("complete", "failed") else status
        require(supervisor.get("status") == expected_supervisor, "Supervisor/result status mismatch")
        if "harness_execution" in result:
            harness = result["harness_execution"]
            require(all(k in harness and harness[k] == v for k, v in supervisor.items()),
                    "Harness execution mismatch")
            if "supervisor_receipt" in harness:
                require(harness["supervisor_receipt"] == {"path": pins["supervisor.json"]["path"],
                        "sha256": pins["supervisor.json"]["sha256"]}, "Supervisor receipt mismatch")
        top = item.get("top_entries", [])
        require(isinstance(top, list), "Invalid top-level file listing")
        declared_points = sorted(x for x in top if x.startswith("point-"))
        actual = index_unique(pmap.get(aid, {}).get("points", []), lambda p: p["point"], "point")
        require(set(actual) <= set(declared_points), "Point absent from terminal listing")
        gaps = ["Missing point detail: " + n for n in declared_points if n not in actual]
        if not declared_points:
            gaps.append("No point directories recorded")
        stages = [summarize_point(actual[n], aid) for n in sorted(actual)]
        labels = [re.sub(r"^point-\d+-", "", n) for n in declared_points]
        before = None
        if (not gaps and labels and labels == PRETRIAL[:len(labels)]
                and result.get("trial_evaluations", 0) == 0
                and result.get("accepted_iterations", 0) == 0
                and not result.get("history")):
            before = True
        elif result.get("trial_evaluations", 0) > 0 or any("trial" in n for n in labels):
            before = False
        # Complete fits cannot be inferred from a baseline-only directory capture.
        if status == "complete":
            before = None
        last = stages[-1] if stages else None
        location = last["stage"] if last else "unknown_missing_point_evidence"
        if gaps:
            location = "unknown_incomplete_point_capture"
        closure_details = summarize_memory(mmap[aid], aid) if aid in mmap else []
        if status == "memory_limit" and not closure_details:
            gaps.append("Missing nested closure capture; closure progress is unknown")
        if closure_details and location == "point_created_closure_progress_unknown":
            last_closure = closure_details[-1]
            if (last_closure["last_native_program_in_captured_log"] == "OrbitPocEvaluateVariational"
                    and not last_closure["native_execution_completed"]):
                location = "closure_orbit_evaluation_entered_without_completion"
        line_search = summarize_search(smap[aid], aid)
        if not line_search["records"]:
            gaps.append("No captured nuisance line-search records; absence is not evidence of no children")
        cleanup = (supervisor.get("owned_process_group_cleaned") is True
                   and supervisor.get("cleanup", {}).get("verified") is True
                   and supervisor.get("cleanup", {}).get("remaining") == [])
        rows.append({"attempt_id": aid, "order": item["attempt"]["order"],
                     "case_id": item["attempt"]["case_id"], "profile": item["attempt"]["profile"],
                     "status": status, "supervisor_status": supervisor.get("status"),
                     "supervisor_returncode": supervisor.get("returncode"),
                     "elapsed_seconds": supervisor.get("elapsed_seconds"),
                     "peak_process_tree_rss_bytes": supervisor.get("peak_process_tree_rss_bytes"),
                     "cleanup_verified_in_capture": cleanup,
                     "before_first_optimizer_trial": before,
                     "before_first_optimizer_trial_basis": "Pinned optimizer order and captured point directories",
                     "last_point": last["point"] if last else None, "last_observed_stage": location,
                     "completed_native_profiles": sum(p["native_profile_completed"] for p in stages),
                     "strict_completed_native_profiles": sum(p["strict_nuisance_profile_completed"] for p in stages),
                     "completed_native_profile_seconds": sum(p["execution"].get("elapsed_seconds", 0)
                         for p in stages if p["native_profile_completed"]),
                     "native_error_reported": result.get("error"), "points": stages,
                     "nested_closure_evidence": closure_details,
                     "nuisance_search": line_search, "missing_evidence": gaps,
                     "record_pins": pins})
    rows.sort(key=lambda r: r["order"])
    summary = {"captured_terminal_attempts": len(rows),
               "status_counts": dict(sorted(Counter(r["status"] for r in rows).items())),
               "before_first_optimizer_trial": sum(r["before_first_optimizer_trial"] is True for r in rows),
               "optimizer_stage_unknown": sum(r["before_first_optimizer_trial"] is None for r in rows),
               "strict_completed_native_profiles": sum(r["strict_completed_native_profiles"] for r in rows),
               "cleanup_verified_in_capture": sum(r["cleanup_verified_in_capture"] for r in rows),
               "explicit_300s_trial_timeouts": sum(r["nuisance_search"]["explicit_300s_trial_timeouts"] for r in rows),
               "failed_zero_update_replays": sum(r["nuisance_search"]["failed_zero_update_replays"] for r in rows)}
    return {"schema": "orbit-poc-v4-fit-failure-analysis-v1", "manifest_hash": manifest,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scope": "Captured terminal prefix only; no live status, rerun, release or covariance acceptance",
            "release_ready": False, "fit_covariance_authorized": False,
            "benchmark_reclassified": False, "native_execution_performed": False,
            "provenance": {"captures": {"terminal": tp, "points": pp, "search": sp, "memory": mp},
                           "optimizer_source": basis,
                           "analyzer": {"path": str(Path(__file__).resolve()),
                                        "sha256": digest(Path(__file__).read_bytes())},
                           "pin_scope": "Capture-file hashes are computed here. Embedded original-file pins are preserved collector claims; original remote bytes are not reread. Captured JSON content has a separate canonical hash. Logs are excerpts."},
            "limitations": ["A supervisor complete record can contain a scientifically failed fit.",
                "A memory_limit is the supervisor process-tree RSS stop, not proof of a kernel OOM kill.",
                "A replay status failure makes its placeholder cost unusable; the generic guard does not prove objective or cache corruption.",
                "Explicit trial timeout errors do not prove an unrecorded replay failure had the same cause.",
                "Intermediate profile filenames show progress, not successful nuisance convergence.",
                "Cold initial/repeat/refinement checks and all scientific thresholds remain required."],
            "summary": summary, "attempts": rows}


def render_html(report):
    def e(value):
        return escape(str(value), quote=True)
    rows = []
    for r in report["attempts"]:
        search = r["nuisance_search"]
        rows.append("<tr>" + "".join("<td>" + e(v) + "</td>" for v in (
            r["attempt_id"], r["status"], r["last_point"], r["last_observed_stage"],
            r["strict_completed_native_profiles"], r["before_first_optimizer_trial"],
            search["explicit_300s_trial_timeouts"], search["failed_zero_update_replays"],
            "; ".join(r["missing_evidence"]))) + "</tr>")
    provenance = "".join("<li>" + e(k + ": " + v["path"] + " — SHA256 " + v["sha256"])
                         + "</li>" for k, v in report["provenance"]["captures"].items())
    return """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>V4 fit failure investigation</title>
<style>body{font:16px system-ui;margin:2rem;line-height:1.5;color:#18212a}table{border-collapse:collapse;font-size:13px}td,th{border:1px solid #ccd4dc;padding:.5rem;text-align:left;vertical-align:top}tr:nth-child(even){background:#f4f6f8}pre{white-space:pre-wrap}section{overflow-x:auto}code{overflow-wrap:anywhere}</style>
<h1>V4 fit failure investigation</h1><p>""" + e(report["scope"]) + "</p><p>Generated " + e(report["generated_at"]) + \
        '</p><p><a href="report.json">Machine-readable report and per-record provenance</a></p>' + \
        "<h2>Captured outcomes</h2><pre>" + e(json.dumps(report["summary"], indent=2)) + \
        "</pre><h2>Interpretation limits</h2><ul>" + "".join("<li>" + e(x) + "</li>" for x in report["limitations"]) + \
        "</ul><h2>Attempt stages</h2><section><table><thead><tr>" + "".join("<th>" + e(x) + "</th>" for x in
        ("Attempt", "Terminal outcome", "Last point", "Last observed stage", "Strict profiles completed", "Before first optimizer trial", "Explicit 300s child timeouts", "Failed zero replays", "Missing evidence")) + \
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></section><h2>Capture provenance</h2><ul>" + provenance + \
        "</ul><p>" + e(report["provenance"]["pin_scope"]) + "</p></html>\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terminal", type=Path, required=True)
    parser.add_argument("--points", type=Path, required=True)
    parser.add_argument("--search", type=Path, required=True)
    parser.add_argument("--memory", type=Path, required=True)
    parser.add_argument("--optimizer-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New output directory; never overwritten")
    args = parser.parse_args(argv)
    report = analyze(args.terminal, args.points, args.search, args.memory, args.optimizer_source)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    (args.output / "index.html").write_text(render_html(report))
    print(json.dumps(report["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
