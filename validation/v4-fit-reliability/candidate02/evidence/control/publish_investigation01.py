#!/usr/bin/env python3
"""Publish a thin, auditable V4 investigation packet after all final receipts exist.

Reads only existing evidence; never runs tests, native programs, or remote jobs.
Failed outcomes remain visible. Missing final evidence fails before creating the
output directory. Large captures, binaries and row archives stay outside Git.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import json
import math
import os
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

MAX_COPY = 1024 * 1024
FINAL_REQUIRED = ("control/build-result02.json", "native-tests02/result.json",
                  "memory-checks03/result.json", "outputs/cost-pairs03-checks/index.json",
                  "control/campaign-retention02.json")
REVIEW_PATHS = (
    "control/block-memory-independent-source-review01/review.json",
    "control/memory-pairs-independent-review01/review.json",
    "control/memory-pairs-independent-review01/review-72h.json",
    "control/review01/candidate02-source/independent-review.json",
    "control/review01/cost-pairs02-outcomes/independent-review.json",
    "control/review01/cost-pairs03-outcomes/independent-review.json",
    "control/review01/memory03-outcomes/independent-review.json",
    "control/review01/native02-outcomes/independent-review.json",
    "control/nuisance-final-source-review02/review.json",
)
CONTROL_PATHS = tuple("control/" + name for name in (
    "build_candidate01.py", "build_candidate02.py", "run_native_tests01.py", "run_native_tests02.py",
    "run_memory_checks01.py", "run_memory_checks02.py", "run_memory_checks03.py",
    "run_cost_pairs01.py", "run_cost_pairs02.py", "run_cost_pairs03.py",
    "copy_memory_replay01.py", "copy_memory_replay02.py", "read_memory_replay_inputs01.py",
    "capture_terminal_details01.py", "capture_point_details01.py", "capture_nuisance_search01.py",
    "capture_memory_closure01.py"))


def strict_json(data):
    def bad(value):
        raise ValueError("Nonfinite JSON: " + value)
    def floating(value):
        number = float(value)
        if not math.isfinite(number): bad(value)
        return number
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError("Duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(data, parse_constant=bad, parse_float=floating, object_pairs_hook=pairs)


def artifact(path):
    path = Path(path).resolve(strict=True)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        for block in iter(lambda: stream.read(1024 * 1024), b""): digest.update(block)
        after = os.fstat(stream.fileno())
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if identity(before) != identity(after): raise ValueError("Evidence changed during read: " + str(path))
    return {"path": str(path), "sha256": digest.hexdigest(), "bytes": after.st_size}


def same_identity(pin, actual):
    return all(pin.get(key) == actual[key] for key in ("path", "sha256", "bytes"))


class Evidence:
    def __init__(self, base):
        self.base = Path(base).resolve(strict=True)
        self.pins, self.copies = {}, {}

    def register(self, path, *, expected=None, copy=False):
        path = Path(path)
        if not path.is_absolute(): path = self.base / path
        pin = artifact(path)
        if expected and (pin["sha256"] != expected["sha256"]
                         or ("bytes" in expected and pin["bytes"] != expected["bytes"])):
            raise ValueError("Evidence hash mismatch: " + str(path))
        if str(path) in self.pins and self.pins[str(path)] != pin:
            raise ValueError("Evidence changed between reads: " + str(path))
        self.pins[str(path)] = pin
        if copy:
            if pin["bytes"] > MAX_COPY:
                raise ValueError("Receipt exceeds thin-packet size limit: " + str(path))
            try: relative = Path(pin["path"]).relative_to(self.base)
            except ValueError: relative = Path("extra") / (pin["sha256"][:16] + "-" + path.name)
            self.copies[str(path)] = "evidence/" + relative.as_posix()
        return pin

    def read(self, path, *, copy=True):
        pin = self.register(path, copy=copy)
        data = Path(pin["path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != pin["sha256"]:
            raise ValueError("Evidence changed before parsing")
        return strict_json(data)

    def follow(self, pin, *, copy=False):
        actual = self.register(pin.get("requested_path", pin["path"]), expected=pin, copy=copy)
        if "requested_path" in pin and actual["path"] != pin["path"]:
            raise ValueError("Pinned alias resolution changed: " + pin["requested_path"])
        return actual

    def reverify(self):
        for requested, pin in self.pins.items():
            if artifact(requested) != pin: raise ValueError("Evidence changed before publication: " + requested)


def execution(value):
    return {key: value.get(key) for key in ("status", "returncode", "elapsed_seconds",
        "peak_process_tree_rss_bytes", "owned_process_group_cleaned")} | {
        "cleanup_verified": value.get("cleanup", {}).get("verified") is True}


def junit(evidence, path):
    pin = evidence.register(path, copy=True)
    cases = list(ET.parse(pin["path"]).getroot().iter("testcase"))
    counts = {"tests": len(cases), **{name: sum(case.find(name) is not None for case in cases)
                                     for name in ("failure", "error", "skipped")}}
    failures = []
    for case in cases:
        for kind in ("failure", "error", "skipped"):
            node = case.find(kind)
            if node is not None:
                text = node.text or node.get("message", "")
                failures.append({"case": case.get("classname", "") + "::" + case.get("name", ""),
                    "kind": kind, "message": text[:4000], "message_truncated": len(text) > 4000})
    return {"receipt": pin, "counts": counts, "nonpassing_cases": failures}


def build_summary(evidence, number):
    value = evidence.read(f"control/build-result{number:02}.json")
    if value.get("schema") != "orbit-poc-v4-failure-candidate-build-result-v1":
        raise ValueError("Unknown build schema")
    evidence.follow(value["build_plan"], copy=True)
    evidence.follow(value["native"])
    evidence.follow(value["build_manifest"], copy=True)
    manifest = evidence.read(value["build_manifest"]["path"])
    if manifest["executable_sha256"] != value["native"]["sha256"]:
        raise ValueError("Build does not bind executable")
    for pin in value["libraries"]: evidence.follow(pin)
    return {"candidate": number, "native": value["native"], "build_manifest": value["build_manifest"],
        "build_plan": value["build_plan"], "execution": execution(value["execution"]),
        "inputs_and_originals_unchanged": value["inputs_and_originals_unchanged"],
        "boot_unchanged": value["boot_unchanged"], "patched_source_files": len(value["patched_source"]),
        "source_inventory": value["patched_source"], "runtime_libraries": value["libraries"]}


def native_summary(evidence, number, native):
    root = evidence.base / f"native-tests{number:02}"
    value = evidence.read(root / "result.json")
    freeze = evidence.read(root / "freeze.json")
    if freeze["candidate_build"]["native"]["sha256"] != native["sha256"]:
        raise ValueError("Native suite candidate mismatch")
    expected = {name: size for name, size, _ in freeze["suites"]}
    required = {"native":106,"correction":51}
    if number == 2: required.update(fail_fast=37,cost_query=15)
    if expected != required: raise ValueError("Required native regression suite matrix changed")
    if set(expected) != {r["suite"] for r in value["results"]} or len(value["results"]) != len(expected):
        raise ValueError("Native suite aggregate is incomplete or duplicated")
    suites = []
    for result in value["results"]:
        name = result["suite"]
        if evidence.read(root / name / "result.json") != result:
            raise ValueError("Native aggregate differs from individual suite receipt")
        parsed = junit(evidence, root / name / "tests.xml")
        if parsed["counts"] != result["counts"]:
            raise ValueError("Native aggregate/JUnit counts disagree")
        passed = (result["execution"]["status"] == "complete" and result["execution"]["returncode"] == 0
                  and result["execution"].get("owned_process_group_cleaned") is True
                  and result["execution"].get("cleanup", {}).get("verified") is True
                  and result["inputs_and_runtime_unchanged"] is True
                  and parsed["counts"] == {"tests": expected[name], "failure": 0, "error": 0, "skipped": 0})
        if passed is not result["passed"]: raise ValueError("Native suite verdict contradicts evidence")
        suites.append({"suite": name, "passed": passed, **parsed, "execution": execution(result["execution"])})
    if value["passed"] is not all(s["passed"] for s in suites):
        raise ValueError("Native aggregate verdict contradicts suites")
    return {"candidate": number, "native": native, "passed": value["passed"], "suites": suites,
            "test_file_hashes": freeze["test_hashes"]}


def memory_summary(evidence, number, native):
    root = evidence.base / f"memory-checks{number:02}"
    value = evidence.read(root / "result.json")
    freeze = evidence.read(root / "freeze.json")
    if not any(p["sha256"] == native["sha256"] and p["path"] == native["path"] for p in freeze["runtime_pins"]):
        raise ValueError("Memory replay native mismatch")
    for pin in freeze["input_pins"]: evidence.follow(pin)
    pairs = evidence.read(value["native_pairs"])
    parsed = junit(evidence, root / "native-pairs/tests.xml")
    if parsed["counts"] != pairs["counts"]: raise ValueError("Memory pair/JUnit counts differ")
    replays = []
    for replay in value["replays"]:
        block = replay["block_epochs"]
        local = evidence.read(root / f"replay72h-block{block}/result.json")
        if local != replay or replay["freeze_sha256"] != artifact(root / "freeze.json")["sha256"]:
            raise ValueError("Memory replay receipt mismatch")
        replays.append({"block_epochs": block, "execution": execution(replay["execution"])})
    if {r["block_epochs"] for r in replays} != {0, 64, 256} or len(replays) != 3:
        raise ValueError("Memory replay matrix is incomplete")
    if value.get("whole_fit_verified") is not False: raise ValueError("Invalid whole-fit claim in component receipt")
    # Positive numerical claims must remain tied to the independently inspected
    # output bytes, not merely to an old summary file that says 'passed'.
    if value["blocked_pair"].get("passed") is True:
        review_path = ("control/memory-pairs-independent-review01/review-72h.json" if number == 2 else
                       "control/review01/memory03-outcomes/independent-review.json")
        review = evidence.read(review_path)
        summary_pin = review["summary"] if number == 2 else review["summary_receipt"]
        freeze_pin = review["freeze"] if number == 2 else review["freeze_receipt"]
        if (not same_identity(summary_pin, artifact(root/"result.json")) or not same_identity(freeze_pin, artifact(root/"freeze.json"))
                or review.get("passed") is not True or review.get("whole_fit_verified") is not False
                or review.get("release_authority") is not False):
            raise ValueError("Independent memory outcome review is unbound or inadmissible")
        evidence.follow(summary_pin)
        evidence.follow(freeze_pin)
        for pin in review["pins" if number == 2 else "provenance"]: evidence.follow(pin)
        if number == 2:
            small = evidence.read("control/memory-pairs-independent-review01/review.json")
            if small.get("passed") is not True or not same_identity(small["freeze"], artifact(root/"freeze.json")):
                raise ValueError("Independent small memory-pair review is unbound")
            evidence.follow(small["freeze"])
            for pin in small["inventory"]: evidence.follow(pin)
    return {"run": number, "native": native, "native_pair_tests": parsed,
        "native_pair_execution": execution(pairs["execution"]), "replays": replays,
        "blocked_pair": value["blocked_pair"], "input_pins": freeze["input_pins"],
        "scope": "Reused fixed-parameter archive only. Large unblocked failure is retained; block64/block256 comparison is not equivalence to its missing output."}


def cost_summary(evidence, number, native):
    root = evidence.base / f"cost-pairs{number:02}"
    checkroot = evidence.base / f"outputs/cost-pairs{number:02}-checks"
    freeze = evidence.read(root / "freeze.json")
    result = evidence.read(root / "result.json")
    index = evidence.read(checkroot / "index.json")
    if freeze["native"]["sha256"] != native["sha256"] or result.get("all_planned_attempts_executed") is not True:
        raise ValueError("Cost experiment incomplete or wrong native")
    if len(result["results"]) != 8 or {x["job"] for x in result["results"]} != {j["name"] for j in freeze["jobs"]}:
        raise ValueError("Cost experiment job coverage mismatch")
    if index["freeze"] != artifact(root/"freeze.json"):
        raise ValueError("Cost checker index is bound to a different campaign freeze")
    evidence.follow(index["freeze"])
    pairs = []
    expected = {f"{m}-accumulate{a}" for m in ("pulses", "log_drag_ou") for a in (0, 1)}
    if len(index["pairs"]) != 4 or {x["pair"] for x in index["pairs"]} != expected:
        raise ValueError("Cost checks do not cover all four pairs")
    for item in index["pairs"]:
        if Path(item["path"]) != checkroot/(item["pair"]+'.json'):
            raise ValueError("Cost pair report path belongs to another campaign")
        evidence.follow(item, copy=True)
        checked = evidence.read(item["path"])
        if checked["schema"] != "orbit-poc-nuisance-cost-only-pair-v1" or checked["passed"] is not item["passed"]:
            raise ValueError("Cost checker/index disagreement")
        if any(checked.get(key) is not False for key in ("accepted_covariance", "whole_fit_convergence_established", "full_fit_verified", "release_authority")):
            raise ValueError("Cost checker carries invalid authority")
        equal = bool(checked["comparisons"]) and all(c["equal"] is True for c in checked["comparisons"])
        if (checked["scientific_comparison_count"] != len(checked["comparisons"])
                or checked["artifact_equality"] is not equal
                or checked["cost_only_pair_verified"] is not checked["frozen_experiment"]["verified"]
                or checked["passed"] is not (equal and checked["cost_only_pair_verified"] and not checked["issues"]
                                              and all(not r["issues"] for r in checked["runs"]))):
            raise ValueError("Cost checker verdict contradicts its scientific evidence")
        if len(checked["runs"]) != 2: raise ValueError("Cost checker lacks exactly two runs")
        for pin in checked["frozen_experiment"]["provenance"]: evidence.follow(pin)
        executions = []
        for flag,run in enumerate(checked["runs"]):
            e = run["execution"] or {}
            d = Path(run["root"])
            if d != root/(item["pair"]+f'-cost{flag}'):
                raise ValueError("Cost checker run root belongs to another pair or campaign")
            jobs = [j for j in freeze['jobs'] if j['name']==d.name and j['profile']==str(d/'profile.xml')]
            if len(jobs)!=1: raise ValueError("Cost checker run does not match frozen job")
            job=jobs[0]
            if (e.get('native_binary_sha256') != native['sha256'] or e.get('freeze_sha256') != index['freeze']['sha256']
                    or e.get('config_sha256') != job['profile_sha256'] or e.get('cost_only_design') != flag
                    or e.get('accumulate_epoch_observations') != job['accumulate'] or e.get('cache') != 1):
                raise ValueError("Cost checker execution does not bind the frozen treatment/native")
            actual = evidence.read(d / "profile.execution.json")
            if actual != e: raise ValueError("Checked execution differs from actual record")
            if next(x for x in result['results'] if x['job']==d.name) != {'job':d.name,**actual}:
                raise ValueError("Cost execution aggregate differs from checked attempt")
            for pin in run['provenance']: evidence.follow(pin)
            evidence.register(d / "supervisor.json", copy=True)
            evidence.register(d / "profile.log", copy=True)
            executions.append({"job": d.name, "classification": run["profile_classification"],
                "iterations": run["final_generation"] - 1 if isinstance(run["final_generation"], int) else None,
                "status": e.get("status"), "returncode": e.get("returncode"),
                "elapsed_seconds": e.get("elapsed_seconds"), "peak_process_tree_rss_bytes": e.get("peak_rss_bytes")})
        pairs.append({"pair": item["pair"], "passed": checked["passed"],
            "artifact_equality": checked["artifact_equality"], "scientific_comparisons": checked["scientific_comparison_count"],
            "issues": checked["issues"], "runs": executions,
            "observed_treatments": checked["frozen_experiment"].get("observed", [])})
    return {"run": number, "native": native, "accepted_pairs": sum(p["passed"] for p in pairs),
            "rejected_pairs": sum(not p["passed"] for p in pairs), "pairs": pairs}


def collect(base, extra_reviews=()):
    evidence = Evidence(base)
    missing = [name for name in FINAL_REQUIRED if not (evidence.base / name).is_file()]
    if missing: raise ValueError("Final evidence pending: " + ", ".join(missing))
    analyzer = evidence.read("outputs/investigation01/report.json")
    if (analyzer.get("release_ready") is not False or analyzer.get("fit_covariance_authorized") is not False
            or analyzer.get("benchmark_reclassified") is not False):
        raise ValueError("Unexpected authority in captured-failure report")
    for pin in analyzer["provenance"]["captures"].values(): evidence.follow(pin)
    prior_retention = evidence.read("control/campaign-retention01.json")
    retention = evidence.read("control/campaign-retention02.json")
    for key in ("before", "after"): evidence.follow(retention[key])
    later = evidence.read(retention["after"]["path"], copy=False)
    capture_counts = dict(Counter(a["status"] for a in analyzer["attempts"]))
    if capture_counts != analyzer["summary"]["status_counts"]:
        raise ValueError("Captured terminal counts disagree")
    if (len(analyzer['attempts']) != analyzer['summary']['captured_terminal_attempts']
            or sum(a.get('before_first_optimizer_trial') is True for a in analyzer['attempts']) != analyzer['summary']['before_first_optimizer_trial']
            or sum(a.get('strict_completed_native_profiles',0) for a in analyzer['attempts']) != analyzer['summary']['strict_completed_native_profiles']):
        raise ValueError("Captured stage totals disagree")
    if later["terminal_status_counts"] != retention["after_counts"]:
        raise ValueError("Later campaign snapshot counts disagree")
    builds = [build_summary(evidence, n) for n in (1, 2)]
    natives = [native_summary(evidence, n, builds[n-1]["native"]) for n in (1, 2)]
    memories = [memory_summary(evidence, n, builds[n-2]["native"]) for n in (2, 3)]
    costs = [cost_summary(evidence, n, builds[0 if n < 3 else 1]["native"]) for n in (1, 2, 3)]
    history = [junit(evidence, p) for p in sorted((evidence.base / "outputs").glob("*tests*.xml"))]
    history += [junit(evidence, p) for p in sorted((evidence.base / "control").glob("variational-memory-author*/*.xml"))]
    reviews = []
    for path in dict.fromkeys([*REVIEW_PATHS, *map(str, extra_reviews)]):
        full = Path(path) if Path(path).is_absolute() else evidence.base / path
        if full.exists():
            value = evidence.read(full)
            reviews.append({"receipt": artifact(full), "schema": value.get("schema"),
                "status": value.get("status", value.get("decision")), "passed": value.get("passed"),
                "scope": value.get("scope"), "limitations": value.get("limitations", [])})
    for path in ("control/source-snapshot01.json", "control/cost-pair-checker-ready01/readiness.json",
                 "outputs/cost-pairs01-checks/outcome-review.json",
                 "control/memory-pairs-independent-review01/documentation-count-correction.json"):
        evidence.read(path)
    for name in ("scripts/analyze_v4_fit_failures.py", "scripts/check_nuisance_cost_only_pair.py",
                 "scripts/check_nuisance_performance_pair.py", "scripts/analyze_nuisance_profile.py",
                 "scripts/build_groops.py", "src/orbit_poc/segmented/supervisor.py",
                 "src/orbit_poc/comparison/backend.py",
                 "docs/v4-fit-failures.md", "docs/variational-memory-candidate.md"):
        evidence.register(evidence.base / "source" / name, copy=True)
    controls = [evidence.register(path, copy=True) for path in (*CONTROL_PATHS,'control/check_cost_pairs.py')]
    report = {"schema": "v4-fit-reliability-publication-v1", "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Bounded fixed-parameter and nuisance-profile components, not a successful full orbit fit.",
        "captured_failure_prefix": {"manifest_hash": analyzer["manifest_hash"], "summary": analyzer["summary"],
            "capture_pins": analyzer["provenance"]["captures"],
            "attempts": [{key: a.get(key) for key in ("attempt_id", "status", "supervisor_status", "elapsed_seconds",
                "peak_process_tree_rss_bytes", "last_observed_stage", "before_first_optimizer_trial",
                "strict_completed_native_profiles", "native_error_reported", "missing_evidence", "record_pins")}
                for a in analyzer["attempts"]]},
        "later_campaign_snapshot": {"captured_at": later["captured_at"], "terminal_count": later["terminal_count"],
            "terminal_status_counts": later["terminal_status_counts"], "nonterminal_attempt_ids": later["current_nonterminal_attempt_ids"],
            "driver_live_at_capture": later["driver_live"], "manifest_unchanged": retention["manifest_unchanged"],
            "driver_identity_matches": retention["driver_identity_matches"],
            "existing_terminal_records_preserved": retention["unchanged_existing_terminal_records"],
            "scope": "A later timestamped read-only snapshot, not additional stage analysis and not current live status."},
        "prior_campaign_retention": prior_retention,
        "builds": builds, "native_suites": natives, "memory_components": memories, "cost_only_profiles": costs,
        "historical_test_attempts": history, "independent_reviews": reviews,
        "reproduction_controls": {"files": controls,
            "scope": "Environment-specific historical launch and collection controls, retained byte-for-byte and linked to receipt hashes. They contain absolute local paths and execution-host assumptions.",
            "requirements": "Reproduction requires the matching repository source, pinned native/toolchain runtime, original external datasets, compatible Linux environment and explicit adaptation of paths. Hashes identify missing external objects; hashes alone do not make them available or make this a self-contained reproducible package."},
        "unresolved": ["The 48-hour GNSS full-design storage and fork process-tree memory exits are not solved by closure blocking.",
            "The archived 72-hour pulse nuisance-child timeouts remain unresolved; short profiles do not establish their completion.",
            "No complete v4 orbit fit, full-fit covariance, frozen-benchmark completion, or release acceptance is established.",
            "Single off/on profile timings are mixed and do not establish a repeatable speedup.",
            "Large blocked outputs are compared to each other; the unblocked large baseline was stopped for memory.",
            "Candidate01 failures are retained. Candidate01 component passes cannot be attributed to candidate02.",
            "The zero-column callback retains query/stencil/remainder checks but cannot inspect nonfinite or overflowing omitted derivative values; full parent/final linearizations still compute them.",
            "Default-off fail-fast preserves valid search behavior; the caller additionally rejects invalid replay support or row counts, and nonfinite diagnostics.",
            "Original remote record pins are collector claims retained in bounded captures; this publication performs no remote recheck."],
        "authority": {"whole_fit_verified": False, "accepted_covariance": False, "release_authority": False,
                      "benchmark_reclassified": False, "established_speedup": False},
        "generator": artifact(__file__), "native_execution_by_generator": False}
    return report, evidence


def render(report, links):
    esc = lambda x: html.escape(str(x), quote=True)
    def table(headers, rows):
        return '<table><thead><tr>' + ''.join('<th>'+esc(h)+'</th>' for h in headers) + '</tr></thead><tbody>' + ''.join(
            '<tr>' + ''.join('<td>'+esc(c)+'</td>' for c in row) + '</tr>' for row in rows) + '</tbody></table>'
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">',
        '<title>V4 fit reliability investigation</title><style>body{font:16px/1.5 system-ui,sans-serif;max-width:1200px;margin:2rem auto;padding:0 1rem;color:#152634;background:#fafbfd}h1,h2{line-height:1.2}table{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.9rem}th,td{border:1px solid #cbd5dd;padding:.5rem;text-align:left;vertical-align:top}th{background:#e8eef3}code{overflow-wrap:anywhere}.notice{border-left:5px solid #b96013;padding:1rem;background:#fff3df}a{color:#075a96}section{margin:2.5rem 0}.wrap{overflow-x:auto}</style>',
        '<h1>V4 fit reliability investigation</h1><p>'+esc(report['scope'])+'</p>',
        '<p class="notice">Component evidence only. Whole-fit convergence, covariance, release and repeatable speedup are not established. Earlier failures remain part of this record.</p>',
        '<p><a href="report.json">Compact report JSON</a> · <a href="manifest.json">Packet manifest</a></p>']
    captured = report['captured_failure_prefix']; later = report['later_campaign_snapshot']
    parts += ['<section><h2>Frozen campaign evidence</h2>',
        '<p>The detailed analysis covers '+esc(captured['summary']['captured_terminal_attempts'])+' terminal attempts. The later snapshot contains '+esc(later['terminal_count'])+' terminal attempts as of '+esc(later['captured_at'])+'. These are separate observations.</p>',
        table(['Observation', 'Timeout', 'Memory limit', 'Failed'], [
            ['Detailed captured prefix', *[captured['summary']['status_counts'].get(k,0) for k in ('timeout','memory_limit','failed')]],
            ['Later snapshot', *[later['terminal_status_counts'].get(k,0) for k in ('timeout','memory_limit','failed')]]]),
        '<p>'+esc(captured['summary']['before_first_optimizer_trial'])+' captured attempts stopped before the first optimizer trial. '+esc(captured['summary']['strict_completed_native_profiles'])+' strict initial/repeat profiles completed; none was a completed orbit fit. Failed zero-replay execution is not a measured objective change. The 72-hour density logs reached the fixed-parameter evaluator after propagation wrote its archive.</p>',
        '<div class="wrap">'+table(['Captured attempt','Status','Last observed stage','Before first optimizer trial'],
            [[x['attempt_id'],x['status'],x['last_observed_stage'],x['before_first_optimizer_trial']] for x in captured['attempts']])+'</div></section>']
    parts += ['<section><h2>Native regression history</h2>', table(['Candidate','Suite','Tests','Failures','Errors','Skipped','Verdict'],
        [[n['candidate'],s['suite'],*[s['counts'][k] for k in ('tests','failure','error','skipped')], 'pass' if s['passed'] else 'reject']
         for n in report['native_suites'] for s in n['suites']]),
        '<p>Candidate01’s four native regression failures remain preserved. Candidate02 adds explicit fail-fast option and real Polynomial query-path tests; these do not constitute the complete release suite.</p></section>']
    parts += ['<section><h2>Fixed-parameter memory components</h2>', table(['Run','Native SHA-256','Block epochs','Execution','Peak process-tree MiB','Seconds'],
        [[m['run'],m['native']['sha256'][:16],r['block_epochs'],r['execution']['status'],
          round((r['execution']['peak_process_tree_rss_bytes'] or 0)/1024**2,2),r['execution']['elapsed_seconds']]
         for m in report['memory_components'] for r in m['replays']]),
        '<p>Block64 and block256 results are compared under unchanged limits. The large unblocked replay’s memory stop prevents a large off/on equivalence claim. This component does not fix the 48-hour GNSS profile memory exits.</p>',
        table(['Run','Blocked epochs','Position difference (m)','Velocity difference (m/s)','Blocked-pair verdict'],
              [[m['run'],m['blocked_pair'].get('epochs'),m['blocked_pair'].get('maximum_position_difference_m'),m['blocked_pair'].get('maximum_velocity_difference_m_s'),m['blocked_pair'].get('passed',False)] for m in report['memory_components']]), '</section>']
    parts += ['<section><h2>Cost-only nuisance profiles</h2><p>Run01 exited with no usable receivers after missing audit-output directories; it produced no scientific profile. Run02 uses candidate01. Run03 uses candidate02. Only existing trial resource fields are excluded from exact scientific comparison.</p>',
        table(['Run','Pair','Exact verdict','Scientific artifacts','Off seconds','On seconds','Off/on iterations'],
            [[c['run'],p['pair'],'pass' if p['passed'] else 'reject',p['scientific_comparisons'],
              p['runs'][0]['elapsed_seconds'],p['runs'][1]['elapsed_seconds'],
              str(p['runs'][0]['iterations'])+' / '+str(p['runs'][1]['iterations'])]
             for c in report['cost_only_profiles'] for p in c['pairs']]), '</section>',
        '<section><h2>Preserved earlier test attempts</h2>', table(['Receipt','Tests','Failures','Errors','Skipped'],
            [[Path(x['receipt']['path']).parent.name+'/'+Path(x['receipt']['path']).name,*[x['counts'][k] for k in ('tests','failure','error','skipped')]] for x in report['historical_test_attempts']]), '</section>',
        '<section><h2>Limits and unresolved work</h2><ul>'+''.join('<li>'+esc(x)+'</li>' for x in report['unresolved'])+'</ul></section>',
        '<section><h2>Evidence and provenance</h2><p>Local packet receipts and controls are byte copies. Controls are environment-specific and use absolute paths; reproduction requires the matching repository, runtime and external datasets. Hashes alone do not make missing objects available. Bulky inputs, native binaries and row archives remain outside Git. Full source inventories are in the retained build receipts.</p><ul>']
    for name, href in sorted(links.items()):
        parts.append('<li><a href="'+esc(href)+'">'+esc(name)+'</a></li>')
    parts.append('</ul></section></html>')
    return '\n'.join(parts)


def publish(base, output, extra_reviews=()):
    output = Path(output).absolute()
    if output.exists(): raise FileExistsError("Publication output already exists: " + str(output))
    if any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError("Publication output must not traverse symlinks")
    report, evidence = collect(base, extra_reviews)
    evidence.register(__file__, copy=True)
    evidence.reverify()
    # The report stays compact; full compilation maps remain in retained receipts.
    for build in report['builds']: build.pop('source_inventory')
    report['provenance'] = [{**pin, 'requested_path': requested,
                            'packet_path': evidence.copies.get(requested)} for requested,pin in sorted(evidence.pins.items())]
    links = {str(Path(path).relative_to(evidence.base)) if Path(path).is_relative_to(evidence.base) else path: rel
             for path,rel in evidence.copies.items()}
    output.mkdir(parents=True)
    for requested, relative in evidence.copies.items():
        target = output / relative; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(evidence.pins[requested]['path'], target)
        if artifact(target)['sha256'] != evidence.pins[requested]['sha256']:
            raise ValueError("Copied evidence mismatch")
    (output/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+'\n')
    (output/'index.html').write_text(render(report, links))
    evidence.reverify()
    payload = [{"path":p.relative_to(output).as_posix(),"sha256":artifact(p)['sha256'],"bytes":p.stat().st_size}
               for p in sorted(output.rglob('*')) if p.is_file()]
    manifest = {"schema":"v4-fit-reliability-packet-v1","created_at":report['created_at'],"files":payload,
        "generator":artifact(__file__),"whole_fit_verified":False,"accepted_covariance":False,"release_authority":False,
        "native_execution_by_generator":False}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True,allow_nan=False)+'\n')
    return {"output":str(output),"manifest":artifact(output/'manifest.json'),"payload_files":len(payload)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',type=Path,default=Path('/home/emper/orbit-v4-failure-investigation'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--review',type=Path,action='append',default=[])
    args=parser.parse_args()
    print(json.dumps(publish(args.base,args.output,args.review),indent=2))


if __name__=='__main__':main()
