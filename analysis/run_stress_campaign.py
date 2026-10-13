"""Reproduce one realism stress case using frozen calibration.

Run from the installed project root. The exact original campaign wrapper is
archived in validation/stress_runner_original.py. This single deliberately
mismatched case is not an ensemble benchmark.
"""
import argparse
from pathlib import Path
from orbit_poc.benchmark import generate_one, fit_one, read_json, write_json, provenance


def main(args):
    config = read_json(args.config)
    calibration = read_json(args.calibration)
    if config["truth_profile"] != "stress":
        raise ValueError("Use an explicit stress configuration")
    if not (calibration["complete"] and calibration["comparison_grid_adequate"]):
        raise ValueError("Complete calibration with an adequate grid is required")
    if calibration["provenance"]["source_sha256"] != provenance()["source_sha256"]:
        raise ValueError("Calibration and current scientific source differ")
    root = args.output_dir.resolve()
    generated = generate_one(config, root / "data", tudat_python=args.tudat_python)
    manifest = {
        "kind": "realism_stress", "status": "running", "valid_benchmark": False,
        "calibrated": True, "truth_backend": "tudat", "expected_primary_runs": 4,
        "runs": [], "provenance": provenance(),
        "note": "One deliberately mismatched-force case with frozen controlled-calibration parameters; no ensemble performance claim.",
    }
    for model in ("baseline", "white", "colored", "density"):
        solver = "deterministic" if model == "baseline" else "gtsam"
        parameters = ({"model": "white", "substep": config["substep"]} if model == "baseline"
                      else calibration["selections"][config["orbit"]][model]["parameters"])
        context = {key: config[key] for key in ("orbit", "atmosphere", "coverage", "seed", "truth_profile", "duration_hours")}
        context.update(model=model, solver=solver, stage="stress")
        output = root / "fits" / model
        try:
            fitted = fit_one(generated["dataset"], parameters, output, solver=solver,
                             options={"max_iterations": args.max_iterations},
                             truth_path=generated["truth"], run_context=context)
        except Exception as error:
            fitted = (read_json(output / "fit.json") if (output / "fit.json").exists()
                      else {"status": "failed", "error": f"{type(error).__name__}: {error}"})
        manifest["runs"].append({"path": str(output / "fit.json"), "context": context,
            **{key: fitted.get(key) for key in ("status", "converged", "valid_for_comparison", "metrics", "elapsed_seconds", "error")}})
        write_json(root / "benchmark.json", manifest)
    manifest["primary_complete"] = all(row["status"] == "complete" for row in manifest["runs"])
    manifest["status"] = "complete" if manifest["primary_complete"] else "incomplete"
    write_json(root / "benchmark.json", manifest)
    print({"status": manifest["status"], "converged_fits": sum(bool(row.get("converged")) for row in manifest["runs"]),
           "valid_benchmark": False})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stress.json"))
    parser.add_argument("--calibration", type=Path, default=Path("runs/v2/calibration/calibration.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("runs/stress-reproduction"))
    parser.add_argument("--tudat-python", required=True)
    parser.add_argument("--max-iterations", type=int, default=60)
    main(parser.parse_args())
