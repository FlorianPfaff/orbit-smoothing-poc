#!/usr/bin/env python3
"""Install the small GPL GROOPS extension into a verified, disposable checkout."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess

COMMIT = "7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee"


def copy_changed(source, destination):
    if not destination.exists() or source.read_bytes() != destination.read_bytes():
        shutil.copyfile(source, destination)


def apply(source, *, numerics=False):
    source = Path(source).resolve()
    actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if actual != COMMIT:
        raise ValueError(f"Expected GROOPS {COMMIT}, found {actual}")
    here = Path(__file__).resolve().parent
    entries = [
        ("MiscAccelerations", "classes/miscAccelerations", "miscAccelerations", "logDensity", "MiscAccelerationsLogDensity", "acc"),
        ("MiscAccelerations", "classes/miscAccelerations", "miscAccelerations", "syntheticDrag", "MiscAccelerationsSyntheticDrag", "acc"),
        ("MiscAccelerations", "classes/miscAccelerations", "miscAccelerations", "syntheticGravity", "MiscAccelerationsSyntheticGravity", "acc"),
        ("ParametrizationAcceleration", "classes/parametrizationAcceleration", "parametrizationAcceleration", "logDensity", "ParametrizationAccelerationLogDensity", "parameter"),
        ("GnssParametrization", "gnss/gnssParametrization", "gnssParametrization", "logDensityOu", "GnssParametrizationLogDensityOu", "base"),
    ]
    target = source / "source/misc/orbitPoc"
    target.mkdir(parents=True, exist_ok=True)
    copy_changed(here / "logDensitySeries.h", target / "logDensitySeries.h")
    copy_changed(here / "linearTrace.h", target / "linearTrace.h")
    modified = []
    for group, directory, stem, choice, cls, collection in entries:
        header = cls[0].lower() + cls[1:] + ".h"
        target = source / "source" / directory
        copy_changed(here / header, target / header)
        cpp = target / (stem + ".cpp")
        text = cpp.read_text()
        include = f'#include "{directory}/{header}"'
        if include not in text:
            marker = f'#include "{directory}/{stem}.h"'
            if marker not in text:
                raise ValueError(f"Cannot locate include registration in {cpp}")
            text = text.replace(marker, include + "\n" + marker, 1)
            marker = f'GROOPS_REGISTER_CLASS({group}, "{stem}Type",'
            text = text.replace(marker, marker + f"\n                      {cls},", 1)
            marker = "      endChoice(config);"
            registration = (f'      if(readConfigChoiceElement(config, "{choice}", type, "v3 log-density comparison"))\n'
                            f"        {collection}.push_back(new {cls}(config));\n")
            if marker not in text:
                raise ValueError(f"Cannot locate choice registration in {cpp}")
            text = text.replace(marker, registration + marker, 1)
            cpp.write_text(text)
        modified.append(str(cpp.relative_to(source)))
    for name in ("native_covariance.py", "native_integration.py", "native_interpolation.py", "native_thermal.py", "native_atmosphere.py", "native_epoch_grid.py", "native_simulation.py", "native_linear_trace.py", "native_nuisance_export.py", "native_preprocessing.py"):
        patcher = here / name
        if patcher.exists():
            subprocess.run([__import__('sys').executable, str(patcher), str(source)], check=True)
    program_names = ("orbitPocPredictCode.cpp", "orbitPocForceDesign.cpp", "orbitPocPredictSlr.cpp", "orbitPocEvaluateVariational.cpp", "orbitPocResampleOrbit.cpp")
    for name in program_names:
        copy_changed(here / name, source / "source/programs/gnss" / name)
    sources = source / "source/sourcesCXX.txt"
    original = sources.read_text()
    entries = ["programs/gnss/" + name for name in program_names]
    contents = "\n".join(line for line in original.splitlines() if line.strip() not in entries)
    marker = "programs/gnss/gnssSimulateReceiver.cpp"
    if marker not in contents:
        raise ValueError("Pinned GROOPS program list changed")
    revised = contents.replace(marker, marker + "\n" + "\n".join(entries), 1) + "\n"
    if revised != original:
        sources.write_text(revised)
    if numerics:
        for name in ("native_row_qr.py", "native_objective.py", "native_derivatives.py"):
            subprocess.run([__import__('sys').executable, str(here / name), str(source)], check=True)
    manifest = {"upstream_commit": COMMIT, "extension_profile": "numerics_v31" if numerics else "legacy_v3", "files": {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(here.iterdir()) if p.is_file()},
        "registration_files": modified}
    (source / "orbit-poc-extension.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--numerics", action="store_true")
    args = parser.parse_args()
    print(json.dumps(apply(args.source, numerics=args.numerics), indent=2))
