"""Audited compression and release of generated numerical intermediates.

Every text diagnostic, physical parameter file, final result artifact and the
latest failed-attempt factor is retained. Original prepared inputs and symlinks
are never deletion candidates. The policy is identical for both new profiles;
the archived runtime is untouched and its outputs are retained.
"""
import re
import time
from pathlib import Path

from orbit_poc.comparison.protocol import artifact_record, file_hash, read_json, write_json

POLICY = "generated_intermediates_v1"
FACTOR = re.compile(r"point-(\d+)-[^/]+/qr\.(\d+)\.R\.bin\Z")
CLOSURE = re.compile(r"point-\d+-[^/]+/closure-\d+/(variational|orbit)\.dat\Z")
PROPOSAL = re.compile(r"point-\d+-[^/]+/proposal-\d+/orbit\.dat\Z")


def compact_attempt(directory, result, profile):
    root = Path(directory).resolve()
    start = time.monotonic()
    retained = {Path(item["path"]).resolve() for item in result.get("artifacts", [])}
    # Preserve the accepted factor as well as the last failed point after an
    # online release policy has made their roles explicit.
    online_receipt = root / "factor-retention.json"
    if result.get("status") != "complete" and online_receipt.is_file():
        online = read_json(online_receipt)
        if online.get("policy") == "released_factor_retention_v1" and online.get("events"):
            for name in online["events"][-1]["protected_paths"]:
                candidate = Path(name).resolve()
                if candidate.is_relative_to(root) and candidate.is_file():
                    retained.add(candidate)
                    if not any(Path(item["path"]).resolve() == candidate for item in result.get("artifacts", [])):
                        result.setdefault("artifacts", []).append(artifact_record("terminal_protected_qr_factor", candidate,
                            metadata={"accepted_covariance": False, "usage": "Accepted/current or latest failed-point factor protected by online retention"}))
    candidates, factors = [], []
    if profile != "legacy_v3":
        if result.get("status") != "complete":
            for point in root.glob("point-*"):
                if point.is_symlink() or not point.is_dir(): continue
                closure_receipt = point / "closure-retention.json"
                completed, current = set(), set()
                if closure_receipt.is_file():
                    closure = read_json(closure_receipt)
                    if closure.get("policy") != "completed_closure_retention_v1":
                        raise ValueError("Unknown failed-point closure-retention policy")
                    completed = set(closure["completed_closures"])
                    if closure["events"]:
                        current = {Path(name).resolve() for name in closure["events"][-1]["protected_paths"]}
                for path in point.glob("closure-*/*.dat"):
                    if (path.is_symlink() or path.parent.is_symlink() or not path.is_file()
                            or not CLOSURE.fullmatch(path.relative_to(root).as_posix())): continue
                    if path.parent.name in completed and path.resolve() not in current: continue
                    retained.add(path.resolve())
                    if not any(Path(item["path"]).resolve() == path.resolve() for item in result.get("artifacts", [])):
                        result.setdefault("artifacts", []).append(artifact_record("terminal_protected_closure_binary", path,
                            metadata={"accepted_covariance": False, "usage": "Current completed pair or unmarked partial closure retained for failed-fit recovery"}))
        for path in root.glob("point-*/*/*"):
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if CLOSURE.fullmatch(relative) or PROPOSAL.fullmatch(relative):
                candidates.append((path, "superseded_propagation_binary"))
        for path in root.glob("point-*/qr.*.R.bin"):
            match = FACTOR.fullmatch(path.relative_to(root).as_posix())
            if match and path.is_file() and not path.is_symlink():
                factors.append((tuple(map(int, match.groups())), path))
                candidates.append((path, "superseded_triangular_factor"))
        if result.get("status") != "complete" and factors:
            last = max(factors, key=lambda item: item[0])[1]
            retained.add(last.resolve())
            if not any(Path(item["path"]).resolve() == last.resolve() for item in result.get("artifacts", [])):
                result.setdefault("artifacts", []).append(artifact_record("terminal_diagnostic_qr_factor", last,
                    metadata={"accepted_covariance": False, "usage": "Last available failed-attempt linearization"}))
    receipt = root / "retention.json"
    previous = read_json(receipt) if receipt.exists() else {}
    if previous and (previous.get("policy") != POLICY or previous.get("profile") != profile):
        raise ValueError("Terminal retention receipt belongs to another policy or profile")
    removed, errors = list(previous.get("removed", [])), list(previous.get("errors", []))
    records = {item["path"]: item for item in removed}
    current_errors = []

    def persist(status):
        write_json(receipt, {"policy": POLICY, "profile": profile,
            "terminal_status": result.get("status"), "status": status,
            "removed": removed,
            "removed_bytes": sum(item["bytes"] for item in removed
                                 if item["status"] == "deleted_after_terminal_attempt"),
            "errors": errors, "elapsed_seconds": time.monotonic()-start,
            "preserved": "All final result artifacts, text logs/JSON/TSV diagnostics, physical parameters, original inputs and symlinks; failed-attempt protected factors/current closure pairs and unmarked partial closures",
            "timing_scope": "Storage cleanup follows measured fitting time and is reported separately",
            "archived_runtime_modified": False})

    # A prior interruption can occur after unlink but before completion is
    # recorded. Preserve its pre-unlink proof without inventing how it vanished.
    for record in removed:
        if record["status"] == "verified_before_release" and not Path(record["path"]).exists():
            record["status"] = "absent_after_verified_release"
    persist("running")
    for path, role in sorted(candidates):
        if path.resolve() in retained:
            continue
        try:
            path.resolve().relative_to(root)
            identity = {"path": str(path), "sha256": file_hash(path),
                        "bytes": path.stat().st_size, "role": role}
            record = records.get(str(path))
            if record is not None:
                if (any(record.get(key) != value for key, value in identity.items())
                        or record["status"] != "verified_before_release"):
                    raise ValueError("Previously audited terminal candidate changed or reappeared")
            else:
                record = {**identity, "status": "verified_before_release"}
                removed.append(record); records[str(path)] = record
            persist("running")  # Save deletion proof before release.
            path.unlink()
            record["status"] = "deleted_after_terminal_attempt"
            persist("running")
        except (OSError, ValueError) as error:
            failure = {"path": str(path), "error": str(error), "status": "not_removed"}
            errors.append(failure); current_errors.append(failure)
            persist("running")
    persist("partial" if current_errors else "complete")
    result["artifacts"] = [item for item in result.get("artifacts", [])
                           if item.get("role") != "numerical_retention_audit"]
    result["artifacts"].append(artifact_record("numerical_retention_audit", receipt))
    return result


def _stable_file_identity(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def compress_row_provenance(path):
    """Losslessly compress a closed native row ledger before releasing its bytes.

    The original is removed only after a complete decompression verifies its
    SHA256 and byte count. The deterministic gzip and receipt retain all rows.
    This maintenance occurs inside measured fitting time when called online.
    """
    path = Path(path).absolute()
    if path.is_symlink() or not re.fullmatch(r"qr\.\d+\.rows\.tsv", path.name):
        raise ValueError("Only regular closed native row-provenance ledgers can be compressed")
    return _compress_closed_text(path, "closed_native_row_provenance", "verified_row_compression_v1")


def _compress_closed_text(path, role, policy):
    """Shared verified compression primitive; callers restrict candidate names."""
    import gzip
    import hashlib
    import os
    from orbit_poc.comparison.protocol import read_json

    path = Path(path).absolute()
    if path.is_symlink():
        raise ValueError("Only regular closed text files can be compressed")
    destination = path.with_name(path.name + ".gz")
    temporary = path.with_name(path.name + ".gz.copying")
    receipt_path = path.with_name(path.name + ".compression.json")
    start = time.monotonic()

    def unpack_digest(candidate):
        digest, count = hashlib.sha256(), 0
        with gzip.open(candidate, "rb") as stream:
            for block in iter(lambda: stream.read(1024*1024), b""):
                digest.update(block); count += len(block)
        return digest.hexdigest(), count

    if not path.exists():
        if not receipt_path.exists() or not destination.is_file() or destination.is_symlink():
            raise ValueError("Missing row ledger and verified compressed recovery receipt")
        receipt = read_json(receipt_path)
        if (receipt.get("policy") != policy or receipt.get("role") != role
                or receipt.get("source", {}).get("path") != str(path)
                or receipt.get("compressed", {}).get("path") != str(destination)
                or destination.stat().st_size != receipt["compressed"].get("bytes")
                or file_hash(destination) != receipt["compressed"]["sha256"]
                or unpack_digest(destination) != (receipt["source"]["sha256"], receipt["source"]["bytes"])):
            raise ValueError("Compressed row-provenance identity changed")
        receipt.update(status="complete", original_removed=True, round_trip_verified=True)
        write_json(receipt_path, receipt)
        return receipt
    if not path.is_file() or destination.is_symlink() or temporary.is_symlink():
        raise ValueError("Row compression requires regular source and staging files")
    before = _stable_file_identity(path)
    if receipt_path.exists() and not destination.exists():
        previous = read_json(receipt_path)
        if previous.get("source") != {"path": str(path), "sha256": file_hash(path), "bytes": before[2]}:
            raise ValueError("Interrupted compression source identity changed")
    if destination.exists():
        if not receipt_path.exists(): raise ValueError("Unindexed compressed row ledger already exists")
        receipt = read_json(receipt_path)
        digest = file_hash(path)
        if (receipt.get("policy") != policy or receipt.get("role") != role
                or receipt.get("source") != {"path": str(path), "sha256": digest, "bytes": before[2]}
                or receipt.get("compressed", {}).get("path") != str(destination)
                or destination.stat().st_size != receipt["compressed"].get("bytes")
                or file_hash(destination) != receipt["compressed"]["sha256"]
                or unpack_digest(destination) != (digest, before[2])):
            raise ValueError("Existing compressed ledger does not match its original")
    else:
        digest, count = hashlib.sha256(), 0
        with path.open("rb") as source, temporary.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", compresslevel=6, mtime=0, fileobj=raw) as zipped:
                for block in iter(lambda: source.read(1024*1024), b""):
                    zipped.write(block); digest.update(block); count += len(block)
            raw.flush(); os.fsync(raw.fileno())
        if path.is_symlink() or _stable_file_identity(path) != before:
            raise ValueError("Row ledger changed during compression; original preserved")
        digest = digest.hexdigest()
        if unpack_digest(temporary) != (digest, count):
            raise ValueError("Compressed row round-trip verification failed; original preserved")
        receipt = {"policy": policy, "status": "verified_copy",
            "source": {"path": str(path), "sha256": digest, "bytes": count},
            "compressed": {"path": str(destination), "sha256": file_hash(temporary), "bytes": temporary.stat().st_size},
            "role": role, "round_trip_verified": True,
            "timing_scope": "Online maintenance is included in measured fit time",
            "all_original_content_preserved": True}
        if role == "closed_native_row_provenance":
            receipt["all_original_row_content_preserved"] = True
        write_json(receipt_path, receipt)
        temporary.replace(destination)
    if path.is_symlink() or _stable_file_identity(path) != before:
        raise ValueError("Row ledger changed before release; original preserved")
    # Persist proof before unlink; an interruption remains recoverable using
    # the retained source or verified gzip and this receipt.
    receipt.update(status="verified_copy", original_removed=False)
    write_json(receipt_path, receipt)
    path.unlink()
    receipt.update(status="complete", original_removed=True, elapsed_seconds=time.monotonic()-start)
    write_json(receipt_path, receipt)
    return receipt



def compact_closed_proposal(directory, metrics):
    """Retain a completed proposal's text and metrics; release its unused binary.

    Call only after the optimizer reads the trajectory and computes correction
    metrics. Failed or unmarked proposals are never selected automatically.
    """
    import math
    root = Path(directory).absolute()
    if root.is_symlink() or not root.is_dir() or not re.fullmatch(r"proposal-\d+", root.name):
        raise ValueError("Proposal compaction requires an explicitly completed proposal directory")
    if (not isinstance(metrics, dict) or not metrics
            or any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in metrics.values())):
        raise ValueError("Completed proposal metrics must be finite scalar values")
    binary, text = root / "orbit.dat", root / "orbit.txt"
    receipt_path = root / "proposal-retention.json"
    previous = read_json(receipt_path) if receipt_path.exists() else {}
    if previous and (previous.get("policy") != "completed_proposal_retention_v1"
                     or previous.get("directory") != str(root) or previous.get("metrics") != metrics):
        raise ValueError("Completed proposal receipt or metrics changed")
    if binary.is_symlink() or (binary.exists() and not binary.is_file()):
        raise ValueError("Completed proposal binary must be a regular file")
    if not binary.exists() and not previous:
        raise ValueError("Missing completed proposal binary and recovery receipt")
    if binary.exists():
        before = _stable_file_identity(binary)
        identity = {"path": str(binary), "sha256": file_hash(binary), "bytes": before[2],
                    "role": "completed_linearized_proposal_binary"}
        if previous and any(previous["binary"].get(key) != value for key, value in identity.items()):
            raise ValueError("Previously audited proposal binary changed")
    else:
        before = None
        identity = {key: previous["binary"][key] for key in ("path", "sha256", "bytes", "role")}
    started = time.monotonic()
    compressed = _compress_closed_text(text, "closed_linearized_proposal_trajectory",
                                      "verified_proposal_compression_v1")
    proof = text.with_name(text.name + ".compression.json")
    binary_record = {**identity, "status": "verified_before_release"}
    record = {"policy": "completed_proposal_retention_v1", "directory": str(root),
              "metrics": dict(metrics), "binary": binary_record, "status": "running",
              "trajectory": compressed["compressed"],
              "trajectory_compression_receipt": {"path": str(proof), "sha256": file_hash(proof)},
              "errors": list(previous.get("errors", [])),
              "preserved": "Full trajectory text, correction metrics, physical parameters, configuration and logs",
              "timing_scope": "Online maintenance is included in measured fit time"}
    write_json(receipt_path, record)
    try:
        if before is not None:
            if binary.is_symlink() or _stable_file_identity(binary) != before:
                raise ValueError("Proposal binary changed before release")
            binary.unlink()
            binary_record["status"] = "deleted_after_completed_proposal"
        else:
            binary_record["status"] = (previous["binary"]["status"]
                if previous["binary"]["status"] == "deleted_after_completed_proposal"
                else "absent_after_verified_release")
        record["status"] = "complete"
    except (OSError, ValueError) as error:
        record["errors"].append({"path": str(binary), "error": str(error), "status": "not_removed"})
        record["status"] = "partial"
    record["elapsed_seconds"] = time.monotonic()-started
    write_json(receipt_path, record)
    return record

def compact_closed_closures(directory, current_closure):
    """Release completed closure binaries and compress text after state reads.

    The caller marks a successfully closed/read trajectory explicitly. Only
    marked closures are candidates; partial later directories stay untouched.
    The current orbit/variational pair remains available for the next closure,
    covariance and final artifacts. All text is retained losslessly.
    """
    root = Path(directory).resolve()
    current = Path(current_closure)
    if not current.is_absolute(): current = root / current
    if (current.is_symlink() or current.parent.resolve() != root
            or not re.fullmatch(r"closure-\d+", current.name)):
        raise ValueError("Current closure must be a direct regular closure directory")
    current = current.resolve()
    for name in ("orbit.dat", "variational.dat"):
        if (current / name).is_symlink() or not (current / name).is_file():
            raise ValueError("Current completed closure is missing a required binary")
    if not (current / "orbit.txt").is_file() and not (current / "orbit.txt.gz").is_file():
        raise ValueError("Current completed closure is missing its exported trajectory")
    receipt_path = root / "closure-retention.json"
    if receipt_path.exists():
        receipt = read_json(receipt_path)
        if receipt.get("policy") != "completed_closure_retention_v1":
            raise ValueError("Unknown closure-retention policy")
    else:
        receipt = {"policy": "completed_closure_retention_v1", "completed_closures": [], "events": [],
            "preserved": "Current completed orbit/variational pair, every trajectory text byte, all logs/metadata and unmarked incomplete closures",
            "timing_scope": "Online maintenance is included in measured fit time"}
    completed = receipt["completed_closures"]
    if any(int(Path(name).name.split("-")[-1]) > int(current.name.split("-")[-1]) for name in completed):
        raise ValueError("Cannot move completed closure protection backwards")
    if current.name not in completed: completed.append(current.name)
    event = {"current_closure": str(current), "protected_paths": [str(current / name) for name in ("orbit.dat", "variational.dat")],
             "compressed": [], "removed": [], "errors": [], "status": "planned"}
    receipt["events"].append(event)
    write_json(receipt_path, receipt)
    start = time.monotonic()
    for name in completed:
        folder = root / name
        if folder.is_symlink() or not re.fullmatch(r"closure-\d+", name) or folder.parent != root:
            raise ValueError("Completed closure identity changed")
        text = folder / "orbit.txt"
        try:
            compressed = _compress_closed_text(text, "completed_closure_trajectory", "verified_closure_text_compression_v1")
            proof = text.with_name(text.name + ".compression.json")
            event["compressed"].append({"source": compressed["source"], "compressed": compressed["compressed"],
                "receipt": {"path": str(proof), "sha256": file_hash(proof)}, "round_trip_verified": True})
        except (OSError, ValueError) as error:
            event["errors"].append({"path": str(text), "error": str(error), "status": "not_compressed"})
            continue  # A failed text copy must not release this closure's binary.
        if folder == current: continue
        for filename in ("orbit.dat", "variational.dat"):
            path = folder / filename
            if not path.exists(): continue
            try:
                if path.is_symlink() or not path.is_file(): raise ValueError("Closure binary is not a regular file")
                before = _stable_file_identity(path)
                record = {"path": str(path), "bytes": before[2], "sha256": file_hash(path),
                    "role": "superseded_completed_closure_binary", "status": "verified_before_release"}
                if path.is_symlink() or _stable_file_identity(path) != before:
                    raise ValueError("Closure binary changed while recording deletion proof")
                event["removed"].append(record)
                write_json(receipt_path, receipt)
                path.unlink()
                record["status"] = "deleted"
                write_json(receipt_path, receipt)
            except (OSError, ValueError) as error:
                event["errors"].append({"path": str(path), "error": str(error), "status": "not_confirmed_removed"})
    event.update(status="complete" if not event["errors"] else "partial", elapsed_seconds=time.monotonic()-start,
        removed_bytes=sum(row["bytes"] for row in event["removed"] if row["status"] == "deleted"))
    write_json(receipt_path, receipt)
    return event


def discard_inactive_factors(directory, protected=()):
    """Audit/delete only released R binaries, preserving current and newest R.

    Explicit protections identify the accepted/current factor. The newest
    available factor is always retained as failure evidence. Rows and all
    objective, rank, parameter and singular-value metadata are untouched.
    """
    from orbit_poc.comparison.protocol import read_json
    root = Path(directory).resolve()
    keep = {Path(path).resolve() for path in protected}
    for path in keep:
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("Protected factor is missing or outside this attempt")
    factors = []
    for path in root.glob("point-*/qr.*.R.bin"):
        match = FACTOR.fullmatch(path.relative_to(root).as_posix())
        if match and path.is_file() and not path.is_symlink():
            factors.append((tuple(map(int, match.groups())), path))
    if factors: keep.add(max(factors, key=lambda item: item[0])[1].resolve())
    receipt_path = root / "factor-retention.json"
    if receipt_path.exists():
        receipt = read_json(receipt_path)
        if receipt.get("policy") != "released_factor_retention_v1":
            raise ValueError("Unknown factor-retention receipt policy")
    else:
        receipt = {"policy": "released_factor_retention_v1", "events": [],
            "preserved": "Explicit current/accepted factors, newest factor, all row provenance and every non-R diagnostic",
            "timing_scope": "Online maintenance is included in measured fit time"}
    event = {"protected_paths": sorted(map(str, keep)), "removed": [], "errors": [], "status": "planned"}
    receipt["events"].append(event)
    write_json(receipt_path, receipt)
    start = time.monotonic()
    for _, path in sorted(factors):
        if path.resolve() in keep: continue
        try:
            before = _stable_file_identity(path)
            record = {"path": str(path), "sha256": file_hash(path), "bytes": before[2],
                      "role": "released_triangular_factor", "status": "verified_before_release"}
            if path.is_symlink() or _stable_file_identity(path) != before:
                raise ValueError("Factor changed while preparing its retention receipt")
            event["removed"].append(record)
            write_json(receipt_path, receipt)
            path.unlink()
            record["status"] = "deleted"
            write_json(receipt_path, receipt)
        except (OSError, ValueError) as error:
            event["errors"].append({"path": str(path), "error": str(error), "status": "not_confirmed_removed"})
    event.update(status="complete" if not event["errors"] else "partial",
                 elapsed_seconds=time.monotonic()-start,
                 removed_bytes=sum(row["bytes"] for row in event["removed"] if row["status"] == "deleted"))
    write_json(receipt_path, receipt)
    return event


def compress_closed_row_provenance(directory):
    """Compress/verify all closed row ledgers in one finished native point.

    Returns source, compressed-artifact and receipt identities for each ledger.
    The caller must have waited for native processes to exit, including failures.
    """
    folder = Path(directory).resolve()
    paths = set(folder.glob("qr.*.rows.tsv"))
    paths.update(path.with_suffix("") for path in folder.glob("qr.*.rows.tsv.gz"))
    results = []
    for path in sorted(paths):
        record = compress_row_provenance(path)
        receipt_path = path.with_name(path.name + ".compression.json")
        results.append({"source": record["source"], "compressed": record["compressed"],
            "receipt": {"path": str(receipt_path), "sha256": file_hash(receipt_path)},
            "status": record["status"], "round_trip_verified": record["round_trip_verified"]})
    return results
