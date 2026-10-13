#!/usr/bin/env python3
"""Acquire public GRACE-FO inputs and build/run native masked GNSS conversion."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from orbit_poc.comparison.data import fetch_example_auxiliary, prepare_flight_day
from orbit_poc.comparison.groops_config import (build_day_configs, fetch_flight_auxiliary,
                                               run_native_preparation)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="2024-04-24")
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--auxiliary-dir", type=Path, required=True)
    parser.add_argument("--scenario-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--method", choices=("groops_pulses", "groops_log_drag_ou"), default="groops_pulses")
    parser.add_argument("--blackout", action="store_true", help="remove [11:00,13:00) UTC before initialization")
    parser.add_argument("--cadence-seconds", type=int, default=30)
    parser.add_argument("--pulse-interval-seconds", type=float, default=1200)
    parser.add_argument("--pulse-sigma-velocity-m-s", type=float, default=1e-4)
    parser.add_argument("--density-tau-seconds", type=float, default=7200)
    parser.add_argument("--density-sigma-log", type=float, default=.3)
    parser.add_argument("--allow-frozen-evaluation", action="store_true")
    parser.add_argument("--offline", action="store_true", help="require cached, recorded inputs")
    parser.add_argument("--groops", type=Path, help="execute native input conversions after configuration")
    args = parser.parse_args()
    fetch_example_auxiliary(args.scenario_dir, args.auxiliary_dir, download=not args.offline)
    fetch_flight_auxiliary(args.auxiliary_dir, download=not args.offline)
    observations = prepare_flight_day(args.date, args.cache_dir, args.output_dir / "raw",
                                     allow_frozen_evaluation=args.allow_frozen_evaluation,
                                     download=not args.offline)
    mask = {"intervals_seconds": [[39600, 46800]] if args.blackout else [],
            "cadence_seconds": args.cadence_seconds, "time_scale": "UTC"}
    manifest = build_day_configs(observations, args.scenario_dir, args.auxiliary_dir,
                                 args.output_dir / args.method, method=args.method, mask=mask,
                                 pulse_interval_seconds=args.pulse_interval_seconds,
                                 pulse_sigma_velocity_m_s=args.pulse_sigma_velocity_m_s,
                                 density_tau_seconds=args.density_tau_seconds,
                                 density_sigma_log=args.density_sigma_log)
    if args.groops:
        manifest = run_native_preparation(manifest, args.groops)
    print(json.dumps({"status": manifest["status"], "output_dir": manifest["output_dir"],
                      "configs": manifest["configs"], "bootstrap": manifest["preprocessing"]["bootstrap"],
                      "reference_inputs_used": False}, indent=2))


if __name__ == "__main__":
    main()
