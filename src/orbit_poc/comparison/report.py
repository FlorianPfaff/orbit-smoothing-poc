"""Registry-driven HTML report; orchestration completion never implies acceptance."""
from __future__ import annotations

from collections import Counter
from html import escape
import json
import math
from pathlib import Path

from .metrics import fixed_epoch_coverage, paired_seed_statistics


def _plain(value):
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "tolist"):
        return _plain(value.tolist())
    return value


def _methods(manifest):
    registry = manifest.get("method_registry", manifest.get("methods", []))
    if isinstance(registry, dict):
        result = {str(key): str(value.get("label", value.get("name", key))) if isinstance(value, dict)
                  else str(value) for key, value in registry.items()}
    else:
        result = {}
        for item in registry:
            if isinstance(item, dict):
                key = str(item.get("id", item.get("method_id", item.get("name"))))
                result[key] = str(item.get("label", item.get("name", key)))
            else:
                result[str(item)] = str(item)
    for row in manifest.get("runs", []):
        key = str(row.get("method_id", row.get("method", "unknown")))
        result.setdefault(key, key)
    return result


def _flatten(row):
    case = row.get("case", {})
    if not isinstance(case, dict):
        case = {"id": str(case)}
    from .protocol import read_result_record
    fit = read_result_record(row["fit_record"]) if "fit_record" in row else row.get("fit", row)
    evaluation = (read_result_record(row["evaluation_record"]) if "evaluation_record" in row
                  else row.get("evaluation", {}))
    evaluation_status = evaluation.get("status", "unknown" if "fit" in row or "fit_record" in row else "complete")
    cell = row.get("cell_id") or "/".join(str(case[key]) for key in
        ("orbit", "spacecraft", "atmosphere", "coverage") if key in case) or "all"
    return {"method_id": str(row.get("method_id", row.get("method", "unknown"))),
            "cell_id": cell, "seed": row.get("seed", case.get("seed", case.get("date"))),
            "coverage": case.get("coverage", row.get("coverage")),
            "status": row.get("status", fit.get("status", "unknown")),
            "converged": fit.get("converged", False), "covariance_valid": fit.get("covariance_valid", False),
            "evaluation_status": evaluation_status,
            "evaluation_complete": evaluation_status == "complete",
            "metrics": evaluation.get("metrics", row.get("metrics", fit.get("metrics", {}))),
            "elapsed_seconds": fit.get("elapsed_seconds"), "peak_rss_bytes": fit.get("peak_rss_bytes"),
            "error": row.get("error") or evaluation.get("error") or fit.get("error"),
            "result_path": row.get("result_path")}


def _valid(row):
    return (row["status"] == "complete" and row["converged"] is True
            and row["covariance_valid"] is True and row["evaluation_complete"])


def _number(value):
    if value is None:
        return "unavailable"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return f"{value:.6g}"
    if isinstance(value, (list, tuple)):
        return "; ".join(_number(item) for item in value)
    return escape(str(value))


def _table(headers, rows):
    head = "".join(f"<th>{escape(str(header))}</th>" for header in headers)
    body = "".join("<tr>" + "".join(f"<td>{_number(value)}</td>" for value in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>" if body else "<p>No records available.</p>"


def create_report(manifest: dict, output_dir: Path) -> dict:
    # Keep large epoch residual/covariance arrays in their scored artifacts.
    # Verify every indexed job and load only the fields the report consumes.
    from .protocol import file_hash, read_result_record
    for item in manifest.get("jobs", []):
        if "result_sha256" in item and file_hash(item["result_path"]) != item["result_sha256"]:
            raise ValueError("Job result bytes changed after checkpoint")
    if manifest.get("calibration"):
        calibration = dict(manifest["calibration"])
        calibration_rows = []
        for row in calibration.get("runs") or []:
            if "result_record" in row:
                result = read_result_record(row["result_record"])
                row = {**row, "score": result.get("calibration_score"),
                       "error": result.get("error", row.get("error"))}
            calibration_rows.append(row)
        calibration["runs"] = calibration_rows
        manifest = {**manifest, "calibration": calibration}
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    registry = _methods(manifest)
    rows = [_flatten(row) for row in manifest.get("runs", [])]
    planned_methods = _methods({name: manifest[name] for name in ("methods", "method_registry") if name in manifest})
    planned_rows = ([_flatten({"case": case, "method": method})
                     for case in manifest["planned_cases"] for method in planned_methods]
                    if "planned_cases" in manifest else None)
    counts = []
    for method, label in registry.items():
        selected = [row for row in rows if row["method_id"] == method]
        statuses = Counter(row["status"] for row in selected)
        counts.append({"method_id": method, "label": label, "attempted": len(selected),
                       "valid": sum(_valid(row) for row in selected),
                       "invalid_or_incomplete": sum(not _valid(row) for row in selected), "statuses": dict(statuses)})
    complete = manifest.get("complete") is True
    key = lambda row: (row["cell_id"], row["method_id"], row["seed"])
    observed_keys = [key(row) for row in rows]
    planned_keys = {key(row) for row in planned_rows} if planned_rows is not None else None
    design_complete = (planned_keys is None or
                       len(observed_keys) == len(planned_keys) and set(observed_keys) == planned_keys)
    all_valid = bool(rows and complete and design_complete and all(_valid(row) for row in rows))
    failures = [row for row in rows if not _valid(row)]
    gates = manifest.get("gates", manifest.get("acceptance_gates", {}))
    from .gates import PRECALIBRATION_GATES
    gates_passed = isinstance(gates, dict) and all(
        gates.get(name) is True or isinstance(gates.get(name), dict) and gates[name].get("passed") is True
        for name in PRECALIBRATION_GATES)
    synthetic = manifest.get("stage", "synthetic") == "synthetic"
    paired, all_paired, coverage, metrics_error = [], [], [], None
    if synthetic and (rows or planned_rows):
        try:
            # Duplicate seeds or malformed records are evidence problems; report
            # them rather than silently dropping repeated/failed experiments.
            analysis_rows = [{**row, "status":row["status"] if row["evaluation_complete"] else "evaluation_incomplete"}
                             for row in rows]
            paired = paired_seed_statistics(analysis_rows, planned_records=planned_rows)
            metric_names = [f"{window}.{metric}" for window in ("whole_arc", "gap") for metric in (
                "position_rmse_m", "rtn_rmse_m.0", "rtn_rmse_m.1", "rtn_rmse_m.2",
                "position_nll", "position_nees", "maximum_joint_95_semimajor_axis_m")]
            all_paired = [comparison for metric in metric_names
                          for comparison in paired_seed_statistics(analysis_rows, metric=metric, planned_records=planned_rows)]
            coverage = fixed_epoch_coverage(analysis_rows, planned_records=planned_rows)
        except (ValueError, TypeError) as error:
            metrics_error = str(error)
    summary = {"schema_version": manifest.get("schema_version", 3), "stage": manifest.get("stage"),
               "status": manifest.get("status", "unknown"), "orchestration_complete": complete,
               "all_fits_valid": all_valid, "numerical_gates_passed": gates_passed,
               "superiority_claim_issued": False, "method_counts": counts, "paired_seed_comparisons": paired,
               "paired_metrics": all_paired, "primary_cell": manifest.get("primary_cell"),
               "fixed_epoch_coverage": coverage, "failures": failures, "metrics_error": metrics_error,
               "expected_fits": manifest.get("expected_fits"), "observed_fits": len(rows),
               "planned_fit_rows": len(planned_rows) if planned_rows is not None else None,
               "planned_design_complete": design_complete,
               "missing_planned_fits": len(planned_keys - set(observed_keys)) if planned_keys is not None else None,
               "source_hash": manifest.get("source_hash"), "protocol_hash": manifest.get("protocol_hash"),
               "selection_hash": manifest.get("selection_hash"), "gates": gates,
               "execution_platform": manifest.get("execution_platform"),
               "concurrent_workers": manifest.get("concurrent_workers"),
               "calibration_adequate": manifest.get("calibration_adequate"),
               "calibration_disclosures": manifest.get("calibration_disclosures", []),
               "calibration": manifest.get("calibration"),
               "development_evidence": manifest.get("development_evidence", {}),
               "scope": manifest.get("scope"), "limitations": manifest.get("limitations", []),
               "interpretation": "Comparative statistics describe valid paired seeds; failure counts remain explicit. A completed job or report is not scientific acceptance. Flight reference agreement is not known truth."}
    notices = []
    if manifest.get("scope"):
        notices.append(str(manifest["scope"]))
    notices.extend(str(item) for item in manifest.get("limitations", []))
    notices.extend(str(item) for item in manifest.get("calibration_disclosures", []))
    if manifest.get("calibration_adequate") is False:
        notices.append("Calibration remains limited by an improving grid boundary. Evaluation uses the frozen best fully scored candidate; superiority claims are withheld.")
    if not complete:
        notices.append("The comparison is incomplete. No final comparative claim is supported.")
    if not design_complete:
        notices.append("Some frozen planned fits have no result row. They remain missing in every affected seed denominator.")
    if failures:
        notices.append(f"{len(failures)} fits are invalid or incomplete. Paired statistics report their missing/failed seed counts.")
    if not gates_passed:
        notices.append("Numerical acceptance gates are missing or have not all passed.")
    if metrics_error:
        notices.append("Metric aggregation was not accepted: " + metrics_error)
    if not synthetic:
        notices.append("Flight SLR residuals are independent predictive checks. Differences to a flight reference describe agreement, not error against known truth.")
    notices.append("Method superiority is not inferred automatically from completion or a surviving subset of fits.")
    sections = ["<h1>Native orbit smoothing comparison</h1>",
                "<p>Predeclared primary cell: <strong>" + escape(" / ".join(manifest.get("primary_cell", []))) + "</strong>. Other cells are secondary.</p>",
                "<p>Frozen protocol: <code>" + escape(str(manifest.get("protocol_hash", "unavailable"))) + "</code></p>",
                "<div class='notice'>" + "".join("<p>" + escape(text) + "</p>" for text in notices) + "</div>",
                "<h2>Methods and completion</h2>", _table(
                    ("Method", "Attempted", "Valid", "Invalid/incomplete", "Statuses"),
                    [(item["label"], item["attempted"], item["valid"], item["invalid_or_incomplete"], json.dumps(item["statuses"], sort_keys=True)) for item in counts]),
                "<p>Expected fits: " + _number(manifest.get("expected_fits")) + "; observed fits: " + str(len(rows)) + ".</p>"]
    calibration = manifest.get("calibration")
    if calibration:
        calibration_runs = calibration.get("runs") or []
        failures_in_calibration = [row for row in calibration_runs if not row.get("valid")]
        sections += ["<h2>Calibration and frozen model settings</h2>",
            "<p>Status: " + escape(str(calibration.get("status"))) + "; " +
            str(len(calibration_runs)) + " candidate/arc/mask records, including " +
            str(len(failures_in_calibration)) + " invalid or excluded records. Revisited candidates across expansion rounds are retained.</p>",
            "<p>" + escape(str(calibration.get("score_weighting", ""))) + "</p>",
            "<pre>" + escape(json.dumps(_plain(calibration.get("selections")), indent=2)) + "</pre>",
            "<details><summary>Boundary checks and calibration disclosures</summary><pre>" +
            escape(json.dumps(_plain({key: calibration.get(key) for key in
                ("selection_hash", "calibration_adequate", "boundary_diagnostics", "calibration_disclosures")}), indent=2)) +
            "</pre></details>",
            "<details><summary>Every calibration score and failed fit</summary>",
            _table(("Arc", "Holdout (min)", "Method", "Parameters", "Round", "Fit status",
                    "Prediction status", "Valid", "Mean projected code NLL", "Error"),
                [(row.get("case", {}).get("arc_id"), row.get("case", {}).get("holdout_minutes"),
                  registry.get(row.get("method"), row.get("method")), json.dumps(row.get("parameters", {}), sort_keys=True),
                  row.get("expansion_round"), row.get("status"), row.get("evaluation_status"), row.get("valid", False),
                  (row.get("score") or {}).get("mean_nll"), row.get("error") or row.get("reason"))
                 for row in calibration_runs]), "</details>"]
    if synthetic:
        sections += ["<h2>Paired gap position errors</h2>",
            "<p>Differences are method A minus B. Intervals resample independent paired seeds, with no time samples treated as separate trials.</p>",
            "<p>Blackout metrics are not applicable to normal-coverage cases. Missing planned seeds are counted even when both methods have no result.</p>",
            _table(("Cell", "Method A", "Method B", "Valid pairs", "Failed/missing pairs", "Mean difference (m)", "95% seed bootstrap (m)"),
                [(r["cell_id"], registry[r["method_a"]], registry[r["method_b"]], r["valid_seed_pairs"], r["failed_or_missing_seed_pairs"], r["mean_difference_a_minus_b"], r["bootstrap_95_interval"]) for r in paired if r["applicable"]]),
            "<h2>Position uncertainty at fixed epochs</h2>",
            "<p>95% position ellipsoid coverage, with Wilson intervals across independent seeds at each fixed epoch. Failed or unavailable seeds remain listed.</p>",
            _table(("Cell", "Method", "Hour", "Covered/valid", "Wilson 95% interval", "Failed/unavailable seeds"),
                [(r["cell_id"], registry[r["method_id"]], r["hours_since_start"], f"{r['successes']}/{r['trials']}", r["interval"], r["failed_or_unavailable_seeds"]) for r in coverage])]
    if synthetic:
        sections += ["<h2>Whole-arc and blackout accuracy and uncertainty</h2>",
            "<p>Each row is one independent seed. RTN means radial, along-track and cross-track. NLL and NEES are averages of marginal position scores across the indicated arc, not independent time-sample trials. Interval widths and ellipsoids are conditional on selected hyperparameters; model-selection uncertainty is excluded.</p>",
            _table(("Cell", "Method", "Seed", "Window", "Position RMSE (m)", "RTN RMSE (m)", "Position NLL", "Position NEES", "Mean RTN 95% widths (m)"),
                [(r["cell_id"], registry[r["method_id"]], r["seed"], window,
                  r["metrics"].get(window, {}).get("position_rmse_m"), r["metrics"].get(window, {}).get("rtn_rmse_m"),
                  r["metrics"].get(window, {}).get("position_nll"), r["metrics"].get(window, {}).get("position_nees"),
                  r["metrics"].get(window, {}).get("mean_marginal_95_width_rtn_m"))
                 for r in rows if _valid(r) for window in ("whole_arc", "gap")]),
            "<details><summary>Paired confidence intervals for all metrics</summary>",
            "<p>Units follow the named metric. A smaller NEES or a narrower interval does not by itself imply better uncertainty calibration.</p>",
            _table(("Cell", "Metric", "A", "B", "Valid pairs", "Mean A−B", "95% paired interval"),
                [(r["cell_id"], r["metric"], registry[r["method_a"]], registry[r["method_b"]], r["valid_seed_pairs"],
                  r["mean_difference_a_minus_b"], r["bootstrap_95_interval"]) for r in all_paired if r["applicable"]]), "</details>"]
    sections += ["<h2>Resources and failed fits</h2>",
        "<p>Runtime includes native outer iterations. Peak memory is the largest sampled native-process resident set; "
        "it excludes the Python wrapper and shared filesystem caches.</p>",
        _table(("Cell", "Method", "Seed/date", "Fit status", "Evaluation status", "Converged", "Elapsed (s)", "Peak RSS (bytes)", "Error"),
            [(r["cell_id"], registry[r["method_id"]], r["seed"], r["status"], r["evaluation_status"], r["converged"],
              r["elapsed_seconds"], r["peak_rss_bytes"], r["error"]) for r in rows])]
    if not synthetic:
        sections += ["<h2>Independent satellite laser ranging</h2>",
            "<p>Residuals are observed minus modeled one-way range. Formal predictive scores use only externally calibrated stations and include cross-observation covariance. Descriptive residuals remain available when formal uncertainty cannot be evaluated. Groups overlap; their scores must not be added or treated as independent trials.</p>",
            _table(("Date", "Coverage", "Method", "Usable points", "Passes", "Range RMS (m)",
                    "Formal points", "Predictive NLL", "Predictive status"),
                [(r["seed"], r["cell_id"], registry[r["method_id"]],
                  r["metrics"].get("native_slr", {}).get("normal_points"),
                  r["metrics"].get("native_slr", {}).get("passes"),
                  r["metrics"].get("native_slr", {}).get("range_rms_m"),
                  r["metrics"].get("formal_prediction", {}).get("observations"),
                  r["metrics"].get("predictive", {}).get("nll"),
                  r["metrics"].get("formal_prediction", {}).get("status", "unavailable")) for r in rows])]
        grouped = []
        for r in rows:
            slr = r["metrics"].get("native_slr", {})
            groups = {key: slr.get(key, {}) for key in ("per_date", "per_station", "per_pass")}
            groups.update(slr.get("by_geometry", {}))
            for category, items in groups.items():
                for name, value in items.items():
                    predictive = value.get("predictive", {})
                    grouped.append((r["seed"], registry[r["method_id"]], r["cell_id"], category, name,
                                    value.get("count"), value.get("rms_m"), predictive.get("dimensions"),
                                    predictive.get("nll"), predictive.get("status", "unavailable")))
        sections += ["<details><summary>SLR by pass, station, date and geometry</summary>",
            _table(("Date", "Method", "Coverage", "Grouping", "Group", "Usable points", "RMS (m)",
                    "Formal dimensions", "Correlated NLL", "Status"), grouped), "</details>",
            "<h2>Agreement with GPS-derived GNV1B orbits</h2>",
            "<p>This comparison shares underlying GPS information with the fitted measurements. It is not independent truth and supplies neither Cartesian NEES nor truth coverage.</p>",
            _table(("Date", "Coverage", "Method", "Matched epochs", "Position disagreement RMS (m)",
                    "Velocity disagreement RMS (m/s)"),
                [(r["seed"], r["cell_id"], registry[r["method_id"]],
                  r["metrics"].get("reference_agreement", {}).get("matched_epochs"),
                  r["metrics"].get("reference_agreement", {}).get("position_rms_m"),
                  r["metrics"].get("reference_agreement", {}).get("velocity_rms_m_s")) for r in rows])]
    if manifest.get("execution_platform"):
        sections += ["<details><summary>Compute environment</summary><pre>" +
            escape(json.dumps(_plain({"platform": manifest["execution_platform"],
                                      "concurrent_workers": manifest.get("concurrent_workers")}), indent=2)) +
            "</pre><p>Elapsed times depend on this concurrency and resource contention.</p></details>"]
    if manifest.get("development_evidence"):
        sections += ["<h2>Development validation</h2>",
            "<p>These checks are engineering evidence. They do not enter frozen evaluation statistics or establish model superiority.</p>"]
        for name, evidence in manifest["development_evidence"].items():
            sections += ["<details><summary>" + escape(str(name)) + "</summary><pre>" +
                         escape(json.dumps(_plain(evidence), indent=2)) + "</pre></details>"]
    sections += ["<h2>Numerical acceptance evidence</h2>", "<pre>" + escape(json.dumps(_plain(gates), indent=2)) + "</pre>",
                 "<h2>All run records</h2>",
                 "<p>Uncertainty values are usable only when the fit reports a valid fully marginalized covariance. Flight reference agreement is kept inside its own metric field.</p>",
                 "".join("<details><summary>" + escape(f"{registry[row['method_id']]} · {row['cell_id']} · seed/date {row['seed']} · {row['status']}") + "</summary><pre>" + escape(json.dumps(_plain(row), indent=2)) + "</pre></details>" for row in rows)]
    html = "<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Orbit smoothing comparison</title><style>body{font:16px/1.5 system-ui,sans-serif;max-width:1200px;margin:3rem auto;padding:0 1.5rem;color:#172333;background:#fafbfc}h1,h2{line-height:1.2}h2{margin-top:2.5rem}table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{padding:.6rem;text-align:left;border-bottom:1px solid #d8dee5}th{background:#edf2f7}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.8rem}.notice{border-left:4px solid #b58c31;padding:.2rem 1rem;background:#fff9eb}details{margin:.6rem 0;padding:.5rem;border:1px solid #d8dee5}</style><body>" + "".join(sections) + "</body></html>"
    (destination / "index.html").write_text(html, encoding="utf-8")
    (destination / "report.json").write_text(json.dumps(_plain(summary), indent=2, sort_keys=True, allow_nan=False) + "\n")
    return {"status": "complete", "html": str((destination / "index.html").resolve()),
            "summary": str((destination / "report.json").resolve()), "scientific_acceptance": False,
            "orchestration_complete": complete, "all_fits_valid": all_valid}
