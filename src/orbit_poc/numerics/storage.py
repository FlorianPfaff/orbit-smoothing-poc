"""Verified terminal-attempt archival with recoverable path publication.

The fitting path stays stable through an atomic symlink publication. All three
profiles use the same working filesystem; archival follows measured fit time.
No source/input path is rewritten and no unverified copy replaces an original.
"""
import os
from pathlib import Path
import shutil
import time

from orbit_poc.comparison.protocol import canonical_hash, file_hash, read_json, write_json


def inventory(directory):
    root = Path(directory)
    rows = []
    for parent, directories, files in os.walk(root, followlinks=False):
        for name in sorted(directories + files):
            path = Path(parent) / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                target = os.readlink(path)
                if not Path(target).is_absolute() and not path.resolve().is_relative_to(root.resolve()):
                    raise ValueError("Cannot archive an external relative symlink without changing its meaning")
                rows.append({"relative_path": relative, "symlink": target})
            elif path.is_dir():
                rows.append({"relative_path": relative, "directory": True})
            elif path.is_file():
                rows.append({"relative_path": relative, "bytes": path.stat().st_size,
                             "sha256": file_hash(path)})
            else:
                raise ValueError("Unsupported special file in attempt directory")
    return sorted(rows, key=lambda row: row["relative_path"])


def archive_attempt(directory, archive_root, receipt_path, *, reserve_bytes):
    """Copy/hash/publish a terminal attempt, or finish an interrupted publication."""
    directory = Path(directory).absolute()
    archive_root = Path(archive_root).resolve()
    receipt_path = Path(receipt_path).absolute()
    destination = archive_root / directory.name
    staging = archive_root / ("." + directory.name + ".copying")
    backup = directory.with_name("." + directory.name + ".archiving")
    link = directory.with_name("." + directory.name + ".archive-link")
    if directory == archive_root or archive_root.is_relative_to(directory) or directory.is_relative_to(archive_root):
        raise ValueError("Working attempt and archive directory must be separate")
    archive_root.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    if receipt_path.exists():
        receipt = read_json(receipt_path)
        if receipt.get("source") != str(directory) or receipt.get("destination") != str(destination):
            raise ValueError("Archive receipt refers to a different attempt")
        if receipt.get("inventory_sha256") != canonical_hash(receipt.get("inventory")):
            raise ValueError("Archive receipt inventory identity changed")
    else:
        if directory.is_symlink() or backup.exists() or not (directory / "result-record.json").is_file():
            raise ValueError("Archival requires an original terminal checkpoint or recovery receipt")
        rows = inventory(directory)
        receipt = {"policy": "verified_terminal_archive_v1", "source": str(directory),
            "destination": str(destination), "inventory": rows, "inventory_sha256": canonical_hash(rows),
            "bytes": sum(row.get("bytes", 0) for row in rows), "status": "planned",
            "permission_scope": "Byte/path/link identity is verified; filesystem-specific permission metadata is not an orbit data identity",
            "timing_scope": "After measured fit and generated-intermediate cleanup; identical policy for all profiles"}
        write_json(receipt_path, receipt)
    expected = receipt["inventory"]
    def verify(path):
        if inventory(path) != expected:
            raise ValueError("Attempt archive bytes, paths or symlinks differ from the receipt")
    if directory.is_symlink():
        if directory.resolve() != destination.resolve():
            raise ValueError("Attempt link points to an unexpected archive")
        verify(destination)
    else:
        source = backup if backup.exists() else directory
        if not source.is_dir():
            raise ValueError("Neither original attempt nor recoverable working directory exists")
        verify(source)
        if destination.exists():
            verify(destination)
        else:
            if shutil.disk_usage(archive_root).free < receipt["bytes"] + reserve_bytes:
                raise OSError("Archive filesystem would violate its storage reserve")
            if staging.is_symlink():
                raise ValueError("Archive staging path cannot be a symlink")
            staging.mkdir(exist_ok=True)
            # Resume an interrupted private staging copy without recreating
            # already matching symlinks or following an unexpected alias.
            for row in expected:
                origin, target = source / row["relative_path"], staging / row["relative_path"]
                if "symlink" in row:
                    if target.exists() or target.is_symlink():
                        if not target.is_symlink() or os.readlink(target) != row["symlink"]:
                            raise ValueError("Conflicting archive staging symlink")
                    else:
                        target.symlink_to(row["symlink"])
                elif row.get("directory"):
                    if target.is_symlink() or (target.exists() and not target.is_dir()):
                        raise ValueError("Conflicting archive staging directory")
                    target.mkdir(exist_ok=True)
                else:
                    if target.is_symlink() or (target.exists() and not target.is_file()):
                        raise ValueError("Conflicting archive staging file")
                    shutil.copy2(origin, target)
            verify(staging)
            staging.replace(destination)
        receipt["status"] = "copy_verified"; write_json(receipt_path, receipt)
        if link.exists() or link.is_symlink():
            if not link.is_symlink() or link.resolve() != destination.resolve():
                raise ValueError("Conflicting archive publication link")
        else:
            link.symlink_to(destination, target_is_directory=True)
        if source == directory:
            if backup.exists(): raise ValueError("Conflicting archive recovery directory")
            directory.replace(backup)
        os.replace(link, directory)
        verify(directory)
    if backup.exists():
        if backup.is_symlink():
            raise ValueError("Archive recovery directory cannot be a symlink")
        if receipt.get("working_copy_release_started"):
            # A previous interruption may have removed part of this already
            # verified copy. The complete destination was verified above;
            # every remaining source entry must still match its exact proof.
            expected_by_path = {row["relative_path"]: row for row in expected}
            if any(expected_by_path.get(row["relative_path"]) != row for row in inventory(backup)):
                raise ValueError("Partially released working copy differs from its archive proof")
            receipt["working_copy_release_recovered"] = True
        else:
            verify(backup)
        receipt.update(status="published_verified", working_copy_release_started=True)
        write_json(receipt_path, receipt)
        shutil.rmtree(backup)
    receipt.update(status="complete", last_operation_elapsed_seconds=time.monotonic()-start,
                   original_working_copy_removed=True)
    write_json(receipt_path, receipt)
    return receipt
