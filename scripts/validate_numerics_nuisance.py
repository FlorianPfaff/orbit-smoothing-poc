#!/usr/bin/env python3
"""Replay one fixed-orbit native nuisance problem with transaction audits."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import xml.etree.ElementTree as ET


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-profile", required=True, type=Path)
    parser.add_argument("--native", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-floor-limited", action="store_true", help="validate separately labelled progress-only status; never call it strict convergence")
    args = parser.parse_args()
    source = args.source_profile.resolve(strict=True)
    native = args.native.resolve(strict=True)
    build_path = Path(str(native) + ".build-manifest.json")
    build = json.loads(build_path.read_text())
    binary_hash = sha256(native)
    if build["executable_sha256"] != binary_hash:
        raise ValueError("Executable/build mismatch")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    spool = output / "spool"
    spool.mkdir()
    tree = ET.parse(source)
    for node in tree.iter():
        if node.text and node.text.strip() and (node.tag.startswith("outputfile") or
            (node.tag == "filename" and node.get("label") == "tmpDir")):
            if str(source.parent) not in node.text:
                raise ValueError(f"Output path outside source-profile directory: {node.text}")
            node.text = node.text.replace(str(source.parent), str(output))
            Path(node.text.split("{")[0]).parent.mkdir(parents=True, exist_ok=True)
    tree.write(output / "profile.xml", encoding="utf-8", xml_declaration=True)
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
               ORBIT_POC_NUMERICS_QR_PREFIX=str(output / "qr"),
               ORBIT_POC_NUMERICS_KEEP_INTERMEDIATE_FACTORS="0",
               ORBIT_POC_NUMERICS_COMPRESS_ROW_PROVENANCE="1",
               ORBIT_POC_NUMERICS_SPOOL_DIRECTORY=str(spool))
    start = time.monotonic()
    timed_out = False
    with (output / "profile.log").open("w") as log:
        process = subprocess.Popen([str(native), str(output / "profile.xml")], env=env,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            returncode = process.wait(timeout=7200)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            returncode = process.wait()
    searches = []
    for path in sorted(output.glob("qr.*.nuisance_line_search.json"), key=lambda p: int(p.name.split(".")[1])):
        item = json.loads(path.read_text())
        searches.append({"generation": int(path.name.split(".")[1]), "sha256": sha256(path), **item})
    profile_path = output / "qr.profile.json"
    profile = json.loads(profile_path.read_text()) if profile_path.exists() else None
    successful_trials = [trial for search in searches for trial in search["trials"] if trial["status"] == 0]
    signatures = {trial.get("observation_signature") for trial in successful_trials}
    crossings = sum(trial.get("ambiguity_half_integer_crossings", 0) for trial in successful_trials)
    fixed_observations = bool(signatures) and None not in signatures and "0" not in signatures and len(signatures) == 1
    replays = [item.get("zero_update_replay") for item in searches]
    exact_replay = bool(replays) and all(item and item["status"] == 0 and item["actual_reduction"] == 0 and item["maximum_update_m"] == 0 for item in replays)
    strictly_converged = bool(profile and profile.get("nuisance_converged") and not profile.get("nuisance_floor_limited"))
    floor_validated = bool(profile and profile.get("nuisance_floor_limited") and not profile.get("nuisance_converged")
        and profile.get("nuisance_objective_resolution", 0) > 0
        and 0 < profile.get("nuisance_predicted_reduction", 0) <= profile["nuisance_objective_resolution"]
        and profile.get("nuisance_floor_audit") and all(item.get("success") and item.get("support_unchanged") for item in profile["nuisance_floor_audit"]))
    passed = (returncode == 0 and not timed_out and (strictly_converged or (args.allow_floor_limited and floor_validated))
              and fixed_observations and crossings > 0 and exact_replay)
    compressed_rows = [json.loads(path.read_text()) for path in sorted(output.glob("qr.*.rows.tsv.compression.json"))]
    receipt = {"strict_nuisance_converged": strictly_converged,
               "progress_only_floor_validated": floor_validated,
               "allow_floor_limited_requested": args.allow_floor_limited,
               "row_compression": compressed_rows, "schema": "orbit-poc-native-nuisance-validation-v1", "passed": passed,
               "returncode": returncode, "timed_out": timed_out, "elapsed_seconds": time.monotonic() - start,
               "native_sha256": binary_hash, "native_unchanged": sha256(native) == binary_hash,
               "build_manifest_sha256": sha256(build_path), "source_profile": str(source),
               "source_profile_sha256": sha256(source), "replay_profile_sha256": sha256(output / "profile.xml"),
               "fixed_observations_and_weights_verified_every_trial": fixed_observations,
               "ambiguity_half_integer_crossings_tested": crossings, "zero_update_replay_exact": exact_replay, "profile": profile, "searches": searches,
               "scope": "One fixed physical trajectory with native GNSS observations; verifies explicitly labelled strict convergence or audited progress-only resolution status, transactional backtracking and fixed-observation float ambiguity coordinates. Does not certify the full benchmark."}
    receipt["passed"] = receipt["passed"] and receipt["native_unchanged"]
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"passed": receipt["passed"], "receipt": str(output / "receipt.json")}))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
