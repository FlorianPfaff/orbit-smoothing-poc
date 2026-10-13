"""Reproducible, read-only postprocessing of the completed controlled matrix.

Writes measurement residuals and selected trajectory plots. Never fits a model,
changes an input, or treats adjacent epochs as independent Monte Carlo samples.
Run from the project root: python analysis/derive_artifacts.py runs/v2/combined
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

MODELS = ("baseline", "white", "colored", "density")
COLORS = dict(zip(MODELS, ("#808080", "#0072B2", "#D55E00", "#009E73")))


def write_csv(path, rows):
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def dataset_for(fit_path):
    # Both host matrices use worker-NN/{fits,data}/<case>/...
    return fit_path.parents[3] / "data" / fit_path.parents[1].name / "dataset.npz"


def load_arrays(path):
    with np.load(path, allow_pickle=False) as data:
        return {key: data[key] for key in data.files}


def main(source):
    source = source.resolve()
    destination = source / "analysis"
    destination.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((source / "benchmark.json").read_text())
    runs = manifest["runs"]
    primary = [row for row in runs if row["context"]["solver"] in ("gtsam", "deterministic")]
    assert len(primary) == manifest["expected_primary_runs"]
    assert all(row["valid_for_comparison"] for row in primary)
    arrays, residual_rows, examples, grouped = {}, [], {}, {}
    input_cache = {}
    for index, row in enumerate(runs):
        context = row["context"]
        fit_path = Path(row["path"])
        fit = load_arrays(fit_path.with_name("fit.npz"))
        dataset_path = dataset_for(fit_path)
        if dataset_path not in input_cache:
            input_cache[dataset_path] = load_arrays(dataset_path)
        data = input_cache[dataset_path]
        nodes = data["obs_node"].astype(int)
        relative_r = fit["states"][nodes, :3] - data["obs_station_pos"]
        relative_v = fit["states"][nodes, 3:6] - data["obs_station_vel"]
        ranges = np.linalg.norm(relative_r, axis=1)
        rates = np.einsum("ni,ni->n", relative_r, relative_v) / ranges
        prediction = np.column_stack((ranges, rates))
        residual = data["obs_y"] - prediction
        standardized = residual / data["obs_sigma"]
        assert np.isfinite(residual).all() and np.isfinite(standardized).all()
        prefix = f"run{index:04d}"
        arrays.update({prefix + "_node": nodes, prefix + "_times": data["times"][nodes],
                       prefix + "_observed": data["obs_y"], prefix + "_predicted": prediction,
                       prefix + "_residual": residual, prefix + "_normalized": standardized})
        residual_rows.append({"array_prefix": prefix, **context,
            "fit_path": str(fit_path.relative_to(source.parent)),
            "observations": len(nodes),
            "range_rms_m": float(np.sqrt(np.mean(residual[:, 0] ** 2))),
            "range_rate_rms_m_s": float(np.sqrt(np.mean(residual[:, 1] ** 2))),
            "normalized_range_rms": float(np.sqrt(np.mean(standardized[:, 0] ** 2))),
            "normalized_range_rate_rms": float(np.sqrt(np.mean(standardized[:, 1] ** 2)))})
        if context["solver"] not in ("gtsam", "deterministic"):
            continue
        key = tuple(context[name] for name in ("orbit", "atmosphere", "coverage", "model"))
        grouped.setdefault(key, []).append(row)
        if context["seed"] == 42 and context["atmosphere"] == "disturbed" and context["coverage"] == "blackout":
            examples.setdefault(context["orbit"], {})[context["model"]] = (
                fit, load_arrays(dataset_path.with_name("truth.npz")))

    arrays["index_json"] = np.array(json.dumps(residual_rows))
    np.savez_compressed(destination / "measurement_residuals.npz", **arrays)
    write_csv(destination / "measurement_residuals.csv", residual_rows)
    summary = []
    for key, group in sorted(grouped.items()):
        entry = dict(zip(("orbit", "atmosphere", "coverage", "model"), key))
        entry["seed_count"] = len(group)
        for metric in ("position_rmse_m", "velocity_rmse_m_s", "gap_position_rmse_m", "log_density_rmse"):
            values = [r["metrics"][metric] for r in group if r["metrics"].get(metric) is not None]
            entry["mean_" + metric] = float(np.mean(values)) if values else None
            entry["median_" + metric] = float(np.median(values)) if values else None
        entry["median_fit_seconds"] = float(np.median([r["elapsed_seconds"] for r in group]))
        summary.append(entry)
    write_csv(destination / "group_summary.csv", summary)

    figures = []
    for orbit, by_model in sorted(examples.items()):
        assert set(by_model) == set(MODELS)
        fig, axes = plt.subplots(2, 1, figsize=(10, 6.8), sharex=True, layout="constrained")
        for model in MODELS:
            fitted, truth = by_model[model]
            hours = (fitted["times"] - fitted["times"][0]) / 3600
            error = np.linalg.norm(fitted["states"][:, :3] - truth["states"][:, :3], axis=1)
            axes[0].plot(hours, np.maximum(error, 1e-6), label=model, color=COLORS[model])
        fitted, truth = by_model["density"]
        b = fitted["states"][:, 6]
        sigma = np.sqrt(fitted["covariance"][:, 6, 6])
        axes[1].plot(hours, np.exp(truth["log_density_correction"]), label="Truth multiplier", color="#242424")
        axes[1].plot(hours, np.exp(b), label="Estimated multiplier", color=COLORS["density"])
        axes[1].fill_between(hours, np.exp(b - 1.959964 * sigma), np.exp(b + 1.959964 * sigma),
                             color=COLORS["density"], alpha=.18, label="Local Gaussian 95% interval")
        for ax in axes:
            ax.axvspan(11, 13, color="#777777", alpha=.12, label="Tracking blackout")
            ax.grid(alpha=.18)
            ax.legend(fontsize=8, loc="upper right")
        axes[0].set(yscale="log", ylabel="Position error norm (m)")
        axes[1].set(xlabel="Elapsed time (h)", ylabel="Density / nominal density", xlim=(0, 24))
        fig.suptitle(f"{orbit}: disturbed atmosphere and 2 h blackout · example seed 42")
        name = f"trajectory-{orbit}"
        fig.savefig(destination / f"{name}.png", dpi=300)
        fig.savefig(destination / f"{name}.pdf")
        plt.close(fig)
        figures.append(name)
    result = {"source_sha256": manifest["provenance"]["source_sha256"],
              "postprocessor_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "fit_count": len(runs), "primary_fit_count": len(primary),
              "residual_observation_count": sum(row["observations"] for row in residual_rows),
              "residual_convention": "observed minus geometric prediction; columns range m, range-rate m/s",
              "normalization": "divide by declared measurement standard deviation; post-fit residuals are correlated",
              "example_selection": "seed 42, disturbed atmosphere, blackout, all four orbits; illustrative only",
              "figures": figures}
    (destination / "derived_manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path)
    main(parser.parse_args().input_dir)
