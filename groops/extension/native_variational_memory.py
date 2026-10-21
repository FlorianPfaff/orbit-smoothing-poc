#!/usr/bin/env python3
"""Opt-in bounded fixed-parameter variational evaluation, default unchanged.

Install after numerics, segmented and optional wide-tangent extensions, before
building a separate candidate. Set ORBIT_POC_VARIATIONAL_BLOCK_EPOCHS to an
integer 1..65536 to bound the native design rows allocated by closure evaluation;
unset/0 preserves the original full-design implementation. This changes storage,
not integration cuts, forces, statistical coordinates or convergence limits.

This component does not bound GNSS profiling memory or certify numerical
equivalence. Different BLAS block shapes must pass the existing accuracy gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

MARKER = "ORBIT_POC_BLOCKED_VARIATIONAL_EVALUATION_V1"
PROGRAM = "source/programs/gnss/orbitPocEvaluateVariational.cpp"
HEADER = "source/misc/orbitPoc/blockedVariationalEvaluation.h"
MANIFEST = "orbit-poc-variational-memory-extension.json"


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _ordinary(path, *, absent=False):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Symlink in variational-memory source path")
    if not path.is_file() and not (absent and not path.exists()):
        raise ValueError("Nonregular variational-memory source file")


def _replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError("Variational-memory anchor mismatch: " + old[:90])
    return text.replace(old, new, 1)


def transform(text):
    for required in ("ORBIT_POC_SEGMENTED_QUERY_GATE_V4", "if(segmentedOnly)return;",
                     "outputfileInitialStateDesign"):
        if required not in text:
            raise ValueError("Variational-memory requires the numerics/segmented evaluator")
    start = "    auto equation=model.integrateArc(arc.times.front(),arc.times.back(),TRUE,TRUE);"
    end = "    std::vector<Time> outputTimes=equation.times;"
    if text.count(start) != 1 or text.count(end) != 1:
        raise ValueError("Variational-memory evaluator bounds mismatch")
    i, j = text.index(start), text.index(end)
    original = text[i:j]
    original = _replace(original, "    auto equation=model.integrateArc", "    equation=model.integrateArc")
    original = _replace(original, "    Vector x(count);", "    x=Vector(count);")
    original = _replace(original, "    Matrix position=equation.pos0, velocity=equation.vel0;\n    matMult",
                        "    position=equation.pos0; velocity=equation.vel0;\n    matMult")
    branch = '''    const UInt blockEpochs=OrbitPoc::variationalBlockEpochs();
    VariationalEquationFromFile::ObservationEquation equation;
    Matrix position,velocity;Vector x;
    if(blockEpochs)
    {
      if(!segmentedReferenceDesign.empty()||!segmentedQueries.empty()||!segmentedQueryReference.empty())
        throw(Exception("Blocked variational evaluation forbids bounded dense-reference gate outputs"));
      const auto evaluated=OrbitPoc::evaluateVariationalBlocks(model,arc.times,blockEpochs,parametersFile,initialFile,initialDesign);
      equation.times=arc.times;position=evaluated.position;velocity=evaluated.velocity;x=evaluated.parameters;
      logInfo<<"Blocked native variational evaluation: epochs="<<arc.times.size()<<", parameters="<<model.parameterCount()
             <<", blocks="<<evaluated.blocks<<", maximum_block_epochs="<<evaluated.maximumBlockEpochs
             <<"; unchanged chronological native integration"<<Log::endl;
    }
    else
    {
'''
    text = text[:i] + branch + original + "    }\n\n" + text[j:]
    # Parse before any exporter or early-return path, so invalid values cannot
    # be silently ignored by a segmented-export-only invocation.
    text = _replace(text, "    const UInt blockEpochs=OrbitPoc::variationalBlockEpochs();\n", "")
    anchor = "    if(isCreateSchema(config)) return;"
    text = _replace(text, anchor, anchor + "\n    const UInt blockEpochs=OrbitPoc::variationalBlockEpochs();")
    return '// ' + MARKER + '\n#include "misc/orbitPoc/blockedVariationalEvaluation.h"\n' + text


def apply(source):
    root = Path(source).absolute()
    here = Path(__file__).resolve().parent
    for path in (root / PROGRAM, here / "blockedVariationalEvaluation.h"):
        _ordinary(path)
    _ordinary(root / HEADER, absent=True)
    _ordinary(root / MANIFEST, absent=True)
    inputs = {name: _sha((here / name).read_bytes()) for name in
              ("native_variational_memory.py", "blockedVariationalEvaluation.h")}
    if (root / MANIFEST).exists():
        previous = json.loads((root / MANIFEST).read_text())
        if (previous.get("schema") != "orbit-poc-variational-memory-install-v1" or
                previous.get("installer_inputs") != inputs or
                set(previous.get("installed_files", {})) != {PROGRAM, HEADER}):
            raise ValueError("Variational-memory installation identity mismatch")
        for name, digest in previous["installed_files"].items():
            if _sha((root / name).read_bytes()) != digest:
                raise ValueError("Installed variational-memory source changed")
        return previous
    original = (root / PROGRAM).read_bytes()
    header = (here / "blockedVariationalEvaluation.h").read_bytes()
    if MARKER.encode() in original:
        raise ValueError("Unattributed partial variational-memory installation")
    if (root / HEADER).exists() and (root / HEADER).read_bytes() != header:
        raise ValueError("Unattributed variational-memory header")
    updated = {PROGRAM: transform(original.decode()).encode(), HEADER: header}
    manifest = {"schema": "orbit-poc-variational-memory-install-v1", "candidate_only": True,
                "environment": "ORBIT_POC_VARIATIONAL_BLOCK_EPOCHS", "default": "0",
                "maximum_block_epochs": 65536,
                "scope": "fixed_parameter_evaluator_only_not_GNSS_profile",
                "models_thresholds_and_native_operator": "unchanged",
                "arithmetic_note": "BLAS block shapes differ; numerical equivalence requires validation",
                "installer_inputs": inputs,
                "previous_files": {PROGRAM: _sha(original)},
                "installed_files": {name: _sha(data) for name, data in updated.items()}}
    # All source/identity/anchor checks are complete before the first write.
    for name, data in updated.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(data)
    (root / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    print(json.dumps(apply(parser.parse_args().source), indent=2, sort_keys=True))
