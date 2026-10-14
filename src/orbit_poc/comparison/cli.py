"""CLI registration for the independently versioned comparison protocol."""
import json
from pathlib import Path


def register(commands):
    comparison = commands.add_parser("comparison", help="Prepare and execute the frozen v3 comparison")
    stages = comparison.add_subparsers(dest="comparison_command", required=True)
    for name in ("prepare", "calibrate", "run", "report"):
        command = stages.add_parser(name)
        command.add_argument("--config", type=Path, required=True)
        command.add_argument("--output-dir", type=Path)
        command.add_argument("--stage", choices=("synthetic", "flight"), default="synthetic")
        if name == "prepare":
            command.add_argument("--split", choices=("calibration", "evaluation"), default="calibration")
        if name in ("run", "report"):
            command.add_argument("--campaign", choices=("primary", "stress", "flight_ar_reference"), default="primary")
        if name != "report":
            command.add_argument("--max-jobs", type=int)
            command.add_argument("--workers", type=int, default=1, help="Maximum concurrent native fits; preparation stays sequential")
            command.add_argument("--budget-hours", type=float, default=12.)
            command.add_argument("--no-resume", action="store_true")


def dispatch(args):
    from .config import load_config
    from . import protocol
    config = load_config(args.config)
    options = {"stage": args.stage}
    if args.comparison_command != "report":
        options.update(max_jobs=args.max_jobs, budget_hours=args.budget_hours, resume=not args.no_resume, workers=args.workers)
    if args.comparison_command == "prepare":
        options["split"] = args.split
    if args.comparison_command in {"run", "report"}:
        options["campaign"] = args.campaign
    result = getattr(protocol, args.comparison_command)(config, args.output_dir, **options)
    summary = {key: value for key, value in result.items() if key in {
        "status", "complete", "inputs_prepared", "all_fits_valid", "expected_fits", "expected_jobs",
        "jobs_started", "protocol_hash", "selection_hash", "calibration_adequate",
        "calibration_disclosures", "error", "html"}}
    print(json.dumps(summary, indent=2, allow_nan=False))
    return 1 if result.get("status") in {"blocked", "failed", "inconclusive_calibration"} else 0
