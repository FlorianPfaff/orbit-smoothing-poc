#!/usr/bin/env python3
"""Check a frozen cost-only dynamic-design pair without running native code.

Scientific payloads and completion gates come from the unchanged performance
checker. This separate binder requires cache=1 and the full eight-job experiment.
An accepted pair cannot establish full-fit convergence or authorize covariance.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

DEPENDENCY = Path(__file__).with_name("check_nuisance_performance_pair.py")
_spec = importlib.util.spec_from_file_location("_cost_pair_scientific_checker", DEPENDENCY)
base = importlib.util.module_from_spec(_spec)
exec(compile(DEPENDENCY.read_bytes(), str(DEPENDENCY), "exec"), base.__dict__)
THREAD_KEYS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
               "NUMEXPR_NUM_THREADS", "BLIS_NUM_THREADS", "GOTO_NUM_THREADS")
FIXED_NATIVE = {"ORBIT_POC_NUISANCE_PERFORMANCE": "1",
                "ORBIT_POC_NUISANCE_INTERPOLATION_CACHE": "1",
                "ORBIT_POC_NUMERICS_KEEP_INTERMEDIATE_FACTORS": "1",
                "ORBIT_POC_NUMERICS_COMPRESS_ROW_PROVENANCE": "0"}
PRIOR = {"pulses": "constraint.pulses", "log_drag_ou": "constraint.logDensityOu"}


def exact_inputs(job):
    items = job["input_files"]
    if not isinstance(items, list) or not items:
        raise ValueError("Missing complete native input inventory")
    result = sorted((item["path"], item["sha256"]) for item in items)
    if len({path for path, _ in result}) != len(result):
        raise ValueError("Duplicate native input identity")
    return result


def verify_xml(source, actual, source_path, actual_path, accumulate):
    """Exact byte substitution, restricted to existing output/tmp XML leaves."""
    old, new = str(Path(source_path).parent), str(Path(actual_path).parent)
    if old == new or source.replace(old.encode(), new.encode()) != actual:
        raise ValueError("Profile differs from its source beyond exact output-root substitution")
    original, updated = ET.fromstring(source), ET.fromstring(actual)
    a, b = list(original.iter()), list(updated.iter())
    if len(a) != len(b):
        raise ValueError("XML element structure differs")
    changed = 0
    for before, after in zip(a, b):
        if (before.tag != after.tag or before.attrib != after.attrib or before.tail != after.tail):
            raise ValueError("XML structure, attributes or tail changed")
        if before.text != after.text:
            output = before.tag.startswith("outputfile") or (
                before.tag == "filename" and before.attrib.get("label") == "tmpDir")
            if (not output or len(before) or not before.text
                    or not before.text.startswith(old + "/")
                    or after.text != new + before.text[len(old):]
                    or ".." in Path(after.text).parts):
                raise ValueError("XML changed a non-output field or unsafe output path")
            changed += 1
    if not changed:
        raise ValueError("No isolated XML outputs")
    accumulation = [e.text for e in updated.iter("accumulateEpochObservations")]
    prefixes = [e.text for e in updated.iter("outputfilePrefix")]
    if accumulation != [str(accumulate)] or prefixes != [new + "/qr"]:
        raise ValueError("XML accumulation or QR output prefix differs from frozen treatment")
    return changed


def verify_metrics(run, flag):
    sidecars = run["performance_sidecars"]
    if type(run["final_generation"]) is not int or len(sidecars) != run["final_generation"] - 1:
        raise ValueError("Missing one performance sidecar per nuisance search")
    omissions, children_seen, hits = 0, 0, 0
    for sidecar in sidecars:
        rows = [(False, sidecar["parent_row_build"]),
                (True, sidecar["zero_update_replay"]["row_build"]),
                *[(True, x["row_build"]) for x in sidecar["ordinary_trials"]],
                *[(True, x["row_build"]) for x in sidecar["arithmetic_audits"]],
                *[(True, x["row_build"]) for group in sidecar["probe_rounds"] for x in group]]
        for child, row in rows:
            if row.get("available") is not True or row.get("completed") is not True:
                raise ValueError("Incomplete measured row build cannot prove treatment")
            if (row.get("cost_only") is not child or row.get("cost_only_design") is not bool(flag)
                    or row.get("interpolation_cache") is not True):
                raise ValueError("Measured row-build treatment differs from frozen settings")
            counters = [row.get(k) for k in ("interpolation_calls", "interpolation_cache_hits",
                                           "interpolation_evaluations", "omitted_dynamic_designs")]
            if not all(type(x) is int and x >= 0 for x in counters) or counters[0] != counters[1] + counters[2]:
                raise ValueError("Invalid interpolation or omission counters")
            calls, cache_hits, _, omitted = counters
            if (not child or not flag) and omitted:
                raise ValueError("Dynamic design omitted from a full build or disabled treatment")
            if child and flag and (omitted == 0 or calls != 0):
                raise ValueError("Enabled child did not exclusively omit dynamic interpolation")
            if child and not flag and calls == 0:
                raise ValueError("Disabled child did not exercise dynamic interpolation")
            omissions += omitted
            children_seen += int(child)
            hits += cache_hits
    if not children_seen or not hits or bool(omissions) != bool(flag):
        raise ValueError("No measured cache/child activity demonstrates the declared treatment")
    return {"child_builds": children_seen, "omitted_dynamic_designs": omissions,
            "interpolation_cache_hits": hits}


def verify_priors(run, method):
    rows = run["artifacts"].get("qr.1.rows.tsv")
    if rows is None:
        raise ValueError("Missing first-generation prior row provenance")
    reader = csv.DictReader(io.StringIO(rows.decode()), delimiter="\t")
    if reader.fieldnames != ["row", "epoch", "source", "rhs", "columns"]:
        raise ValueError("Unrecognized prior row provenance header")
    priors = [row for row in reader if row["source"] == PRIOR[method]]
    if not priors or any(not row["columns"] or not math.isfinite(float(row["rhs"]))
                         or float(row["rhs"]) == 0 for row in priors):
        raise ValueError("Original full nonzero physical-prior rows were not exercised")
    return {"source": PRIOR[method], "rows": len(priors), "nonzero_rhs_rows": len(priors)}


def bind_cost_pair(runs, freeze_path):
    issues, pins, observed, cached = [], {}, [], {}

    def read(path, expected=None):
        path = str(path)
        if path not in cached:
            if not Path(path).is_absolute():
                raise ValueError("Frozen file paths must be absolute")
            pin, data = base.analysis.artifact(path)
            pins[path], cached[path] = pin, data
        if expected is not None and pins[path]["sha256"] != expected:
            raise ValueError("Frozen file hash mismatch: " + path)
        return cached[path]

    def pinned(pin):
        return read(pin["path"], pin["sha256"])

    try:
        freeze_path = str(Path(freeze_path).resolve(strict=True))
        freeze = base.strict_json(read(freeze_path))
        if freeze.get("schema") != "orbit-poc-cost-only-pair-freeze-v1":
            raise ValueError("Unknown cost-only freeze schema")
        cpu = freeze.get("cpu")
        if type(cpu) is not int or cpu < 0 or freeze.get("one_numerical_thread") is not True:
            raise ValueError("Frozen CPU/thread controls are invalid")
        native = freeze["native"]
        pinned(native); pinned(freeze["runner"])
        build = base.strict_json(pinned(freeze["build_manifest"]))
        if build.get("executable_sha256") != native["sha256"]:
            raise ValueError("Build manifest does not bind the frozen native executable")
        pinned(freeze["supervisor"])
        libraries = freeze["libraries"]
        if (not isinstance(libraries, list) or not libraries
                or len({x["path"] for x in libraries}) != len(libraries)):
            raise ValueError("Missing or duplicate frozen runtime library inventory")
        for library in libraries:
            pinned(library)
        preparation = base.strict_json(pinned(freeze["source_preparation"]))
        if preparation.get("schema") != "orbit-poc-nuisance-pair-preparation-v1":
            raise ValueError("Unknown original scientific preparation")
        fixed = freeze["environment_fixed"]
        if not isinstance(fixed, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in fixed.items()):
            raise ValueError("Invalid frozen environment")
        if any(fixed.get(k) != "1" for k in THREAD_KEYS) or any(fixed.get(k) != v for k, v in FIXED_NATIVE.items()):
            raise ValueError("Frozen environment changes cache, instrumentation, factor retention or threading")
        if any(k.startswith("ORBIT_POC_") and k not in FIXED_NATIVE for k in fixed):
            raise ValueError("Unexpected fixed native option outside cost-only experiment")
        jobs = freeze["jobs"]
        treatments, names, profiles = set(), set(), set()
        for job in jobs:
            method, acc, flag = job["method"], job["accumulate"], job["cost_only_design"]
            if (method not in PRIOR or type(acc) is not int or acc not in (0, 1)
                    or type(flag) is not int or flag not in (0, 1) or type(job["cache"]) is not int or job["cache"] != 1):
                raise ValueError("Invalid frozen method/accumulation/cost/cache treatment")
            treatment = (method, acc, flag)
            if treatment in treatments or job["name"] in names or job["profile"] in profiles:
                raise ValueError("Duplicate frozen job identity or treatment")
            treatments.add(treatment); names.add(job["name"]); profiles.add(job["profile"])
            originals = [x for x in preparation["jobs"] if (x.get("method"), x.get("accumulate"), x.get("cache")) == (method, acc, 1)]
            if len(originals) != 1:
                raise ValueError("Original scientific fixture is not unique")
            old = originals[0]
            if (job["source_profile"] != {"path": old["profile"], "sha256": old["profile_sha256"]}
                    or exact_inputs(job) != exact_inputs(old)):
                raise ValueError("Original complete physical input inventory or source profile changed")
            for item in job["input_files"]:
                pinned(item)
            source = pinned(job["source_profile"])
            actual = read(job["profile"], job["profile_sha256"])
            verify_xml(source, actual, job["source_profile"]["path"], job["profile"], acc)
        expected = {(m, a, c) for m in PRIOR for a in (0, 1) for c in (0, 1)}
        if treatments != expected or len(jobs) != 8:
            raise ValueError("Freeze does not cover exactly eight predeclared treatments")
        selected = []
        for flag, run in enumerate(runs):
            if not run["execution_verified"]:
                raise ValueError("Cost-only treatment lacks verified completed execution")
            matches = [job for job in jobs if job["profile"] == str(Path(run["root"]) / "profile.xml")]
            if len(matches) != 1:
                raise ValueError("Run is not uniquely bound to frozen profile")
            job = matches[0]; selected.append(job)
            execution = run["execution"]
            for key, expected_value in (("cost_only_design", flag), ("cache", 1),
                                        ("accumulate_epoch_observations", job["accumulate"]), ("blas_openmp_threads", 1)):
                if type(execution.get(key)) is not int or execution[key] != expected_value:
                    raise ValueError("Execution treatment differs from frozen cost-only pair: " + key)
            environment = dict(fixed, ORBIT_POC_NUISANCE_COST_ONLY_DESIGN=str(flag),
                               ORBIT_POC_NUMERICS_QR_PREFIX=str(Path(run["root"]) / "qr"))
            if (job["cost_only_design"] != flag or execution.get("environment") != environment
                    or execution.get("freeze_sha256") != pins[freeze_path]["sha256"]
                    or execution.get("native_binary_sha256") != native["sha256"]
                    or execution.get("config_sha256") != job["profile_sha256"]
                    or execution.get("command") != ["/usr/bin/taskset", "-c", str(cpu), native["path"], job["profile"]]
                    or execution.get("input_identity_after") != "verified"):
                raise ValueError("Execution environment/command/configuration differs from frozen treatment")
            observed.append({"cost_only_design": flag, "metrics": verify_metrics(run, flag),
                             "prior_rows": verify_priors(run, job["method"])})
        if ((selected[0]["method"], selected[0]["accumulate"], selected[0]["source_profile"])
                != (selected[1]["method"], selected[1]["accumulate"], selected[1]["source_profile"])
                or exact_inputs(selected[0]) != exact_inputs(selected[1])):
            raise ValueError("Paired scientific fixtures or accumulation differ")
        for path, pin in pins.items():
            if base.analysis.artifact(path)[0] != pin:
                raise ValueError("Frozen input changed during comparison: " + path)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ET.ParseError) as error:
        issues.append({"message": str(error)})
    return {"verified": not issues, "issues": issues, "observed": observed,
            "provenance": [{"requested_path": path, **pin} for path, pin in sorted(pins.items())]}


def compare(off, on, *, freeze=None):
    runs = []
    for root in (off, on):
        try:
            runs.append(base.inspect_run(root))
        except (OSError, ValueError, TypeError, AttributeError) as error:
            runs.append({"root": str(Path(root).resolve()), "issues": [{"message": str(error)}],
                         "provenance": {}, "artifacts": {}, "values": {}, "removed_fields": {},
                         "execution": None, "execution_verified": False, "performance_sidecars": [],
                         "final_generation": None, "profile_classification": "invalid_or_unfinished_profile"})
    issues = [{"side": side, **issue} for side, run in zip(("off", "on"), runs) for issue in run["issues"]]
    comparisons = []
    a, b = runs
    for name in sorted(set(a["artifacts"]) | set(b["artifacts"])):
        left, right = a["artifacts"].get(name), b["artifacts"].get(name)
        same = left is not None and right is not None and left == right
        comparisons.append({"artifact": name, "equal": same,
            "off_sha256": hashlib.sha256(left).hexdigest() if left is not None else None,
            "on_sha256": hashlib.sha256(right).hexdigest() if right is not None else None,
            "comparison": "exact canonical JSON after existing trial resource-field removal" if name.endswith(".json") else "exact uncompressed bytes"})
        if not same:
            issues.append({"message": "Missing, unmatched or changed scientific artifact", "file": name})
    binding = bind_cost_pair(runs, freeze or Path(off).resolve().parent / "freeze.json")
    issues.extend(binding["issues"])
    for side, run in zip(("off", "on"), runs):
        for path, pin in run["provenance"].items():
            try:
                if base.analysis.artifact(path)[0] != pin:
                    raise ValueError("Scientific input changed during comparison")
            except (OSError, ValueError) as error:
                issues.append({"side": side, "message": str(error), "file": path})
    equal = bool(comparisons) and all(c["equal"] for c in comparisons)
    public = [{k: v for k, v in run.items() if k not in {"artifacts", "values", "provenance", "performance_sidecars"}}
              | {"provenance": sorted(run["provenance"].values(), key=lambda p: p["path"])} for run in runs]
    return {"schema": "orbit-poc-nuisance-cost-only-pair-v1", "created_at": datetime.now(timezone.utc).isoformat(),
        "checker": base.analysis.artifact(__file__)[0], "scientific_checker": base.analysis.artifact(DEPENDENCY)[0],
        "analyzer_dependency": base.analysis.artifact(base._ANALYZER)[0],
        "passed": not issues and equal and binding["verified"], "artifact_equality": equal,
        "cost_only_pair_verified": binding["verified"], "frozen_experiment": binding,
        "scientific_comparison_count": len(comparisons), "comparisons": comparisons, "runs": public, "issues": issues,
        "removed_fields": {"nuisance_line_search.trials[*]": list(base.STRIPPED_TRIAL_FIELDS)},
        "accepted_covariance": False, "whole_fit_convergence_established": False, "full_fit_verified": False,
        "release_authority": False,
        "limitations": ["Fixed-orbit nuisance profiles only; no full orbit fit or release acceptance.",
            "Floor-limited equality is progress-only evidence.", "No numerical tolerance or additional scientific-field exclusion is introduced.",
            "Execution/environment receipts are checked against frozen files; this checker does not rerun native code.",
            "Performance sidecars are partial nested measurements, not a claimed total runtime."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("off", type=Path)
    parser.add_argument("on", type=Path)
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.off, args.on, freeze=args.freeze)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
