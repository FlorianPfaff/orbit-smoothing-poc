#!/usr/bin/env python3
"""Build the pinned external GROOPS engine and the separately licensed v3 extension."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys

COMMIT = "7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee"
REPOSITORY = "https://github.com/groops-devs/groops.git"


def run(args, **kwargs):
    subprocess.run([str(a) for a in args], check=True, **kwargs)


def source_receipt(source):
    """Hash the actual patched compilation inputs, not just the patch scripts."""
    files = {str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted((source / "source").rglob("*")) if path.is_file()}
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"sha256": digest, "files": files}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-dir", type=Path, required=True)
    p.add_argument("--build-dir", type=Path, required=True)
    p.add_argument("--prefix", type=Path, help="Conda compiler/dependency environment")
    p.add_argument("--jobs", type=int, default=8)
    p.add_argument("--configure-only", action="store_true")
    p.add_argument("--upstream-only", action="store_true", help="Build the clean pinned upstream engine for external-example reproduction")
    p.add_argument("--numerics", action="store_true", help="Enable the separately versioned v3.1 QR/objective/derivative extension")
    p.add_argument("--segmented", action="store_true", help="Enable v4 local-operator exports on top of --numerics; does not split force propagation")
    p.add_argument("--wide-tangent-candidate", action="store_true", help="Opt into the separately versioned wide-tangent candidate; requires --segmented")
    p.add_argument("--nuisance-performance", action="store_true", help="Install separate opt-in nuisance instrumentation and exact interpolation cache; requires --numerics")
    p.add_argument("--variational-memory-candidate", action="store_true", help="Install default-off bounded closure evaluator; requires --segmented and --nuisance-performance")
    p.add_argument("--cmake-executable", type=Path, help="Use an independent CMake installation with the compiler prefix")
    args = p.parse_args()
    source, build = args.source_dir.resolve(), args.build_dir.resolve()
    if args.jobs < 1:
        p.error("--jobs must be positive")
    if args.numerics and args.upstream_only:
        p.error("--numerics and --upstream-only are mutually exclusive")
    if args.segmented and not args.numerics:
        p.error("--segmented requires --numerics")
    if args.wide_tangent_candidate and not args.segmented:
        p.error("--wide-tangent-candidate requires --segmented")
    if args.nuisance_performance and not args.numerics:
        p.error("--nuisance-performance requires --numerics")
    if args.variational_memory_candidate and not (args.segmented and args.nuisance_performance):
        p.error("--variational-memory-candidate requires --segmented and --nuisance-performance")
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--filter=blob:none", REPOSITORY, source])
        run(["git", "-C", source, "checkout", "--detach", COMMIT])
    extension = Path(__file__).resolve().parents[1] / "groops/extension/apply_extension.py"
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if revision != COMMIT:
        raise ValueError(f"Expected GROOPS {COMMIT}, found {revision}")
    installed_nuisance = (source / "orbit-poc-nuisance-performance-extension.json").is_file()
    installed_memory = (source / "orbit-poc-variational-memory-extension.json").is_file()
    if installed_memory and not installed_nuisance:
        raise ValueError("Installed variational-memory profile lacks nuisance provenance; use a fresh source tree")
    if installed_nuisance:
        # The base installer copies original headers. Reapplying it would
        # overwrite the attributed optional extension before verification.
        if not args.nuisance_performance:
            raise ValueError("This source has the nuisance extension; retain --nuisance-performance or use a fresh source tree")
        for selected, name in ((args.segmented, "segmented"),
                               (args.wide_tangent_candidate, "wide-tangent"),
                               (args.variational_memory_candidate, "variational-memory")):
            if selected != (source / f"orbit-poc-{name}-extension.json").is_file():
                raise ValueError("Installed numerical profile differs; use a fresh source tree")
        run([sys.executable, extension.with_name("native_nuisance_performance.py"), "--source", source])
        if args.variational_memory_candidate:
            run([sys.executable, extension.with_name("native_variational_memory.py"), "--source", source])
    elif args.upstream_only:
        changed = subprocess.check_output(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=all"], text=True)
        if changed.strip():
            raise ValueError("An upstream-only build requires a separate clean checkout of the pinned revision")
    else:
        run([sys.executable, extension, source, *(["--numerics"] if args.numerics else [])])
        if args.segmented:
            run([sys.executable, extension.with_name("native_segmented.py"), source])
        if args.wide_tangent_candidate:
            run([sys.executable, extension.with_name("native_tangent_wide.py"), source])
        if args.nuisance_performance:
            run([sys.executable, extension.with_name("native_nuisance_performance.py"), "--source", source])
        if args.variational_memory_candidate:
            run([sys.executable, extension.with_name("native_variational_memory.py"), "--source", source])
    env = dict(os.environ)
    cmake = str(args.cmake_executable.resolve()) if args.cmake_executable else "cmake"
    command = [cmake, "-S", source / "source", "-B", build, "-G", "Ninja",
               "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_DISABLE_FIND_PACKAGE_MPI=ON"]
    if args.prefix:
        prefix = args.prefix.resolve()
        env["PATH"] = str(prefix / "bin") + os.pathsep + env.get("PATH", "")
        for variable, executable in (("CC", "x86_64-conda-linux-gnu-cc"),
                                     ("CXX", "x86_64-conda-linux-gnu-c++"),
                                     ("FC", "x86_64-conda-linux-gnu-gfortran")):
            compiler = prefix / "bin" / executable
            if not compiler.exists():
                raise FileNotFoundError(compiler)
            env[variable] = str(compiler)
        command += [f"-DCMAKE_PREFIX_PATH={prefix}", f"-DCMAKE_BUILD_RPATH={prefix / 'lib'}"]
        # The pinned dependency environment provides these exact libraries.
        # Avoid vendor probing through unrelated system/Windows installations.
        for package, name in (("BLAS", "libblas.so"), ("LAPACK", "liblapack.so")):
            library = prefix / "lib" / name
            if library.is_file():
                command.append(f"-D{package}_LIBRARIES={library}")
    run(command, env=env)
    if not args.configure_only:
        inputs = source_receipt(source)
        run([cmake, "--build", build, "--parallel", str(args.jobs)], env=env)
        if source_receipt(source) != inputs:
            raise RuntimeError("Patched compilation inputs changed during the build; rebuild before freezing")
        executable = build / "groops"
        run([executable, "--help"], env=env)
        manifest = {
            "schema_version": 1, "upstream_commit": COMMIT,
            "extension": None if args.upstream_only else json.loads((source / "orbit-poc-extension.json").read_text()),
            "segmented_extension": json.loads((source / "orbit-poc-segmented-extension.json").read_text()) if args.segmented else None,
            "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            "cmake_cache_sha256": hashlib.sha256((build / "CMakeCache.txt").read_bytes()).hexdigest(),
            "compiler": subprocess.check_output([env.get("CXX", "c++"), "--version"], env=env, text=True).splitlines()[0],
            "mpi": False,
            "patched_source": inputs,
            "build_command": [str(value) for value in command],
            "build_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "cmake_version": subprocess.check_output([cmake, "--version"], env=env, text=True).splitlines()[0],
        }
        if args.wide_tangent_candidate:
            manifest["wide_tangent_extension"] = json.loads(
                (source / "orbit-poc-wide-tangent-extension.json").read_text())
        if args.nuisance_performance:
            manifest["nuisance_performance_extension"] = json.loads(
                (source / "orbit-poc-nuisance-performance-extension.json").read_text())
        if args.variational_memory_candidate:
            manifest["variational_memory_extension"] = json.loads(
                (source / "orbit-poc-variational-memory-extension.json").read_text())
        (build / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
