#!/usr/bin/env python3
"""Check exact scientific equality of two completed native nuisance-profile runs.

No native process is launched. Timing sidecars are diagnostics, never numerical
acceptance criteria. This check cannot authorize a full-fit covariance.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import struct

_ANALYZER = Path(__file__).with_name("analyze_nuisance_profile.py")
_SPEC = importlib.util.spec_from_file_location("_nuisance_analysis", _ANALYZER)
analysis = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(analysis)
GENERATION = re.compile(r"qr\.(\d+)\.(.+)")
JSON_SUFFIXES = (".profile.json", ".factor.json", ".diagnostics.json", ".nuisance_line_search.json")
STRIPPED_TRIAL_FIELDS = ("child_user_seconds", "child_system_seconds", "peak_child_rss_bytes")
REQUIRED_FACTOR = ("factor.json", "diagnostics.json", "profile.json", "parameters.tsv", "bias_coordinates.tsv",
                   "nuisance_coordinates.tsv", "delta.tsv", "singular_values.txt", "rows.tsv", "R.bin", "rhs.bin")


def strict_json(data):
    def constant(token):
        raise ValueError("Nonfinite JSON number: " + token)
    def number(token):
        result = float(token)
        if not math.isfinite(result):
            constant(token)
        return result
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(data, parse_constant=constant, parse_float=number, object_pairs_hook=pairs)


def scientific_json(value, name):
    """Only three existing trial resource fields are non-scientific."""
    value = json.loads(json.dumps(value, allow_nan=False))
    removed = []
    if name.endswith(".nuisance_line_search.json"):
        for index, trial in enumerate(value.get("trials", [])):
            for field in STRIPPED_TRIAL_FIELDS:
                if field in trial:
                    del trial[field]
                    removed.append(f"trials[{index}].{field}")
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return data, removed


def scientific_name(path):
    name = path.name
    if name.endswith(".rows.tsv.gz"):
        return name[:-3]
    if name.endswith(JSON_SUFFIXES) or (name.startswith("qr.") and name.endswith((".tsv", ".bin", ".singular_values.txt"))):
        return name
    return None


def classify_profile(profile):
    if profile.get("nuisance_converged") is True and profile.get("nuisance_floor_limited") is False:
        return "strict_nuisance_convergence"
    if profile.get("nuisance_converged") is False and profile.get("nuisance_floor_limited") is True:
        return "floor_limited_progress_only"
    return "invalid_or_unfinished_profile"


def valid_floor_receipt(profile):
    """Mirror the corrected backend's progress-only receipt gate; no covariance."""
    resolution, potential = (profile.get(key) for key in ("nuisance_objective_resolution", "nuisance_predicted_reduction"))
    if (not analysis.finite_nonnegative(resolution) or not analysis.finite_nonnegative(potential)
            or not 0 < potential <= resolution
            or profile.get("nuisance_floor_policy") != "empirical_equivalent_arithmetic_and_symmetric_probes_v1"):
        return False
    audits = profile.get("nuisance_floor_audit")
    if not isinstance(audits, list) or len(audits) != 4 or not all(isinstance(item, dict) for item in audits):
        return False
    if not all(item.get("success") is True and item.get("support_unchanged") is True for item in audits):
        return False
    if not all(sum(item.get("kind") == "equivalent_arithmetic" and type(item.get("mode")) is int
                   and item["mode"] == mode for item in audits) == 1 for mode in (1, 2, 3)):
        return False
    probes = [item for item in audits if item.get("kind") == "two_amplitude_symmetric_nuisance_probe"
              and isinstance(item.get("probes"), list) and len(item["probes"]) == 4]
    if len(probes) != 1:
        return False
    return all(analysis.finite_nonnegative(probes[0].get(key)) and 0 < probes[0][key] <= resolution
               for key in ("empirical_quadratic_potential", "half_empirical_quadratic_potential",
                           "empirical_quadratic_potential_with_allowance", "half_empirical_quadratic_potential_with_allowance"))


def check_matrix(data, *, rows, columns):
    if len(data) < 16:
        raise ValueError("Truncated binary matrix")
    shape = struct.unpack("<QQ", data[:16])
    if shape != (rows, columns) or len(data) != 16 + 8 * rows * columns:
        raise ValueError("Binary matrix dimensions/payload differ from final factor metadata")
    if not all(math.isfinite(value[0]) for value in struct.iter_unpack("<d", data[16:])):
        raise ValueError("Nonfinite binary factor")


def inspect_run(root):
    root = Path(root).resolve(strict=True)
    issues, provenance, artifacts, values, strip_log = [], {}, {}, {}, {}

    def load(path):
        pin, data = analysis.artifact(path)
        previous = provenance.get(pin["path"])
        if previous is not None and previous != pin:
            raise ValueError("Input changed during pair check")
        provenance[pin["path"]] = pin
        return data

    def problem(message, file=None):
        issues.append({"message": message, **({"file": file} if file else {})})

    execution = None
    try:
        execution = strict_json(load(root / "profile.execution.json"))
        if type(execution.get("returncode")) is not int or execution["returncode"] != 0 or execution.get("timed_out") is not False:
            problem("Native profile did not complete successfully", "profile.execution.json")
        if execution.get("status") != "complete" or execution.get("owned_process_group_cleaned") is not True:
            problem("Execution lacks complete status and verified owned cleanup", "profile.execution.json")
        supervisor_data = load(root / "supervisor.json")
        if execution.get("supervisor_sha256") != hashlib.sha256(supervisor_data).hexdigest():
            problem("Supervisor receipt pin mismatch", "supervisor.json")
        supervisor = strict_json(supervisor_data)
        if (supervisor.get("status") != "complete" or type(supervisor.get("returncode")) is not int
                or supervisor["returncode"] != 0 or supervisor.get("owned_process_group_cleaned") is not True
                or not isinstance(supervisor.get("cleanup"), dict) or supervisor["cleanup"].get("verified") is not True):
            problem("Supervisor does not confirm completed owned-process cleanup", "supervisor.json")
        config = load(root / "profile.xml")
        if execution.get("config_sha256") != hashlib.sha256(config).hexdigest():
            problem("Native execution configuration pin mismatch", "profile.xml")
        command = execution.get("command")
        valid_direct = isinstance(command, list) and len(command) == 2
        valid_taskset = isinstance(command, list) and len(command) == 5 and command[:2] == ["/usr/bin/taskset", "-c"]
        if not (valid_direct or valid_taskset) or not isinstance(command[-1], str) or Path(command[-1]).resolve() != root / "profile.xml":
            problem("Execution command does not identify this profile XML", "profile.execution.json")
        if supervisor.get("argv") != command:
            problem("Supervisor command differs from execution", "supervisor.json")
        binary_hash = execution.get("native_binary_sha256")
        if not isinstance(binary_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", binary_hash):
            problem("Missing native executable identity", "profile.execution.json")
    except (OSError, ValueError, TypeError, AttributeError) as error:
        problem(str(error), "profile.execution.json")
    execution_verified = not issues

    for path in sorted(root.iterdir()):
        if not path.is_file():
            continue
        name = scientific_name(path)
        if name is None:
            continue
        try:
            data = load(path)
            if path.name.endswith(".rows.tsv.gz"):
                data = gzip.decompress(data)
            if name.endswith(".json"):
                value = strict_json(data)
                if not isinstance(value, dict):
                    raise ValueError("Scientific JSON must be an object")
                values[name] = value
                data, removed = scientific_json(value, name)
                strip_log[name] = removed
            if name in artifacts and artifacts[name] != data:
                raise ValueError("Conflicting raw/compressed scientific copies")
            artifacts[name] = data
        except (OSError, ValueError, TypeError, AttributeError, EOFError) as error:
            problem(str(error), path.name)

    profile = values.get("qr.profile.json", {})
    classification = classify_profile(profile)
    if classification == "invalid_or_unfinished_profile":
        problem("Missing or inconsistent final nuisance convergence status", "qr.profile.json")
    if classification == "floor_limited_progress_only" and not valid_floor_receipt(profile):
        problem("Floor-limited status lacks the unchanged measured-resolution audit", "qr.profile.json")
    if profile.get("threshold_m") != 1e-8 or profile.get("required_consecutive_small_updates") != 2:
        problem("Nuisance convergence controls differ from unchanged thresholds", "qr.profile.json")
    if profile.get("fixed_weights") is not True or profile.get("dynamic_updates") is not False:
        problem("Profile does not affirm fixed weights and fixed physical dynamics", "qr.profile.json")
    if classification == "strict_nuisance_convergence":
        history = profile.get("history")
        if (not isinstance(history, list) or len(history) < 2
                or any(not isinstance(row, dict) or not analysis.finite_nonnegative(row.get("maximum_update_m"))
                       or row["maximum_update_m"] >= 1e-8 for row in history[-2:])):
            problem("Strict nuisance status lacks two consecutive unchanged-threshold updates", "qr.profile.json")
    iterations = profile.get("iterations")
    history = profile.get("history")
    if (not isinstance(history, list) or type(iterations) is not int or len(history) != iterations
            or not history or not isinstance(history[-1], dict)
            or profile.get("maximum_update_m") != history[-1].get("maximum_update_m")):
        problem("Nuisance history count/final update disagrees with summary", "qr.profile.json")
    final = None
    if type(iterations) is not int or iterations < 1:
        problem("Missing positive nuisance iteration count", "qr.profile.json")
    else:
        final = iterations + 1
        actual_generations = {int(match[1]) for name in artifacts if (match := GENERATION.fullmatch(name))}
        if actual_generations != set(range(1, final + 1)):
            problem("Scientific generations are missing, extra, or noncontiguous")
        for generation in range(1, final + 1):
            for suffix in REQUIRED_FACTOR:
                name = f"qr.{generation}.{suffix}"
                if name not in artifacts:
                    problem("Required scientific artifact missing", name)
            if generation <= iterations:
                for suffix in ("nuisance_line_search.json", "receiver_times.tsv"):
                    name = f"qr.{generation}.{suffix}"
                    if name not in artifacts:
                        problem("Required nuisance iteration artifact missing", name)
            elif f"qr.{generation}.nuisance_line_search.json" in artifacts:
                problem("Final factor is not a separate fresh linearization")
        diagnostics = values.get(f"qr.{final}.diagnostics.json", {})
        if diagnostics.get("lambda") != 0 or type(diagnostics.get("lambda")) is bool:
            problem("Final factor is not undamped", f"qr.{final}.diagnostics.json")
        if diagnostics.get("rank_status") != "full":
            problem("Final factor does not certify full rank", f"qr.{final}.diagnostics.json")
        factor = values.get(f"qr.{final}.factor.json", {})
        rows, columns = factor.get("rows"), factor.get("columns")
        if type(rows) is not int or type(columns) is not int or rows <= 0 or rows != columns:
            problem("Invalid final square-root factor dimensions", f"qr.{final}.factor.json")
        else:
            for suffix, shape in (("R.bin", (rows, columns)), ("rhs.bin", (rows, 1))):
                name = f"qr.{final}.{suffix}"
                if name in artifacts:
                    try:
                        check_matrix(artifacts[name], rows=shape[0], columns=shape[1])
                    except ValueError as error:
                        problem(str(error), name)

    sidecars = []
    for path in sorted(root.glob("qr.*.nuisance_performance.json")):
        try:
            value = strict_json(load(path))
            search_name = path.name.replace(".nuisance_performance.json", ".nuisance_line_search.json")
            if search_name not in values:
                raise ValueError("Performance sidecar has no matching scientific line-search receipt")
            sidecars.append(analysis.validate_performance(value, values[search_name]))
        except (OSError, ValueError, TypeError, AttributeError) as error:
            problem(str(error), path.name)
    return {"root": str(root), "issues": issues, "provenance": provenance,
            "artifacts": artifacts, "values": values, "removed_fields": strip_log,
            "profile_classification": classification, "final_generation": final,
            "execution": execution, "execution_verified": execution_verified, "performance_sidecars": sidecars,
            "performance": analysis.performance_summary(sidecars)}


def bind_cache_pair(runs, freeze_path, preparation_path):
    """Bind observed cache treatments to the immutable actual-runner plan."""
    issues, pins = [], []
    try:
        freeze_pin, freeze_data = analysis.artifact(freeze_path)
        preparation_pin, preparation_data = analysis.artifact(preparation_path)
        pins.extend([freeze_pin, preparation_pin])
        freeze, preparation = strict_json(freeze_data), strict_json(preparation_data)
        if (freeze.get("schema") != "orbit-poc-nuisance-pair-freeze-v1"
                or preparation.get("schema") != "orbit-poc-nuisance-pair-preparation-v1"
                or freeze.get("preparation_sha256") != preparation_pin["sha256"]
                or freeze.get("order") != preparation.get("predeclared_order")):
            raise ValueError("Freeze/preparation identity or order mismatch")
        cpu = preparation.get("cpu")
        if type(cpu) is not int or cpu < 0 or preparation.get("one_numerical_thread") is not True:
            raise ValueError("Frozen CPU/thread settings missing or invalid")
        native = freeze["native"]
        selected = []
        for cache, run in enumerate(runs):
            if not run["execution_verified"]:
                raise ValueError("Cache treatment lacks verified completed execution")
            execution = run["execution"] or {}
            profile = str(Path(run["root"]) / "profile.xml")
            jobs = [job for job in preparation["jobs"] if job.get("profile") == profile]
            if len(jobs) != 1:
                raise ValueError("Run is not uniquely identified by frozen preparation")
            job = jobs[0]; selected.append(job)
            if (type(job.get("cache")) is not int or job["cache"] != cache
                    or type(execution.get("cache")) is not int or execution["cache"] != cache
                    or type(job.get("accumulate")) is not int or job["accumulate"] not in (0, 1)
                    or type(execution.get("accumulate_epoch_observations")) is not int
                    or execution["accumulate_epoch_observations"] != job["accumulate"]):
                raise ValueError("Run cache/accumulation treatment differs from frozen plan")
            if (execution.get("freeze_sha256") != freeze_pin["sha256"]
                    or execution.get("native_binary_sha256") != native["sha256"]
                    or execution.get("config_sha256") != job["profile_sha256"]
                    or execution.get("command") != ["/usr/bin/taskset", "-c", str(cpu), native["path"], profile]
                    or execution.get("blas_openmp_threads") != 1
                    or execution.get("input_identity_after") != "verified"):
                raise ValueError("Run command/runtime/configuration identity differs from frozen plan")
            expected = run["final_generation"] - 1 if type(run["final_generation"]) is int else None
            sidecars = run["performance_sidecars"]
            if expected is None or len(sidecars) != expected:
                raise ValueError("Cache experiment lacks one performance sidecar per nuisance search")
            hits = 0
            for sidecar in sidecars:
                rows = [sidecar["parent_row_build"], sidecar["zero_update_replay"]["row_build"],
                        *[item["row_build"] for item in sidecar["ordinary_trials"]],
                        *[item["row_build"] for item in sidecar["arithmetic_audits"]],
                        *[item["row_build"] for items in sidecar["probe_rounds"] for item in items]]
                for row in rows:
                    if row.get("available") is not True:
                        continue
                    counters = [row.get(key) for key in ("interpolation_calls", "interpolation_cache_hits", "interpolation_evaluations")]
                    if (type(row.get("interpolation_cache")) is not bool or row["interpolation_cache"] != bool(cache)
                            or not all(type(value) is int and value >= 0 for value in counters)
                            or counters[0] != counters[1] + counters[2] or (not cache and counters[1])):
                        raise ValueError("Performance cache flags/counters conflict with declared treatment")
                    hits += counters[1]
            if cache and hits == 0:
                raise ValueError("No measured exact-cache hit demonstrates the enabled treatment")
        def inputs(job):
            return sorted((item["path"], item["sha256"]) for item in job["input_files"])
        if (selected[0]["accumulate"] != selected[1]["accumulate"] or selected[0]["method"] != selected[1]["method"]
                or selected[0]["source_profile"]["sha256"] != selected[1]["source_profile"]["sha256"]
                or inputs(selected[0]) != inputs(selected[1])):
            raise ValueError("Paired scientific fixture, inputs or accumulation differ")
        for pin in pins:
            if analysis.artifact(pin["path"])[0] != pin:
                raise ValueError("Frozen metadata changed during comparison")
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        issues.append({"message": str(error)})
    return {"verified": not issues, "issues": issues, "provenance": pins}


def compare(left, right, *, freeze=None, preparation=None):
    runs = []
    for root in (left, right):
        try:
            runs.append(inspect_run(root))
        except (OSError, ValueError, TypeError, AttributeError) as error:
            runs.append({"root": str(Path(root).resolve()), "issues": [{"message": str(error)}],
                "provenance": {}, "artifacts": {}, "values": {}, "removed_fields": {}, "execution": None,
                "profile_classification": "invalid_or_unfinished_profile", "final_generation": None, "execution_verified": False,
                "performance_sidecars": [], "performance": analysis.performance_summary([])})
    issues = [{"side": side, **issue} for side, run in zip(("off", "on"), runs) for issue in run["issues"]]
    a, b = runs
    native_a = (a["execution"] or {}).get("native_binary_sha256")
    native_b = (b["execution"] or {}).get("native_binary_sha256")
    if native_a != native_b:
        issues.append({"message": "Cache toggle pair must use the same native executable"})
    names = sorted(set(a["artifacts"]) | set(b["artifacts"]))
    comparisons = []
    for name in names:
        left_data, right_data = a["artifacts"].get(name), b["artifacts"].get(name)
        same = left_data is not None and right_data is not None and left_data == right_data
        comparisons.append({"artifact": name, "equal": same,
            "off_sha256": hashlib.sha256(left_data).hexdigest() if left_data is not None else None,
            "on_sha256": hashlib.sha256(right_data).hexdigest() if right_data is not None else None,
            "comparison": "exact canonical JSON after declared resource-field removal" if name.endswith(".json") else "exact uncompressed bytes"})
        if not same:
            issues.append({"message": "Missing, unmatched or changed scientific artifact", "file": name})
    for side, run in zip(("off", "on"), runs):
        for path, pin in run["provenance"].items():
            if analysis.artifact(path)[0] != pin:
                issues.append({"side": side, "message": "Input changed during comparison", "file": path})
    artifact_equality = bool(comparisons) and all(item["equal"] for item in comparisons)
    common = Path(left).resolve().parent
    cache_pair = bind_cache_pair(runs, freeze or common / "freeze.json", preparation or common / "preparation.json")
    issues.extend(cache_pair["issues"])
    passed = not issues and artifact_equality and cache_pair["verified"]
    public_runs = [{key: value for key, value in run.items() if key not in {"artifacts", "values", "provenance", "performance_sidecars"}}
                   | {"provenance": sorted(run["provenance"].values(), key=lambda item: item["path"])} for run in runs]
    return {"schema": "orbit-poc-nuisance-performance-pair-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "checker": analysis.artifact(__file__)[0], "analyzer_dependency": analysis.artifact(_ANALYZER)[0],
        "passed": passed, "artifact_equality": artifact_equality, "cache_pair_verified": cache_pair["verified"],
        "frozen_experiment": cache_pair, "scientific_comparison_count": len(comparisons), "comparisons": comparisons,
        "runs": public_runs, "issues": issues, "accepted_covariance": False,
        "whole_fit_convergence_established": False,
        "acceptance": "Exact scientific JSON values and uncompressed text/binary payloads; no numerical tolerance introduced.",
        "removed_fields": {"nuisance_line_search.trials[*]": list(STRIPPED_TRIAL_FIELDS)},
        "limitations": ["This is a fixed-orbit nuisance-profile equality check, not a full orbit fit or release gate.",
            "Floor-limited equality is progress-only evidence and cannot authorize covariance.",
            "Frozen native-input identity is checked through the execution manifest; this checker does not rerun the native process.",
            "Timing sidecars are partial nested measurements and are not summed into a claimed total cost."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("off", type=Path)
    parser.add_argument("on", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, help="Defaults to the off run's parent/freeze.json")
    parser.add_argument("--preparation", type=Path, help="Defaults to the off run's parent/preparation.json")
    args = parser.parse_args()
    result = compare(args.off, args.on, freeze=args.freeze, preparation=args.preparation)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
