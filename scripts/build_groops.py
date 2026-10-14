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


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-dir", type=Path, required=True)
    p.add_argument("--build-dir", type=Path, required=True)
    p.add_argument("--prefix", type=Path, help="Conda compiler/dependency environment")
    p.add_argument("--jobs", type=int, default=8)
    p.add_argument("--configure-only", action="store_true")
    p.add_argument("--upstream-only", action="store_true", help="Build the clean pinned upstream engine for external-example reproduction")
    args = p.parse_args()
    source, build = args.source_dir.resolve(), args.build_dir.resolve()
    if args.jobs < 1:
        p.error("--jobs must be positive")
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--filter=blob:none", REPOSITORY, source])
        run(["git", "-C", source, "checkout", "--detach", COMMIT])
    extension = Path(__file__).resolve().parents[1] / "groops/extension/apply_extension.py"
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if revision != COMMIT:
        raise ValueError(f"Expected GROOPS {COMMIT}, found {revision}")
    if args.upstream_only:
        changed = subprocess.check_output(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=all"], text=True)
        if changed.strip():
            raise ValueError("An upstream-only build requires a separate clean checkout of the pinned revision")
    else:
        run([sys.executable, extension, source])
    env = dict(os.environ)
    command = ["cmake", "-S", source / "source", "-B", build, "-G", "Ninja",
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
    run(command, env=env)
    if not args.configure_only:
        run(["cmake", "--build", build, "--parallel", str(args.jobs)], env=env)
        executable = build / "groops"
        run([executable, "--help"], env=env)
        manifest = {
            "schema_version": 1, "upstream_commit": COMMIT,
            "extension": None if args.upstream_only else json.loads((source / "orbit-poc-extension.json").read_text()),
            "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            "cmake_cache_sha256": hashlib.sha256((build / "CMakeCache.txt").read_bytes()).hexdigest(),
            "compiler": subprocess.check_output([env.get("CXX", "c++"), "--version"], env=env, text=True).splitlines()[0],
            "mpi": False,
        }
        (build / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
