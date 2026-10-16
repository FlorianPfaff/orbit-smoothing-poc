#!/usr/bin/env python3
"""Install the explicitly selected wide-tangent candidate after v4 patches.

The seven source payloads reproduce the reviewed native candidate. Installation
does not certify native convergence, covariance, or the v4 release gates.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import tempfile

PAYLOAD = Path(__file__).resolve().with_name("wide_tangent")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def ordinary(path, allow_absent=False):
    require(path.is_absolute() and ".." not in path.parts, "Noncanonical source path")
    for parent in (path, *path.parents):
        require(not parent.is_symlink(), "Symlink in source path")
    require((allow_absent and not path.exists()) or path.is_file(), "Nonregular source file")


def apply(target, *, payload_root=PAYLOAD):
    """Validate the entire overlay before writing; accept an exact repeat."""
    root, payload_root = Path(target), Path(payload_root)
    require(root.is_absolute() and root.is_dir() and ".." not in root.parts,
            "Invalid installed source root")
    manifest_path = payload_root / "manifest.json"
    ordinary(manifest_path)
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    require(set(manifest) == {"schema", "candidate_only", "files"}
            and manifest["schema"] == "orbit-poc-wide-tangent-overlay-v1"
            and manifest["candidate_only"] is True, "Unknown candidate overlay")
    files = manifest["files"]
    require(isinstance(files, list) and len(files) == 7, "Unexpected overlay membership")
    pending, names = [], set()
    for item in files:
        require(set(item) == {"path", "original_sha256", "proposed_sha256", "proposed_bytes"},
                "Unknown overlay member fields")
        name = item["path"]
        require(isinstance(name, str) and name, "Invalid overlay member")
        rel = Path(name)
        require(not rel.is_absolute() and ".." not in rel.parts and str(rel) == name
                and name not in names, "Unsafe or duplicate overlay member")
        names.add(name)
        current, proposed = root / rel, payload_root / "proposed" / rel
        ordinary(proposed)
        data = proposed.read_bytes()
        require(sha(data) == item["proposed_sha256"] and len(data) == item["proposed_bytes"],
                "Proposed source changed")
        ordinary(current, True)
        if current.exists() and current.read_bytes() == data:
            continue
        if item["original_sha256"] is None:
            require(not current.exists(), "Unrecognized pre-existing new file")
        else:
            require(current.exists() and sha(current.read_bytes()) == item["original_sha256"],
                    "Installed baseline identity mismatch")
        pending.append((current, data))
    for path, data in pending:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=path.name + ".candidate-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    output = {item["path"]: sha((root / item["path"]).read_bytes()) for item in files}
    require(output == {item["path"]: item["proposed_sha256"] for item in files},
            "Installed candidate source changed")
    return {"schema": "orbit-poc-wide-tangent-install-v1", "candidate_only": True,
            "changed_files": len(pending), "source_hashes": output,
            "manifest_sha256": sha(manifest_bytes), "compiled": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="GROOPS checkout after native_segmented.py")
    args = parser.parse_args()
    result = apply(args.source / "source")
    (args.source / "orbit-poc-wide-tangent-extension.json").write_text(
        json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
