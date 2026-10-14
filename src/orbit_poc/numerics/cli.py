"""Independent v3.1 numerical prepare/run/report commands."""
import argparse
import json
from pathlib import Path


def _commands(parser):
    commands = parser.add_subparsers(dest="numerics_command", required=True)
    for name in ("prepare", "run", "report"):
        command = commands.add_parser(name)
        command.add_argument("--config", type=Path, required=True)
        command.add_argument("--output-dir", type=Path)
        if name == "run": command.add_argument("--max-attempts", type=int)


def register(commands):
    _commands(commands.add_parser("numerics", help="Frozen v3.1 numerical reliability benchmark"))


def dispatch(args):
    from .config import load_config
    config = load_config(args.config)
    if args.numerics_command == "report":
        from .report import create_report
        result = create_report(config, args.output_dir)
    else:
        from . import protocol
        options = {"max_attempts": args.max_attempts} if args.numerics_command == "run" else {}
        result = getattr(protocol, args.numerics_command)(config, args.output_dir, **options)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 1 if result["status"] in ("blocked", "failed") else 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="orbit-poc numerics", description=__doc__)
    _commands(parser)
    args = parser.parse_args(argv)
    try:
        return dispatch(args)
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
