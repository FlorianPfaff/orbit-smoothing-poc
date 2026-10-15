#!/usr/bin/env python3
"""Verify the narrowly scoped 7fa70502 -> 3aad854b native applicability proof.

This verifies source/build identity and an inactive nonfinite guard. It neither
executes an estimator nor marks an unfinished numerical gate as passed.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re


OLD_BINARY = "7fa70502fb091199af52715786f965650c78f2254f71824f777b6091363a081c"
NEW_BINARY = "3aad854b51102dce1fa7a8622177b33075d928d060cb10d740f1b137a00c33e9"
CHANGED = {"nuisanceLineSearch.h", "orbitPocQrSolve.cpp"}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def text_digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def previous_source(name, current):
    """Reconstruct previous bytes, then verify against its immutable manifest."""
    if name == "orbitPocQrSolve.cpp":
        block = '''        if(nuisanceFixture=="floor_derived_nonfinite"&&std::fabs(alpha)>1)
        {trial.reduction=-.75*std::numeric_limits<Double>::max();trial.cost=-trial.reduction;}
'''
        assert current.count(block) == 1
        return current.replace(block, "")
    block = '''  if(!std::isfinite(result.probeCurvature)||!std::isfinite(result.probeHalfCurvature)||
     !std::isfinite(result.probeSlope)||!std::isfinite(result.probeHalfSlope))
  {reject("nonfinite_symmetric_probe_diagnostics");return;}
'''
    assert current.count(block) == 1
    previous = current.replace(block, "")
    begin = previous.index("inline void writeNuisanceFloorAudit")
    end = previous.index("inline void writeNuisanceSearch")
    serializer = previous[begin:end]
    serializer = re.sub(r"nuisanceJsonNumber\(((?:result\.probe|r\.)\w+)\)", r"\1", serializer)
    serializer = serializer.replace('<<",\\\"maximum_update_m\\\":"<<nuisanceJsonNumber(t.change)', "")
    return previous[:begin] + serializer + previous[end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", required=True, type=Path)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    binaries = [args.previous.resolve(strict=True), args.current.resolve(strict=True)]
    expected = [OLD_BINARY, NEW_BINARY]
    manifests = []
    for executable, required_hash in zip(binaries, expected):
        manifest_path = Path(str(executable) + ".build-manifest.json")
        manifest = json.loads(manifest_path.read_text())
        assert digest(executable) == manifest["executable_sha256"] == required_hash
        manifests.append(manifest)
    old, new = manifests
    build_fields = ["upstream_commit", "cmake_cache_sha256", "compiler", "mpi",
                    "build_command", "build_script_sha256", "cmake_version"]
    for name in build_fields:
        assert old[name] == new[name], name
    assert old["extension"]["registration_files"] == new["extension"]["registration_files"]
    assert old["extension"]["extension_profile"] == new["extension"]["extension_profile"] == "numerics_v31"
    old_files, new_files = old["extension"]["files"], new["extension"]["files"]
    assert old_files.keys() == new_files.keys()
    assert {name for name in old_files if old_files[name] != new_files[name]} == CHANGED
    old_native, new_native = old["patched_source"]["files"], new["patched_source"]["files"]
    assert old_native.keys() == new_native.keys()
    changed_native = {name for name in old_native if old_native[name] != new_native[name]}
    assert {Path(name).name for name in changed_native} == CHANGED and len(changed_native) == 2
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    changed = []
    for name in sorted(CHANGED):
        current = (root / "groops/extension" / name).read_text()
        previous = previous_source(name, current)
        assert text_digest(current) == new_files[name]
        assert text_digest(previous) == old_files[name], f"Previous bytes were not reconstructed exactly: {name}"
        compiled_name = next(item for item in changed_native if Path(item).name == name)
        assert old_native[compiled_name] == old_files[name]
        assert new_native[compiled_name] == new_files[name]
        patch = output / (name + ".diff")
        patch.write_text("".join(difflib.unified_diff(previous.splitlines(True), current.splitlines(True),
                                                    fromfile="7fa/" + name, tofile="3aad/" + name)))
        changed.append({"name": name, "compiled_path": compiled_name,
                        "previous_sha256": old_files[name], "current_sha256": new_files[name],
                        "previous_bytes_reconstructed_and_hash_verified": True,
                        "diff": {"path": str(patch), "sha256": digest(patch)}})
    receipt = {
        "schema": "orbit-poc-native-component-applicability-v1",
        "source_comparison_verified": True,
        "previous_binary_sha256": OLD_BINARY, "current_binary_sha256": NEW_BINARY,
        "binaries": [{"path": str(path), "sha256": digest(path),
                      "build_manifest_sha256": digest(Path(str(path) + ".build-manifest.json"))}
                     for path in binaries],
        "identical_build_fields": {name: new[name] for name in build_fields},
        "unchanged_extension_components": {name: new_files[name] for name in sorted(new_files) if name not in CHANGED},
        "unchanged_compiled_source_file_count": len(new_native) - len(changed_native),
        "previous_patched_source_sha256": old["patched_source"]["sha256"],
        "current_patched_source_sha256": new["patched_source"]["sha256"],
        "changed_components": changed,
        "normal_case_equivalence_conditions": [
            "Every evaluated symmetric-probe slope and curvature is finite.",
            "The actual gate retains its original input, initialization, weights, priors, masks, gauges and execution receipts.",
            "The original gate finishes and passes its own unchanged acceptance criteria; this proof does not supply that result."
        ],
        "exact_change_inventory": [
            "Guard derived symmetric-probe slope/curvature against nonfinite values before existing acceptance checks; the new branch is inactive for finite values.",
            "Serialize derived probe/history values with finite-number JSON guards, and add per-probe maximum_update_m to the diagnostics.",
            "Add only the floor_derived_nonfinite test mode in the standalone OrbitPocQrSolve fixture program."
        ],
        "unchanged_normal_case_operations": [
            "Physical propagation, forces, derivatives, GNSS forward model and original weighted rows.",
            "Nuisance correction, nonlinear trial objective, profiling thresholds, backtracking and empirical resolution/probe acceptance arithmetic.",
            "Probe amplitude, dimensional and scalar caps, adaptive refinement rules, full parameter penalties and nuisance covariance marginalization."
        ],
        "scope": "Source-level component applicability for finite normal-case nonlinear objective evidence executed with 7fa70502. No new estimator execution, output equivalence experiment, timing transfer or blanket whole-binary identity claim.",
        "gate_result": "not_evaluated_by_this_proof",
        "verifier_sha256": digest(Path(__file__)),
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"source_comparison_verified": True, "gate_result": receipt["gate_result"],
                      "receipt": str(output / "receipt.json")}))


if __name__ == "__main__":
    main()
