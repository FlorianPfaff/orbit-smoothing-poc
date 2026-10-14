#!/usr/bin/env python3
"""Run the checksum-pinned official example in a fresh private directory.

This reproduces the published recipe, including its native ambiguity resolution.
Agreement with the supplied output is a software check, not an accuracy result.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import zipfile

import numpy as np

from orbit_poc.comparison.backend import _orbit, run_native
from orbit_poc.comparison.data import reuse_auxiliary_manifest
from orbit_poc.comparison.protocol import artifact_record, file_hash, write_json


EXAMPLE_SHA256 = "5a9d10bbab419489e5a62306ab5f1c840963ca66fb0b1b9e70fb648e9629f63b"
PROGRAMS = ("01groopsConvert", "02groopsConvertGracefo", "03groopsVariational", "04groopsGnssProcessing")


def reproduce(args):
    archive = Path(args.archive).resolve()
    if file_hash(archive) != EXAMPLE_SHA256:
        raise ValueError("Official example archive SHA256 does not match the frozen protocol")
    binary = Path(args.groops).resolve()
    auxiliary = Path(args.auxiliary_dir).resolve()
    auxiliary_manifest = reuse_auxiliary_manifest(auxiliary)
    output = Path(args.output).resolve()
    if output.exists():
        raise FileExistsError("Choose a new output directory; previous example evidence is preserved")
    output.mkdir(parents=True)
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            path = (output / entry.filename).resolve()
            if not path.is_relative_to(output):
                raise ValueError("Unsafe archive member")
        bundle.extractall(output)
    scenario = output / "scenarioLeoReducedDynamicOrbit"
    supplied = output / "supplied-output"
    shutil.move(scenario / "output", supplied)
    record = {"schema_version": 3, "status": "running", "passed": False,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "example_sha256": EXAMPLE_SHA256, "native_binary_sha256": file_hash(binary),
        "auxiliary_sources": [{"url": row["url"], "sha256": row["sha256"], "bytes": row["bytes"]}
                              for row in auxiliary_manifest["sources"]],
        "scope": "Official example recipe reproduction; supplied output agreement is not independent truth accuracy",
        "execution": [], "agreement": [],
        "thresholds_m": {"rms": args.rms_tolerance_m, "maximum": args.max_tolerance_m}}
    record_path = output / "example-reproduction.json"
    write_json(record_path, record)
    try:
        for name in PROGRAMS:
            config = scenario / f"{name}.xml"
            tree = ET.parse(config)
            fields = tree.findall("./global/filename[@label='groopsDataDir']")
            if len(fields) != 1:
                raise ValueError(f"Unexpected official auxiliary-path structure: {name}")
            fields[0].text = str(auxiliary)
            tree.write(config, encoding="utf-8", xml_declaration=True)
            execution = run_native(binary, config, scenario, name, timeout=args.timeout_seconds)
            record["execution"].append(execution)
            write_json(record_path, record)
        for date in ("2020-01-01", "2020-01-02"):
            relative = Path(date) / f"gracefo1_orbit_{date}.txt"
            fitted = scenario / "output" / relative
            reference = supplied / relative
            fitted_time, fitted_state = _orbit(fitted)
            reference_time, reference_state = _orbit(reference)
            if len(fitted_time) != len(reference_time) or not np.array_equal(fitted_time, reference_time):
                raise ValueError(f"Example orbit epochs disagree on {date}")
            distance = np.linalg.norm(fitted_state[:, :3] - reference_state[:, :3], axis=1)
            rms = float(np.sqrt(np.mean(distance**2)))
            maximum = float(distance.max())
            record["agreement"].append({"date": date, "epochs": len(distance),
                "supplied_example_position_difference_rms_m": rms,
                "supplied_example_position_difference_max_m": maximum,
                "passed": rms < args.rms_tolerance_m and maximum < args.max_tolerance_m,
                "artifacts": [artifact_record("fitted_example_orbit", fitted),
                              artifact_record("supplied_example_orbit", reference)]})
        record.update(status="complete", passed=all(row["passed"] for row in record["agreement"]))
    except Exception as error:
        record.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json(record_path, record)
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--groops", required=True)
    parser.add_argument("--auxiliary-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=3600.)
    parser.add_argument("--rms-tolerance-m", type=float, default=.001)
    parser.add_argument("--max-tolerance-m", type=float, default=.003)
    arguments = parser.parse_args()
    for key in ("timeout_seconds", "rms_tolerance_m", "max_tolerance_m"):
        if not np.isfinite(getattr(arguments, key)) or getattr(arguments, key) <= 0:
            parser.error(f"{key} must be finite and positive")
    result = reproduce(arguments)
    print(json.dumps({key: result[key] for key in ("status", "passed", "native_binary_sha256", "agreement")}, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
