"""Inclusive numerical benchmark report: every planned attempt stays visible."""
from collections import Counter
from decimal import Decimal
import html
import json
import math
from pathlib import Path
import statistics

from orbit_poc.comparison.protocol import canonical_hash, read_json, write_json
from .config import PROFILES, config_from_dict
from .protocol import (TERMINAL, artifact, attempt_job, project_root, resolve,
                       read_cartesian_estimate, validate_complete_result, verify_artifact)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _median(values):
    return statistics.median(values) if values else None


def objective_resolution(diagnostics):
    """Summarize explicit controller floor flags without inferring missing data."""
    if not isinstance(diagnostics, dict) or not isinstance(diagnostics.get("history"), list):
        return {"status": "unavailable", "reason": "No controller trial history retained"}
    trials = [row for row in diagnostics["history"] if isinstance(row, dict)
              and _number(row.get("actual_reduction"))]
    flagged = [row for row in trials if type(row.get("objective_reduction_numerically_resolved")) is bool]
    unresolved = [row for row in flagged if not row["objective_reduction_numerically_resolved"]]
    return {"status": "reported" if flagged else "unavailable", "evaluated_trials": len(trials),
        "flagged_trials": len(flagged), "trials_without_resolution_diagnostic": len(trials)-len(flagged),
        "unresolved_trials": len(unresolved) if flagged else None,
        "accepted_unresolved_trials": sum(row.get("accepted") is True for row in unresolved) if flagged else None,
        "unresolved_trial_evidence": [{key: row.get(key) for key in
            ("trial", "accepted", "actual_reduction", "predicted_reduction", "objective_floor", "gain_ratio")}
            for row in unresolved],
        "scope": "An unresolved objective change is at or below the measured numerical floor; its sign alone is not a resolved improvement or a convergence test"}


def nuisance_resolution(diagnostics):
    """Keep progress from empirically limited profiles distinct from convergence."""
    if not isinstance(diagnostics, dict) or not isinstance(diagnostics.get("history"), list):
        return {"status": "unavailable", "reason": "No controller trial history retained"}
    trials = [row for row in diagnostics["history"] if isinstance(row, dict) and _number(row.get("trial"))]
    flagged = [row for row in trials if any(type(row.get(key)) is bool for key in
               ("nuisance_floor_limited_before", "nuisance_floor_limited_trial"))]
    limited = [row for row in flagged if row.get("nuisance_floor_limited_before") is True
               or row.get("nuisance_floor_limited_trial") is True]
    checks = diagnostics.get("confirmation_checks", [])
    confirmations = [row for row in (checks if isinstance(checks, list) else []) if isinstance(row, dict)
                     and type(row.get("nuisance_floor_limited")) is bool]
    available = bool(flagged or confirmations)
    return {"status": "reported" if available else "unavailable", "flagged_trials": len(flagged),
        "trials_without_profile_diagnostic": len(trials)-len(flagged),
        "floor_limited_trials": len(limited) if available else None,
        "accepted_floor_limited_trials": sum(row.get("accepted") is True for row in limited) if available else None,
        "unresolved_profile_rejections": sum(row.get("reason") == "unresolved_nuisance_profile_reduction"
                                              for row in trials) if available else None,
        "floor_limited_confirmations": sum(row["nuisance_floor_limited"] for row in confirmations) if confirmations else None,
        "floor_limited_trial_evidence": [{key: row.get(key) for key in
            ("trial", "accepted", "reason", "nuisance_floor_limited_before", "nuisance_floor_limited_trial",
             "nuisance_resolution_sum", "predicted_reduction", "actual_reduction",
             "inexact_profile_forcing_ratio", "gain_ratio_after_profile_resolution")} for row in limited],
        "scope": "Empirical nuisance-resolution estimates permit only resolved nonfinal physical progress; they are not rigorous error bounds. Convergence and covariance still require a fresh strictly stationary nuisance profile."}



def execution_storage(reference):
    """Expose only hash-verified deployment policy; missing context stays unknown."""
    if not reference:
        return {"status": "unavailable", "reason": "No pinned execution context"}
    try:
        context = read_json(verify_artifact(reference))
        keys = ("storage_policy", "timing_policy", "archive_policy", "physical_backing_path",
                "writable_roots", "temporary_directory", "c_write_policy")
        return {"status": "reported", "context": reference,
                **{key: context[key] for key in keys if key in context}}
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        return {"status": "invalid", "context": reference, "error": str(error)}


def _one_artifact(row, role):
    choices = [item for item in row.get("artifacts", []) if item["role"] == role]
    if len(choices) != 1:
        raise ValueError(f"No unique retained {role} artifact")
    return verify_artifact(choices[0])


def _norm_summary(values):
    import numpy as np
    norms = np.linalg.norm(values, axis=tuple(range(1, values.ndim)))
    return {"rms": float(np.sqrt(np.mean(norms**2))), "maximum": float(np.max(norms))}


def _state_difference(first, second):
    import numpy as np
    def load(row):
        choices = [item for item in row.get("artifacts", []) if item["role"] == "state_estimate"]
        if len(choices) != 1: raise ValueError("No unique retained state_estimate artifact")
        return read_cartesian_estimate(choices[0])
    a, b = load(first), load(second)
    if not np.array_equal(a["mjd"], b["mjd"]):
        raise ValueError("State epoch grids differ; no interpolation performed")
    delta = b["states"] - a["states"]
    covariance = b["covariance"] - a["covariance"]
    return {"status": "compared", "matched_epochs": len(a["mjd"]), "epoch_matching": "exact GPS MJD; no interpolation",
        "position_difference_m": _norm_summary(delta[:, :3]),
        "velocity_difference_m_s": _norm_summary(delta[:, 3:]),
        "position_covariance_difference_m2": _norm_summary(covariance[:, :3, :3]),
        "velocity_covariance_difference_m2_s2": _norm_summary(covariance[:, 3:, 3:]),
        "cross_covariance_difference_m2_s": _norm_summary(covariance[:, :3, 3:]),
        "covariance_norm": "Frobenius within each block; different physical units are never combined"}


def _phase_rows(path):
    rows = {}
    expected = ["GPSMJD", "PRN", "type", "input_m", "processed_m", "removed_windup_m",
        "fitted_ambiguity_m", "receiver_bias_m", "transmitter_bias_m", "STEC", "TEC_factor_m",
        "residual_m", "sigma_m", "clock_m", "track_start_GPSMJD", "track_end_GPSMJD"]
    lines = Path(path).read_text().splitlines()
    if not lines or lines[0].lstrip("# ").split() != expected:
        raise ValueError("Unrecognized native phase-recovery column schema")
    for line in lines[1:]:
        if not line.strip() or line.startswith("#"): continue
        fields = line.split()
        if len(fields) != len(expected): raise ValueError("Incomplete carrier-phase recovery row")
        key = (Decimal(fields[0]), int(fields[1]), fields[2])
        values = [float(value) for value in fields[3:]]
        if not key[0].is_finite() or not all(math.isfinite(value) for value in values):
            raise ValueError("Nonfinite carrier-phase recovery row")
        if key in rows: raise ValueError("Duplicate epoch/PRN/signal in carrier-phase recovery")
        rows[key] = {name: value for name, value in zip(expected[3:], values)}
    if not rows: raise ValueError("No carrier-phase recovery observations")
    return rows


def _phase_difference(first, second):
    import numpy as np
    a, b = (_phase_rows(_one_artifact(row, "phase_recovery")) for row in (first, second))
    if a.keys() != b.keys():
        raise ValueError("Carrier-phase epoch/PRN/type support differs; no intersection-only comparison")
    difference, standardized = [], []
    for key in sorted(a):
        x, y = a[key], b[key]
        for field in ("input_m", "sigma_m", "track_start_GPSMJD", "track_end_GPSMJD"):
            if x[field] != y[field]:
                raise ValueError(f"Carrier-phase input/support differs in {field}")
        if x["sigma_m"] <= 0: raise ValueError("Carrier-phase weight is nonpositive")
        # Same observed y: predicted y = y - residual, including fitted nuisances.
        value = x["residual_m"] - y["residual_m"]
        difference.append(value); standardized.append(value / x["sigma_m"])
    def summary(values):
        values = np.asarray(values)
        return {"rms": float(np.sqrt(np.mean(values**2))), "maximum_absolute": float(np.max(np.abs(values)))}
    return {"status": "compared", "matched_observations": len(a),
        "prediction_difference_m": summary(difference),
        "prediction_difference_in_assumed_sigmas": summary(standardized),
        "matching": "Exact epoch/PRN/type sets and identical input values, weights and ambiguity-track bounds",
        "scope": "Fitted carrier-phase predictions including nuisance terms; delta prediction = -delta native residual"}


def numerical_comparisons(rows):
    comparisons = []
    for case_id in dict.fromkeys(row["case_id"] for row in rows):
        group = {row["profile"]: row for row in rows if row["case_id"] == case_id}
        for label, left, right in (("solver_only", PROFILES[0], PROFILES[1]),
                                  ("derivative_change", PROFILES[1], PROFILES[2])):
            first, second = group[left], group[right]
            record = {"case_id": case_id, "comparison": label, "from_profile": left, "to_profile": right,
                "origin": first["origin"], "method": first["method"],
                "code_predictions": {"status": "unavailable", "reason": "No direct code prediction export is available"}}
            for key, function in (("state_and_covariance", _state_difference), ("carrier_phase_predictions", _phase_difference)):
                if not first["valid"] or not second["valid"]:
                    record[key] = {"status": "unavailable", "reason": "Both profiles must have valid posteriors",
                        "profile_statuses": [first["status"], second["status"]]}
                    continue
                try: record[key] = function(first, second)
                except (OSError, ValueError, RuntimeError, KeyError, ArithmeticError) as error:
                    record[key] = {"status": "unavailable", "reason": str(error)}
            comparisons.append(record)
    return comparisons


REQUIRED_GATES = ("qr_independent_agreement", "rank_and_invariance", "objective_and_priors",
    "rollback_and_convergence", "synthetic_derivatives", "flight_derivative_approximation",
    "propagation_refinement", "pipeline_and_provenance")


def acceptance_gates(context_reference):
    """Display pinned, explicitly scoped gate receipts independently of fit counts."""
    declared = []
    context_error = None
    if context_reference:
        try:
            context = read_json(verify_artifact(context_reference))
            declared = context.get("acceptance_gates", [])
            if not isinstance(declared, list): raise ValueError("Acceptance gates must be a list")
        except (OSError, RuntimeError, ValueError) as error:
            context_error = str(error)
    rows = []
    for name in REQUIRED_GATES:
        matches = [entry for entry in declared if isinstance(entry, dict) and entry.get("gate") == name]
        row = {"gate": name, "status": "pending", "scope": "No pinned acceptance receipt supplied", "receipt": None}
        if context_error: row["error"] = context_error
        elif len(matches) > 1: row.update(status="invalid", error="Duplicate gate declarations")
        elif matches:
            entry = matches[0]
            try:
                if set(entry) != {"gate", "status", "scope", "receipt"} or entry["status"] not in {"passed", "failed", "pending"} or not entry["scope"]:
                    raise ValueError("Invalid gate declaration")
                verify_artifact(entry["receipt"])
                row = dict(entry)
            except (OSError, RuntimeError, ValueError, KeyError) as error:
                row.update(status="invalid", error=str(error))
        rows.append(row)
    return rows


def create_report(config, output_dir=None, *, project=None):
    project = Path(project or project_root())
    root = resolve(output_dir or config.output_dir, project)
    plan = read_json(root / "plan.json")
    if plan.get("plan_hash") != canonical_hash({k: v for k, v in plan.items() if k != "plan_hash"}):
        raise ValueError("Cannot report a changed numerical plan")
    if len(plan["cases"]) != 50 or len(plan["attempts"]) != 150:
        raise ValueError("The report requires the entire frozen 50-case/150-attempt plan")
    manifest = read_json(root / "manifest.json") if (root / "manifest.json").exists() else None
    if manifest and (manifest.get("manifest_hash") != canonical_hash({k: v for k, v in manifest.items() if k != "manifest_hash"})
                     or manifest["plan_hash"] != plan["plan_hash"]):
        raise ValueError("Cannot report a changed numerical input freeze")
    cases = {item["case_id"]: item for item in (manifest or plan)["cases"]}
    input_errors = {}
    if manifest:
        checked = {}
        for case in manifest["cases"]:
            errors = []
            for item in case["input_inventory"]:
                key = (item["path"], item["sha256"])
                if key not in checked:
                    try: verify_artifact(item); checked[key] = None
                    except (OSError, ValueError, RuntimeError) as error: checked[key] = str(error)
                if checked[key]: errors.append(checked[key])
            if errors: input_errors[case["case_id"]] = sorted(set(errors))
    rows = []
    for attempt in plan["attempts"]:
        case = cases[attempt["case_id"]]
        directory = root / "attempts" / attempt["attempt_id"]
        row = {**attempt, "origin": case["origin"], "method": case["method"],
               "status": "not_run", "valid": False, "elapsed_seconds": None,
               "peak_rss_bytes": None, "numerical_diagnostics": None, "error": None,
               "objective_resolution": objective_resolution(None),
               "nuisance_resolution": nuisance_resolution(None)}
        archive_receipt = root / "archive-index" / (attempt["attempt_id"] + ".json")
        if archive_receipt.is_file():
            row["archive"] = {"receipt": artifact(archive_receipt),
                              "record": {key: value for key, value in read_json(archive_receipt).items() if key != "inventory"}}
        if (directory / "result-record.json").exists():
            try:
                index = read_json(directory / "result-record.json")
                path = verify_artifact(index["result"])
                result = read_json(path)
                request = read_json(directory / "request.json")
                if (index["attempt_id"] != attempt["attempt_id"] or index["profile"] != attempt["profile"]
                        or index["request_hash"] != canonical_hash(request)
                        or result.get("request_hash") != index["request_hash"]
                        or result.get("status") != index["status"]
                        or result.get("numerics_profile") != attempt["profile"]
                        or not manifest or result.get("numerics_manifest_hash") != manifest["manifest_hash"]
                        or result.get("input_manifest_hash") != case["input_manifest_hash"]):
                    raise ValueError("Attempt checkpoint does not match the frozen case/profile/input identity")
                if request != attempt_job(config_from_dict(plan["config"]), manifest, case, attempt):
                    raise ValueError("Checkpoint request differs from the frozen job recipe")
                for item in result.get("artifacts", []): verify_artifact(item)
                status = result["status"]
                if status not in TERMINAL: raise ValueError("Unknown terminal attempt status")
                if status == "complete": validate_complete_result(result, request)
                execution = result.get("harness_execution", {})
                row.update(status=status, valid=bool(status == "complete" and result.get("converged")
                           and result.get("covariance_valid")), elapsed_seconds=execution.get("elapsed_seconds"),
                           peak_rss_bytes=execution.get("peak_process_tree_rss_bytes"),
                           numerical_diagnostics=result.get("numerical_diagnostics"), error=result.get("error"),
                           objective_resolution=objective_resolution(result.get("numerical_diagnostics")),
                           nuisance_resolution=nuisance_resolution(result.get("numerical_diagnostics")),
                           preprocessing_audit_sha256=result.get("preprocessing_audit_sha256"),
                           converged=result.get("converged", False), covariance_valid=result.get("covariance_valid", False),
                           result=index["result"], artifacts=result.get("artifacts", []))
                for name in ("elapsed_seconds", "peak_rss_bytes"):
                    if row[name] is not None and (not _number(row[name]) or row[name] < 0):
                        raise ValueError("Invalid measured resource statistic")
            except (OSError, KeyError, ValueError, RuntimeError) as error:
                row.update(status="integrity_error", valid=False, error=str(error))
        elif directory.exists() and any(directory.iterdir()):
            row.update(status="interrupted_or_running", error="No terminal checkpoint; never retried automatically")
        if case["case_id"] in input_errors:
            row.update(status="integrity_error", valid=False,
                       error="Frozen estimation inputs changed: " + "; ".join(input_errors[case["case_id"]]))
        rows.append(row)
    for case_id in cases:
        matched = [r for r in rows if r["case_id"] == case_id and r["valid"]]
        if len({r["preprocessing_audit_sha256"] for r in matched}) > 1:
            for row in matched:
                row.update(status="integrity_error", valid=False,
                    error="Profiles disagree on frozen observation support/weights")
    profiles = []
    for profile in PROFILES:
        subset = [r for r in rows if r["profile"] == profile]
        if len(subset) != 50: raise ValueError("A profile is missing planned benchmark attempts")
        resources = [r for r in subset if _number(r["elapsed_seconds"])]
        profiles.append({"profile": profile, "expected_attempts": 50,
            "status_counts": dict(sorted(Counter(r["status"] for r in subset).items())),
            "valid_attempts": sum(r["valid"] for r in subset),
            "valid_fraction_of_all_planned": sum(r["valid"] for r in subset)/50,
            "measured_attempts": len(resources),
            "objective_resolution_available_attempts": sum(r["objective_resolution"]["status"] == "reported" for r in subset),
            "accepted_unresolved_objective_trials": sum(r["objective_resolution"]["accepted_unresolved_trials"] or 0 for r in subset if r["objective_resolution"]["status"] == "reported") if any(r["objective_resolution"]["status"] == "reported" for r in subset) else None,
            "nuisance_resolution_available_attempts": sum(r["nuisance_resolution"]["status"] == "reported" for r in subset),
            "accepted_floor_limited_nuisance_trials": sum(r["nuisance_resolution"]["accepted_floor_limited_trials"] or 0 for r in subset if r["nuisance_resolution"]["status"] == "reported") if any(r["nuisance_resolution"]["status"] == "reported" for r in subset) else None,
            "elapsed_seconds_total_all_measured_attempts": sum(r["elapsed_seconds"] for r in resources),
            "elapsed_seconds_median_all_measured_attempts": _median([r["elapsed_seconds"] for r in resources]),
            "elapsed_seconds_median_valid_attempts": _median([r["elapsed_seconds"] for r in resources if r["valid"]]),
            "peak_rss_bytes_maximum": max((r["peak_rss_bytes"] for r in subset if _number(r["peak_rss_bytes"])), default=None)})
    paired = []
    for profile in PROFILES[1:]:
        ratios = []; transitions = Counter()
        for case_id in cases:
            baseline = next(r for r in rows if r["case_id"] == case_id and r["profile"] == "legacy_v3")
            candidate = next(r for r in rows if r["case_id"] == case_id and r["profile"] == profile)
            transitions[f"baseline_{'valid' if baseline['valid'] else baseline['status']}__candidate_{'valid' if candidate['valid'] else candidate['status']}"] += 1
            if baseline["valid"] and candidate["valid"] and _number(baseline["elapsed_seconds"]) and baseline["elapsed_seconds"] > 0 and _number(candidate["elapsed_seconds"]):
                ratios.append(candidate["elapsed_seconds"]/baseline["elapsed_seconds"])
        paired.append({"profile": profile, "all_50_case_outcomes": dict(sorted(transitions.items())),
            "jointly_valid_timed_pairs": len(ratios), "median_candidate_over_baseline_seconds": _median(ratios),
            "scope": "Descriptive timing among jointly valid pairs; all failures and missing attempts remain in the 50-case outcome table"})
    strata = []
    for origin in sorted({r["origin"] for r in rows}):
        for profile in PROFILES:
            subset = [r for r in rows if r["origin"] == origin and r["profile"] == profile]
            strata.append({"origin": origin, "profile": profile, "expected_attempts": len(subset),
                "valid_attempts": sum(r["valid"] for r in subset),
                "status_counts": dict(sorted(Counter(r["status"] for r in subset).items()))})
    terminal = sum(r["status"] in TERMINAL for r in rows)
    gates = acceptance_gates(manifest.get("execution_context") if manifest else None)
    all_gates_passed = all(row["status"] == "passed" for row in gates)
    result = {"schema_version": 1, "name": plan["name"], "plan_hash": plan["plan_hash"],
        "manifest_hash": manifest["manifest_hash"] if manifest else None,
        "execution_context": manifest.get("execution_context") if manifest else None,
        "execution_storage": execution_storage(manifest.get("execution_context") if manifest else None),
        "retention_policy": "generated_intermediates_v1",
        "source": plan["source"], "expected_cases": 50, "expected_attempts": 150,
        "terminal_attempts": terminal, "execution_complete": terminal == 150,
        "acceptance_gates": gates, "all_correctness_gates_passed": all_gates_passed,
        "release_status": "ready_for_review" if terminal == 150 and all_gates_passed else "pending",
        "all_attempts_valid": all(r["valid"] for r in rows), "profiles": profiles, "paired": paired,
        "strata": strata, "input_integrity_errors": input_errors,
        "numerical_comparisons": numerical_comparisons(rows),
        "attempts": rows, "scientific_accuracy_comparison": False,
        "limitations": ["150 terminal attempts establish execution completion only; release remains pending without every pinned correctness gate. Flight derivative evidence quantifies an approximation.",
            "Objective changes at or below the measured numerical floor are reported explicitly, including accepted trials. Their sign alone cannot establish a resolved improvement; convergence still requires a fresh undamped correction and gradient.",
            "Accepted progress involving empirically floor-limited nuisance profiles is counted separately. The summed endpoint resolution estimate must be at most 0.001 of predicted improvement, and the gain ratio after subtracting that estimate must exceed 0.0001. This empirical estimate is not a rigorous error bound or a proof of a nuisance minimum. Floor-limited profiles cannot establish convergence or accepted covariance.",
            "The benchmark measures numerical reliability and cost at fixed statistical settings; it does not establish orbit accuracy superiority.",
            "Retained failure and slow-convergence fixtures are deliberately selected stress cases; report them separately from the 32 prospective cases.",
            "Prospective cells share the two seeds 510000 and 510001; coverage variants and methods reuse underlying realizations. These fits are dependent, not 32 independent statistical trials. Timing ratios are descriptive and carry no independence-based confidence intervals.",
            "The legacy-to-QR comparison includes the new solver/controller, GNSS interpolation/time/range arithmetic stabilization, and nuisance-coordinate bookkeeping corrections, including code/TEC prior coordinates after ambiguity recentering. Both new profiles share the forward arithmetic changes; physical forces, observation weights and intended statistical models are unchanged. It is not a pure linear-algebra replacement. Identical-row solver equivalence is a separate correctness gate.",
            "The comparison between the two new profiles combines staged tangent derivatives with local long-double accumulation of mean-force integration moments. Physical forces, quadrature weights and windows are unchanged, but this is not a Jacobian-only contrast. Selected refinement checks bound the combined numerical change without separating its contributions.",
            "Missing legacy diagnostics remain unavailable, not zero. No raw objective comparison is made across different methods or statistical settings.",
            "Trajectory/covariance differences and fitted carrier-phase prediction differences are numerical diagnostics, not errors against truth. Direct code prediction differences are unavailable.",
            "Terminal compaction and archival occur outside measured fitting time. Online row compression and released-factor cleanup are included in fitting time and retain verification receipts; original inputs and every final artifact remain available.",
            "Timing is end-to-end isolated worker time including the deployment filesystem I/O; it is not an intrinsic solver CPU-speed measurement. Reported peak memory is the outer harness's sampled summed RSS of the worker and recursive children, including native nuisance line-search children; shared pages may be counted more than once. Native parent RSS and per-child wait4 maxima remain separate diagnostics and are not substituted for a measured simultaneous process-tree peak.",
            "Runtime ratios are conditional on joint success. All 150 planned attempts, including failures and missing attempts, remain visible."],
        "input_freeze": artifact(root / "manifest.json") if manifest else None}
    destination = root / "report"; destination.mkdir(parents=True, exist_ok=True)
    write_json(destination / "report.json", result)
    def esc(value): return html.escape(str(value))
    def value(x): return "unavailable" if x is None else f"{x:.6g}" if _number(x) else esc(x)
    sections = ["<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>v3.1 numerical benchmark</title>",
        "<style>body{max-width:1200px;margin:32px auto;padding:0 20px;font:15px/1.5 system-ui;color:#172334}table{border-collapse:collapse;width:100%;margin:20px 0}th,td{text-align:left;padding:8px;border-bottom:1px solid #ddd}th{background:#edf2f7}code{overflow-wrap:anywhere}pre{white-space:pre-wrap;font-size:12px}details{max-width:440px}.bad{color:#9b2c2c}.good{color:#176342}</style>",
        f"<h1>{esc(plan['name'])}</h1><p>{terminal} / 150 attempts have terminal checkpoints. Every planned attempt appears below.</p>",
        "<p>Numerical reliability at fixed statistical settings. No orbit-accuracy or scientific-superiority claim.</p>",
        f"<p>Plan <code>{esc(plan['plan_hash'])}</code><br>Input freeze <code>{esc(result['manifest_hash'] or 'not complete')}</code></p>",
        "<h2>All planned attempts by profile</h2><table><tr><th>Profile</th><th>Valid / planned</th><th>Statuses</th><th>Total measured seconds</th><th>Peak tree RSS bytes</th><th>Accepted unresolved gains</th><th>Accepted inexact-profile steps</th></tr>"]
    sections[-1:-1] = ["<h2>Execution storage and timing</h2><p>All profiles use the frozen shared deployment. Worker wall time includes its filesystem I/O; these timings do not isolate intrinsic solver CPU speed.</p><pre>" + esc(json.dumps(result["execution_storage"], indent=2)) + "</pre>"]
    sections[-1:-1] = [f"<h2>Release acceptance gates</h2><p>Execution complete: {terminal == 150}. Release status: {esc(result['release_status'])}. Terminal failures count toward execution completion, not correctness.</p><table><tr><th>Gate</th><th>Status</th><th>Scope</th><th>Pinned receipt</th></tr>"] + [
        f"<tr><td>{esc(g['gate'])}</td><td>{esc(g['status'])}</td><td>{esc(g['scope'])}</td><td><code>{esc(json.dumps(g.get('receipt')))}</code>{esc(g.get('error',''))}</td></tr>" for g in gates] + ["</table>"]
    for row in profiles:
        sections.append(f"<tr><td>{esc(row['profile'])}</td><td>{row['valid_attempts']} / 50</td><td>{esc(json.dumps(row['status_counts']))}</td><td>{value(row['elapsed_seconds_total_all_measured_attempts'])}</td><td>{value(row['peak_rss_bytes_maximum'])}</td><td>{value(row['accepted_unresolved_objective_trials'])}</td><td>{value(row['accepted_floor_limited_nuisance_trials'])}</td></tr>")
    sections.append("</table><h2>Retained stress fixtures and prospective cases</h2><table><tr><th>Stratum</th><th>Profile</th><th>Valid / planned</th><th>Statuses</th></tr>")
    for row in strata:
        sections.append(f"<tr><td>{esc(row['origin'])}</td><td>{esc(row['profile'])}</td><td>{row['valid_attempts']} / {row['expected_attempts']}</td><td>{esc(json.dumps(row['status_counts']))}</td></tr>")
    sections.append("</table><h2>Paired timing and outcomes</h2><p>Timing ratios are descriptive. Prospective cells share two seeds; coverage variants and methods are dependent. No independence-based confidence intervals are reported.</p>")
    for row in paired:
        sections.append(f"<h3>{esc(row['profile'])}</h3><p>Jointly valid timed pairs: {row['jointly_valid_timed_pairs']}; median candidate/baseline time: {value(row['median_candidate_over_baseline_seconds'])}.</p><pre>{esc(json.dumps(row['all_50_case_outcomes'],indent=2))}</pre>")
    sections.append("<h2>Matched numerical differences</h2><p>Legacy-to-QR differences include solver/controller, shared GNSS interpolation/time/range arithmetic stabilization and nuisance-coordinate bookkeeping corrections; identical-row solver equivalence is tested separately. The two new profiles combine staged derivatives and mean-force integration arithmetic changes. Carrier-phase differences include fitted nuisance parameters; direct code predictions are unavailable. All 100 planned pairs remain visible.</p><table><tr><th>Case</th><th>Comparison</th><th>State/covariance</th><th>Carrier phase</th><th>Evidence</th></tr>")
    for row in result["numerical_comparisons"]:
        comparison_label = {"solver_only": "Solver/controller, forward arithmetic and bookkeeping", "derivative_change": "Staged derivatives and integration arithmetic"}.get(row["comparison"], row["comparison"])
        sections.append(f"<tr><td>{esc(row['case_id'])}</td><td>{esc(comparison_label)}</td><td>{esc(row['state_and_covariance']['status'])}</td><td>{esc(row['carrier_phase_predictions']['status'])}</td><td><details><summary>Numerical differences</summary><pre>{esc(json.dumps(row,indent=2))}</pre></details></td></tr>")
    sections.append("</table><h2>Complete attempt ledger</h2><table><tr><th>Case</th><th>Profile</th><th>Status</th><th>Seconds</th><th>Peak bytes</th><th>Accepted unresolved gains</th><th>Diagnostics / failure</th></tr>")
    for row in rows:
        details = {"error": row["error"], "numerical_diagnostics": row["numerical_diagnostics"],
                   "objective_resolution": row["objective_resolution"],
                   "nuisance_resolution": row["nuisance_resolution"],
                   "result": row.get("result"), "artifacts": row.get("artifacts", []), "archive": row.get("archive")}
        sections.append(f"<tr><td>{esc(row['case_id'])}<br><small>{esc(row['origin'])}</small></td><td>{esc(row['profile'])}</td><td class='{'good' if row['valid'] else 'bad'}'>{esc(row['status'])}</td><td>{value(row['elapsed_seconds'])}</td><td>{value(row['peak_rss_bytes'])}</td><td>{value(row['objective_resolution'].get('accepted_unresolved_trials'))}</td><td><details><summary>Recorded evidence</summary><pre>{esc(json.dumps(details,indent=2))}</pre></details></td></tr>")
    sections.append("</table><h2>Interpretation and limitations</h2><ul>" + "".join(f"<li>{esc(x)}</li>" for x in result["limitations"]) + "</ul></html>")
    (destination / "index.html").write_text("\n".join(sections)+"\n")
    return {"status": "complete" if terminal == 150 else "partial", "terminal_attempts": terminal,
            "expected_attempts": 150, "html": str(destination / "index.html"), "report": str(destination / "report.json")}
