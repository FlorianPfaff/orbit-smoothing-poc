"""Portable HTML/CSV reports, with missing and failed stages made conspicuous."""
from __future__ import annotations

import csv
import html
import json
from pathlib import Path

import numpy as np

from .benchmark import (CHI2_95_3, MODEL_NAMES, paired_statistics, read_json,
                        relocate_run_paths, solver_equivalence, write_json)


def _format(value):
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.5g}"
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


def _table(rows, columns):
    if not rows:
        return "<p>No completed records are available.</p>"
    header = "".join(f"<th>{html.escape(label)}</th>" for _, label in columns)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(_format(row.get(key)))}</td>" for key, _ in columns) + "</tr>" for row in rows)
    return f'<div class="table-scroll"><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>'


def _wilson(successes, total, z=1.959963984540054):
    p = successes / total
    denominator = 1 + z * z / total
    midpoint = (p + z * z / (2 * total)) / denominator
    width = z * np.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return midpoint - width, midpoint + width


def _plot_groups(runs, destination):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    grouped = {}
    for run in runs:
        context = run.get("context", {})
        if not run.get("valid_for_comparison") or context.get("solver") not in ("gtsam", "deterministic"):
            continue
        key = tuple(context.get(field, "unknown") for field in ("orbit", "atmosphere", "coverage"))
        grouped.setdefault(key, []).append(run)
    figures = []
    coverage_records = []
    colors = {"baseline": "#657185", "white": "#2679bb", "colored": "#e18b25", "density": "#169c80"}
    for key, rows in sorted(grouped.items()):
        fig, axes = plt.subplots(1, 3, figsize=(15, 4.2), constrained_layout=True)
        models = [model for model in ("baseline", *MODEL_NAMES) if any(r["context"]["model"] == model for r in rows)]
        error_samples = [[r["metrics"]["position_rmse_m"] for r in rows if r["context"]["model"] == model] for model in models]
        axes[0].boxplot(error_samples, showfliers=True)
        axes[0].set_xticks(np.arange(1, len(models) + 1), models)
        axes[0].set_ylabel("Position RMSE (m)")
        axes[0].set_title("Independent-seed distributions")
        axes[0].set_yscale("log")
        for model in models:
            selected = [r for r in rows if r["context"]["model"] == model]
            epochs = []
            times = None
            for row in selected:
                path = Path(row["path"]).parent / "epoch_metrics.npz"
                if not path.exists():
                    continue
                with np.load(path, allow_pickle=False) as values:
                    current = values["times"]
                    if times is not None and (current.shape != times.shape or not np.allclose(current, times)):
                        continue
                    times = current.copy()
                    epochs.append(values["position_nees"].copy())
            if epochs:
                stacked = np.asarray(epochs)
                valid = np.isfinite(stacked)
                denominator = valid.sum(axis=0)
                successes = ((stacked <= CHI2_95_3) & valid).sum(axis=0)
                keep = denominator > 0
                hours = (times[keep] - times[0]) / 3600
                coverage = successes[keep] / denominator[keep]
                low, high = _wilson(successes[keep], denominator[keep])
                axes[1].plot(hours, coverage, label=f"{model} (n={len(epochs)})", color=colors[model], alpha=0.85)
                # Intervals are saved in CSV instead of overlapping four ribbons.
                coverage_records.extend({"orbit": key[0], "atmosphere": key[1], "coverage": key[2],
                    "model": model, "elapsed_hours": float(hour), "seed_count": int(n),
                    "position_joint_95_coverage": float(p), "wilson_95_low": float(lo), "wilson_95_high": float(hi)}
                    for hour, n, p, lo, hi in zip(hours, denominator[keep], coverage, low, high))
        axes[1].axhline(0.95, color="#555", linestyle="--", linewidth=1)
        axes[1].set(xlabel="Elapsed time (h)", ylabel="Empirical joint-position coverage", ylim=(-0.02, 1.02), title="95% ellipsoids at each fixed epoch")
        axes[1].legend(fontsize=8, loc="lower right")
        runtimes = [[r.get("elapsed_seconds", 0) or 0 for r in rows if r["context"]["model"] == model] for model in models]
        axes[2].bar(models, [np.median(values) for values in runtimes], color=[colors[model] for model in models])
        axes[2].set(ylabel="Median complete fit time (s)", title="Measured runtime, including initialization")
        fig.suptitle(" / ".join(key), fontsize=14)
        name = "-".join(key) + ".png"
        fig.savefig(destination / name, dpi=300)
        fig.savefig(destination / name.replace(".png", ".pdf"))
        plt.close(fig)
        figures.append({"path": name, "pdf": name.replace(".png", ".pdf"), "caption": " / ".join(key)})
    if coverage_records:
        _write_csv(destination / "fixed_epoch_coverage.csv", coverage_records)
    return figures


def _write_csv(path, rows):
    if not rows:
        Path(path).write_text("")
        return
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with Path(path).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value) if isinstance(value, (dict, list)) else value for key, value in row.items()})


def make_report(input_dir, output_dir=None, *, plots=True) -> dict:
    source = Path(input_dir).resolve()
    destination = Path(output_dir).resolve() if output_dir else source / "report"
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = source / "benchmark.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else {
        "status": "incomplete", "valid_benchmark": False, "runs": [],
        "expected_primary_runs": None, "note": "Benchmark manifest is absent."}
    runs = relocate_run_paths(manifest.get("runs", []), source)
    if not runs:
        for path in source.rglob("fit.json"):
            record = read_json(path)
            if record.get("context", {}).get("stage") in ("calibration", "posterior", "scaling"):
                continue
            runs.append({"path": str(path), "context": record.get("context", {}),
                         "status": record.get("status"), "converged": record.get("converged", False),
                         "valid_for_comparison": record.get("valid_for_comparison", False),
                         "metrics": record.get("metrics", {}), "elapsed_seconds": record.get("elapsed_seconds"),
                         "error": record.get("error")})
    rows = [{**run.get("context", {}), "status": run.get("status"), "converged": run.get("converged"),
             "valid_for_comparison": run.get("valid_for_comparison"), **run.get("metrics", {}),
             "elapsed_seconds": run.get("elapsed_seconds"), "error": run.get("error")} for run in runs]
    comparisons = paired_statistics(runs)
    equivalence_result = solver_equivalence(runs, manifest.get("expected_ieks_pairs", 96))
    equivalence = equivalence_result["pairs"]
    _write_csv(destination / "runs.csv", rows)
    _write_csv(destination / "paired_comparisons.csv", comparisons)
    _write_csv(destination / "solver_equivalence.csv", equivalence)
    figures = []
    plot_error = None
    if plots:
        try:
            figures = _plot_groups(runs, destination)
        except Exception as error:
            plot_error = f"{type(error).__name__}: {error}"
    valid_count = sum(bool(run.get("valid_for_comparison")) for run in runs)
    valid_benchmark = bool(manifest.get("valid_benchmark") and equivalence_result["passed"])
    status = "Completed calibrated trajectory matrix" if valid_benchmark else "Exploratory or incomplete benchmark"
    limitations = []
    if not manifest.get("primary_complete"):
        limitations.append("The requested primary matrix is incomplete; missing jobs are not successful results.")
    if not manifest.get("calibrated"):
        limitations.append("No completed held-out calibration was supplied. Model hyperparameters are exploratory defaults.")
    if manifest.get("pilot"):
        limitations.append("This is a two-seed timing pilot. It does not establish ensemble uncertainty calibration.")
    if manifest.get("truth_backend") != "tudat":
        limitations.append("Independent Tudat truth is not confirmed for this run; diagnostic truth must not support scientific claims.")
    if valid_count < len(runs):
        limitations.append("Failed, unconverged, or invalid-covariance fits are excluded from paired statistics and plots, and remain listed below.")
    if not equivalence_result["passed"]:
        limitations.append(f"Solver equivalence has {equivalence_result['passing_pairs']} passing pairs of {equivalence_result['expected_pairs']} required. Each needs identical reference, <0.01 posterior-sigma state difference, and <1e-4 relative objective difference.")
    if plot_error:
        limitations.append("Plot generation failed: " + plot_error)
    stage_rows = []
    for filename in ("calibration.json", "scaling.json", "posterior.json", "schur-check.json"):
        path = source / filename
        if not path.exists():
            path = source / filename.removesuffix(".json") / filename
        if path.exists():
            item = read_json(path)
            stage_rows.append({"stage": filename.removesuffix(".json"), "complete": item.get("complete", item.get("passed", False)),
                               "details": item.get("note", item.get("status", "See stage manifest"))})
        else:
            stage_rows.append({"stage": filename.removesuffix(".json"), "complete": False, "details": "Not present in this report directory"})
    summary = {"status": status, "valid_benchmark": valid_benchmark, "observed_fit_count": len(runs),
               "valid_fit_count": valid_count, "expected_primary_runs": manifest.get("expected_primary_runs"),
               "limitations": limitations, "stage_status": stage_rows, "paired_comparisons": comparisons,
               "solver_equivalence": equivalence, "figures": figures,
               "solver_equivalence_acceptance": equivalence_result,
               "html": str(destination / "report.html")}
    write_json(destination / "summary.json", summary)
    issues = "".join(f"<li>{html.escape(item)}</li>" for item in limitations)
    panels = "".join(f'<figure><img src="{html.escape(item["path"])}" alt="{html.escape(item["caption"])}"><figcaption>{html.escape(item["caption"])} · <a href="{html.escape(item["pdf"])}">Vector PDF</a></figcaption></figure>' for item in figures)
    text = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Orbit smoothing proof of concept</title><style>
body{{font:15px/1.5 system-ui,sans-serif;color:#182536;background:#f7f9fc;margin:0;padding:32px;max-width:1500px;margin:auto}}h1{{font-size:30px;margin-bottom:8px}}h2{{margin-top:32px}}.status{{padding:18px;border-left:5px solid {'#15956c' if valid_benchmark else '#cc7b16'};background:white}}table{{border-collapse:collapse;width:100%;font-size:12px;background:white}}td,th{{text-align:left;padding:8px;border-bottom:1px solid #dce2ea;white-space:nowrap}}th{{background:#edf2f7}}.table-scroll{{overflow:auto;max-height:650px}}img{{max-width:100%;height:auto}}figure{{margin:24px 0;background:white;padding:12px}}code{{background:#e6edf4;padding:2px 4px}}.muted{{color:#5d6b7c}}</style></head><body>
<h1>Orbit smoothing proof of concept</h1><p class="muted">Independent simulation, held-out model selection, sparse trajectory inference, and honest uncertainty checks.</p>
<div class="status"><strong>{html.escape(status)}</strong><p>{valid_count} valid fits among {len(runs)} recorded fits; requested primary runs: {html.escape(_format(manifest.get('expected_primary_runs')))}.</p><ul>{issues}</ul></div>
<p>All states use SI units. Empirical coverage is evaluated across independent seeds at each fixed epoch. Consecutive trajectory samples are correlated and are not additional Monte Carlo trials. With five or ten seeds, coverage estimates remain coarse; the CSV contains Wilson intervals.</p>
<h2>Stage status</h2>{_table(stage_rows, [('stage','Stage'),('complete','Complete / passed'),('details','Details')])}
<h2>Model comparisons</h2>{panels or '<p>No valid plots are available yet.</p>'}
<p>Derived atmosphere corrections are interpretable as density only for controlled truth with fixed spacecraft properties. Under force-model mismatch they are effective drag corrections. Weak drag at high altitude may leave these corrections unidentifiable.</p>
<h2>Paired seed differences</h2><p>A negative difference favors model A for RMSE. Bootstrap intervals require at least five paired seeds and are descriptive; no correction for multiple comparisons is claimed.</p>
{_table(comparisons, [('orbit','Orbit'),('atmosphere','Atmosphere'),('coverage','Tracking'),('model_a','Model A'),('model_b','Model B'),('paired_seed_count','Pairs'),('mean_difference_a_minus_b','RMSE A − B (m)'),('bootstrap_95_interval','95% bootstrap interval')])}
<h2>GTSAM / IEKS consistency</h2><p>{equivalence_result['passing_pairs']} of {equivalence_result['expected_pairs']} required pairs pass.</p>{_table(equivalence, [('orbit','Orbit'),('atmosphere','Atmosphere'),('coverage','Tracking'),('model','Model'),('seed','Seed'),('both_valid','Both valid'),('same_reference','Same frozen-Q reference'),('maximum_posterior_sigma_difference','Max difference / posterior sigma'),('relative_objective_difference','Relative objective difference'),('passed','Pass')])}
<h2>Every recorded fit</h2>{_table(rows, [('orbit','Orbit'),('atmosphere','Atmosphere'),('coverage','Tracking'),('seed','Seed'),('model','Model'),('solver','Solver'),('status','Status'),('converged','Converged'),('valid_for_comparison','Valid'),('position_rmse_m','Position RMSE (m)'),('velocity_rmse_m_s','Velocity RMSE (m/s)'),('gap_position_rmse_m','Gap RMSE (m)'),('elapsed_seconds','Seconds'),('error','Error')])}
<p>Machine-readable outputs: <a href="summary.json">summary.json</a>, <a href="runs.csv">runs.csv</a>, <a href="paired_comparisons.csv">paired_comparisons.csv</a>, <a href="solver_equivalence.csv">solver_equivalence.csv</a>{', <a href="fixed_epoch_coverage.csv">fixed_epoch_coverage.csv</a>' if (destination / 'fixed_epoch_coverage.csv').exists() else ''}.</p>
<h2>Provenance</h2><pre>{html.escape(json.dumps(manifest.get('provenance', {}), indent=2))}</pre>
</body></html>'''
    (destination / "report.html").write_text(text)
    return summary
