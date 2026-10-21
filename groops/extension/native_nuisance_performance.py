#!/usr/bin/env python3
"""Install opt-in nuisance-stage instrumentation in a separate native tree.

Run after the corrected numerics, segmented and optional wide-tangent installers.
Set ORBIT_POC_NUISANCE_PERFORMANCE=1 for diagnostic sidecars. The default is 0.
ORBIT_POC_NUISANCE_INTERPOLATION_CACHE=1 enables a one-entry exact-query cache
inside each row build; default 0. Every native design call and downstream check
remains in place. No cache entry survives a build/update boundary logically.
ORBIT_POC_NUISANCE_COST_ONLY_DESIGN=1 omits the unused physical observation
derivative interpolation only during cost-only child builds; default 0.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

MARKER = "ORBIT_POC_NUISANCE_PERFORMANCE_V1"
MANIFEST = "orbit-poc-nuisance-performance-extension.json"
PROCESSING = "source/gnss/gnssProcessingStep/gnssProcessingStep.cpp"
SEARCH = "source/misc/orbitPoc/nuisanceLineSearch.h"
HEADER = "source/misc/orbitPoc/nuisancePerformance.h"
DYNAMIC = "source/gnss/gnssParametrization/gnssParametrizationLeoDynamicOrbits.cpp"


def _replace(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f"Nuisance performance anchor mismatch: {old[:100]}")
    return text.replace(old, new, 1)


def _processing(text: str) -> str:
    for required in ("ORBIT_POC_SCALED_ROW_QR_V31", "ORBIT_POC_TRANSACTIONAL_NUISANCE_V31"):
        if required not in text:
            raise ValueError(f"Nuisance performance requires installed {required}")
    text = _replace(text, """    if(!noiseModel.arOrder)
    {
      gnss->designMatrix(normalEquationInfo, eqn, A);
      return;
    }""", """    if(!noiseModel.arOrder)
    {
      orbitPocNuisancePerformance::ObservationDesignMeasure performance(orbitPocRowQr().enabled());
      gnss->designMatrix(normalEquationInfo, eqn, A);
      return;
    }""")
    anchor = "void GnssProcessingStep::State::buildNormals(Bool constraintsOnly, Bool solveEpochParameters)\n{\n  try\n  {"
    text = _replace(text, anchor, anchor + "\n    orbitPocNuisancePerformance::BuildMeasure performance(orbitPocRowQr().enabled(),orbitPocRowQr().isCostOnly());")
    anchor = "      buildNormals(FALSE,FALSE);\n      const std::string mode="
    text = _replace(text, anchor, "      buildNormals(FALSE,FALSE);\n      const auto rowBuildPerformance=orbitPocNuisancePerformance::metrics();\n      const std::string mode=")
    anchor = "        trial.receiverPositionChange=receiverPositionChange;trial.receiverTimeChange=receiverTimeChange;trial.changedReceiverTimes=changedReceiverTimes;"
    text = _replace(text, anchor, "        trial.performance=orbitPocNuisancePerformance::metrics();\n" + anchor)
    anchor = '      orbitPocQr::writeNuisanceSearch(stem+".nuisance_line_search.json",search,before,prediction);'
    text = _replace(text, anchor, anchor + '\n      orbitPocNuisancePerformance::writeSearch(stem+".nuisance_performance.json",search,rowBuildPerformance);')
    return '// ' + MARKER + '\n#include "misc/orbitPoc/nuisancePerformance.h"\n' + text


def _search(text: str) -> str:
    text = _replace(text, "  Double userSeconds=0,systemSeconds=0;", "  Double userSeconds=0,systemSeconds=0,wallSeconds=0;\n  orbitPocNuisancePerformance::Metrics performance;")
    anchor = "  requireSerialTrialRuntime();int pipeDescriptors[2];"
    text = _replace(text, anchor, "  const auto performanceStart=orbitPocNuisancePerformance::Clock::now();\n" + anchor)
    anchor = "    NuisanceTrial result;result.alpha=alpha;"
    text = _replace(text, anchor, "    orbitPocNuisancePerformance::metrics()=orbitPocNuisancePerformance::Metrics{};\n" + anchor)
    # Catch blocks retain failed/partial row-build instrumentation. They do not
    # change the exception, status or acceptance behavior of the existing path.
    anchor = "    const char *data=reinterpret_cast<const char*>(&result);std::size_t remaining=sizeof(result);"
    text = _replace(text, anchor, "    if(result.status)result.performance=orbitPocNuisancePerformance::metrics();\n" + anchor)
    anchor = "  return result;\n}\nstruct NuisanceProbeRound"
    text = _replace(text, anchor, "  result.wallSeconds=orbitPocNuisancePerformance::elapsed(performanceStart);\n" + anchor)
    return '// ' + MARKER + '\n#include "misc/orbitPoc/nuisancePerformance.h"\n' + text


def _dynamic(text: str) -> str:
    original = "para->polynomial.at(arcNo).interpolateOffset({eqn.timeRecv}, para->PosDesign.at(arcNo), {eqn.receiver->timeRemainder(eqn.idEpoch)}, 3)"
    replacement = """orbitPocNuisancePerformance::dynamicDesign(para->PosDesign.at(arcNo).columns(),
                [&](){para->polynomial.at(arcNo).interpolateOffset({eqn.timeRecv}, para->PosDesign.at(arcNo).column(0,0), {eqn.receiver->timeRemainder(eqn.idEpoch)}, 3);},
                [&](){return orbitPocNuisancePerformance::interpolate(
                para,&para->polynomial.at(arcNo),&para->PosDesign.at(arcNo),eqn.receiver->idRecv(),eqn.idEpoch,arcNo,
                eqn.timeRecv.mjdInt(),eqn.timeRecv.mjdMod(),eqn.receiver->timeRemainder(eqn.idEpoch),
                [&](){return """ + original + ";});})"
    return '// ' + MARKER + '\n#include "misc/orbitPoc/nuisancePerformance.h"\n' + _replace(text, original, replacement)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def apply(root: str | Path) -> dict:
    root = Path(root)
    here = Path(__file__).resolve().parent
    inputs = {name: _digest((here / name).read_bytes()) for name in
              ("native_nuisance_performance.py", "nuisancePerformance.h")}
    manifest_path = root / MANIFEST
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("installer_inputs") != inputs:
            raise ValueError("Installed nuisance performance implementation differs")
        if set(manifest.get("installed_files", {})) != {PROCESSING, SEARCH, HEADER, DYNAMIC}:
            raise ValueError("Installed nuisance performance file inventory differs")
        for name, expected in manifest["installed_files"].items():
            if _digest((root / name).read_bytes()) != expected:
                raise ValueError(f"Installed nuisance performance file changed: {name}")
        return manifest
    original = {name: (root / name).read_bytes() for name in (PROCESSING, SEARCH, DYNAMIC)}
    if any(MARKER in data.decode() for data in original.values()):
        raise ValueError("Unattributed partial nuisance performance installation")
    # The base extension copies every header before this optional installer.
    # An exact copy is expected; an unattributed different header is not.
    if (root / HEADER).exists() and (root / HEADER).read_bytes() != (here / "nuisancePerformance.h").read_bytes():
        raise ValueError("Unattributed partial nuisance performance header")
    # Prevalidate every anchor before writing any generated native source.
    updated = {PROCESSING: _processing(original[PROCESSING].decode()).encode(),
               SEARCH: _search(original[SEARCH].decode()).encode(),
               DYNAMIC: _dynamic(original[DYNAMIC].decode()).encode(),
               HEADER: (here / "nuisancePerformance.h").read_bytes()}
    manifest = {"schema": "orbit-poc-nuisance-performance-extension-v1",
                "runtime_default": "0", "runtime_environment": "ORBIT_POC_NUISANCE_PERFORMANCE",
                "runtime_values": ["0", "1"],
                "cache_environment": "ORBIT_POC_NUISANCE_INTERPOLATION_CACHE",
                "cache_default": "0", "cache_values": ["0", "1"],
                "cache_scope": "one_exact_native_matrix_within_one_buildNormals_generation",
                "cost_only_design_environment": "ORBIT_POC_NUISANCE_COST_ONLY_DESIGN",
                "cost_only_design_default": "0",
                "cost_only_design_scope": "unused_dynamic_observation_derivatives_only_no_residual_or_prior_changes",
                "scientific_models_and_thresholds": "unchanged",
                "installer_inputs": inputs,
                "previous_files": {name: _digest(data) for name, data in original.items()},
                "installed_files": {name: _digest(data) for name, data in updated.items()}}
    for name, data in updated.items():
        (root / name).write_bytes(data)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    print(json.dumps(apply(parser.parse_args().source), indent=2, sort_keys=True))
