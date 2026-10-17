"""Command line entry points for simulation, calibration, inference, and reports."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(prog="orbit-poc", description=__doc__)
    commands = cli.add_subparsers(dest="command", required=True)
    from .comparison.cli import register
    register(commands)
    from .numerics.cli import register as register_numerics
    register_numerics(commands)
    from .segmented.cli import register as register_segmented
    register_segmented(commands)
    for name in ("generate", "calibrate", "benchmark", "scaling", "posterior"):
        command = commands.add_parser(name)
        command.add_argument("--config", type=Path, help="JSON or YAML scenario/benchmark configuration")
        command.add_argument("--output-dir", type=Path, required=True)
        command.add_argument("--truth-backend", choices=("tudat", "scipy"), default="tudat")
        command.add_argument("--tudat-python", help="Interpreter in the separate Tudat environment")
        command.add_argument("--no-resume", action="store_true")
        command.add_argument("--orbits", nargs="+", choices=("leo300", "leo500", "leo800", "eccentric"))
        if name != "generate":
            command.add_argument("--budget-hours", type=float, default=12.0)
            command.add_argument("--max-iterations", type=int, default=20)
        if name in ("calibrate", "benchmark", "posterior"):
            command.add_argument("--max-jobs", type=int)
        if name == "calibrate":
            command.add_argument("--quick", action="store_true", help="One seed and one candidate/model; explicitly incomplete")
        if name == "benchmark":
            command.add_argument("--calibration", type=Path)
            command.add_argument("--seeds", type=int, choices=(5, 10, 20), default=5)
            command.add_argument("--pilot", action="store_true", help="Two seeds/cell and a timing-based final sample recommendation")
            command.add_argument("--no-ieks", action="store_true")
            command.add_argument("--workers", type=int, default=1, choices=range(1, 9))
            command.add_argument("--job-timeout", type=float, help="Hard timeout in seconds for each isolated fitting job")
        if name == "posterior":
            command.add_argument("--num-warmup", type=int, default=500)
            command.add_argument("--num-samples", type=int, default=500)
            command.add_argument("--job-timeout", type=float, default=3600)
    fit = commands.add_parser("fit")
    fit.add_argument("--dataset", type=Path, required=True)
    fit.add_argument("--output-dir", type=Path, required=True)
    fit.add_argument("--model", choices=("white", "colored", "density"), default="density")
    fit.add_argument("--solver", choices=("gtsam", "ieks", "deterministic", "numpyro"), default="gtsam")
    fit.add_argument("--parameters", type=Path, help="JSON ModelSpec parameters")
    fit.add_argument("--options", type=Path, help="JSON solver options")
    fit.add_argument("--max-iterations", type=int, default=20)
    fit.add_argument("--truth", type=Path)
    fit.add_argument("--reference", type=Path)
    fit.add_argument("--no-resume", action="store_true")
    report = commands.add_parser("report")
    report.add_argument("--input-dir", type=Path, required=True)
    report.add_argument("--output-dir", type=Path)
    report.add_argument("--no-plots", action="store_true")
    schur = commands.add_parser("schur-check")
    schur.add_argument("--output-dir", type=Path, required=True)
    merge = commands.add_parser("merge-calibration")
    merge.add_argument("--inputs", type=Path, nargs="+", required=True)
    merge.add_argument("--output-dir", type=Path, required=True)
    merge_benchmark = commands.add_parser("merge-benchmark")
    merge_benchmark.add_argument("--inputs", type=Path, nargs="+", required=True)
    merge_benchmark.add_argument("--output-dir", type=Path, required=True)
    job = commands.add_parser("_fit-job", help=argparse.SUPPRESS)
    job.add_argument("--job", type=Path, required=True)
    job.add_argument("--output-dir", type=Path, required=True)
    return cli


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "comparison":
            from .comparison.cli import dispatch
            return dispatch(args)
        if args.command == "segmented":
            from .segmented.cli import dispatch
            return dispatch(args)
        if args.command == "numerics":
            from .numerics.cli import dispatch
            return dispatch(args)
        from . import benchmark as experiments
        if args.command in ("generate", "calibrate", "benchmark", "scaling", "posterior"):
            from .config import load_config
            config = load_config(args.config) if args.config else {
                "orbit": "leo500", "atmosphere": "disturbed", "coverage": "normal",
                "duration_hours": 24.0, "cadence": 60.0, "seed": 200000,
                "truth_profile": "controlled", "epoch": "2024-05-10T00:00:00"}
            if args.orbits:
                config["orbits"] = args.orbits
                if args.command == "generate":
                    if len(args.orbits) != 1:
                        raise ValueError("generate accepts exactly one --orbits value")
                    config["orbit"] = args.orbits[0]
            common = {"truth_backend": args.truth_backend, "tudat_python": args.tudat_python,
                      "resume": not args.no_resume}
            if args.command == "generate":
                result = experiments.generate_one(config, args.output_dir, **common)
            else:
                common.update(budget_hours=args.budget_hours,
                              solver_options={"max_iterations": args.max_iterations})
                if args.command == "calibrate":
                    result = experiments.calibrate(config, args.output_dir, **common,
                                                   max_jobs=args.max_jobs, quick=args.quick)
                elif args.command == "benchmark":
                    result = experiments.benchmark(config, args.output_dir, **common,
                        max_jobs=args.max_jobs, calibration_path=args.calibration, seeds=args.seeds,
                        pilot=args.pilot, include_ieks=not args.no_ieks, workers=args.workers,
                        job_timeout=args.job_timeout)
                elif args.command == "scaling":
                    result = experiments.run_scaling(config, args.output_dir, **common)
                else:
                    result = experiments.run_posterior_checks(config, args.output_dir, **common,
                        max_jobs=args.max_jobs, num_warmup=args.num_warmup,
                        num_samples=args.num_samples, job_timeout=args.job_timeout)
        elif args.command == "fit":
            parameters = experiments.read_json(args.parameters) if args.parameters else {"model": args.model}
            options = experiments.read_json(args.options) if args.options else {"max_iterations": args.max_iterations}
            result = experiments.fit_one(args.dataset, parameters, args.output_dir,
                solver=args.solver, options=options, resume=not args.no_resume,
                truth_path=args.truth, reference_path=args.reference)
        elif args.command == "_fit-job":
            request = experiments.read_json(args.job)
            result = experiments.fit_one(request["dataset"], request["parameters"], args.output_dir,
                solver=request["solver"], options=request["options"], truth_path=request["truth"],
                run_context=request["context"])
        elif args.command == "schur-check":
            result = experiments.schur_check()
            experiments.write_json(args.output_dir / "schur-check.json", result)
        elif args.command == "merge-calibration":
            result = experiments.merge_calibrations(args.inputs, args.output_dir)
        elif args.command == "merge-benchmark":
            result = experiments.merge_benchmarks(args.inputs, args.output_dir)
        else:
            from .report import make_report
            result = make_report(args.input_dir, args.output_dir, plots=not args.no_plots)
        summary = {key: value for key, value in result.items()
                   if key in ("status", "complete", "valid_benchmark", "valid_for_comparison", "converged",
                              "dataset", "truth", "fit", "html", "seed_recommendation", "budget", "passed")}
        print(json.dumps(experiments._plain(summary or result), indent=2, allow_nan=False))
        if result.get("status") in ("failed", "timeout") or result.get("passed") is False:
            return 1
        return 0
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
