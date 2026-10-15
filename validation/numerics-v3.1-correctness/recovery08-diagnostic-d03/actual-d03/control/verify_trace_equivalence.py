#!/usr/bin/env python3
"""Require exact original08/diagnostic-off/diagnostic-on first-four numerical identity."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

EXACT_SUFFIXES = ["R.bin", "z.bin", "rhs.bin", "parameters.tsv", "delta.tsv",
                  "singular_values.txt", "profile.json", "bias_coordinates.tsv",
                  "nuisance_coordinates.tsv", "receiver_times.tsv"]
TIMING_KEYS = {"peak_child_rss_bytes", "child_user_seconds", "child_system_seconds"}
RETIREABLE = {"R.bin":"superseded_triangular_factor", "z.bin":"superseded_transformed_target", "rhs.bin":"superseded_transformed_target_alias"}


def artifact(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}


def numerical_search(value):
    if isinstance(value, list):
        return [numerical_search(item) for item in value]
    if isinstance(value, dict):
        return {key:numerical_search(item) for key,item in value.items() if key not in TIMING_KEYS}
    return value


def row_bytes(directory, generation):
    plain = directory / f"qr.{generation}.rows.tsv"
    compressed = plain.with_suffix(".tsv.gz")
    if plain.exists() == compressed.exists():
        raise ValueError(f"Require exactly one original row file: {plain}")
    return (plain.read_bytes(), plain) if plain.exists() else (gzip.decompress(compressed.read_bytes()), compressed)


def factor_identity(directory, generation, suffix, last_generation):
    path=directory / f"qr.{generation}.{suffix}"
    if path.exists():
        return artifact(path)
    if suffix not in RETIREABLE or generation >= last_generation:
        raise ValueError(f"Required native numerical artifact is absent: {path}")
    receipt=directory / f"qr.{generation}.retention.json"
    value=json.loads(receipt.read_text())
    if value.get("schema")!="orbit-poc-native-factor-retention-v1" or value.get("status")!="completed":
        raise ValueError(f"Invalid original factor retention receipt: {receipt}")
    expected_path=str(path)
    matches=[item for item in value.get("artifacts",[]) if item.get("path")==expected_path]
    if len(matches)!=1 or matches[0].get("role")!=RETIREABLE[suffix]:
        raise ValueError(f"Missing or wrong retired-factor identity: {path}")
    item=matches[0]
    if not isinstance(item.get("sha256"),str) or len(item["sha256"])!=64 or any(c not in "0123456789abcdef" for c in item["sha256"]):
        raise ValueError("Invalid retired factor hash")
    if type(item.get("bytes")) is not int or item["bytes"]<16:
        raise ValueError("Invalid retired factor byte count")
    metadata=json.loads((directory / f"qr.{generation}.factor.json").read_text())
    if metadata.get("keep_intermediate_factors") is not False:
        raise ValueError("Missing factor contradicts its retention policy")
    return {"path":expected_path,"sha256":item["sha256"],"bytes":item["bytes"],"retention_receipt":artifact(receipt)}


def verify(directories, last_generation):
    if last_generation != 4 or len(directories) != 3:
        raise ValueError("D03 requires three replay directories and exactly four generations")
    expected = set(range(1, last_generation+1))
    last_available=[]
    for position,directory in enumerate(directories):
        actual={int(p.name.split(".")[1]) for p in directory.glob("qr.*.factor.json")}
        if position==0:
            if not actual or max(actual)<=4 or actual!=set(range(1,max(actual)+1)):
                raise ValueError("Original08 must preserve a contiguous longer replay including generations1-4")
        elif actual!=expected:
            raise ValueError(f"Diagnostic replay must contain exactly four generations: {directory}")
        last_available.append(max(actual))
    sentinels=[]
    required={"schema":"orbit-poc-d03-generation-stop-v1","diagnostic_only":True,
              "scientific_complete":False,"completed_generations":4,
              "reason":"bounded diagnostic stopped before generation5"}
    for directory in directories[1:]:
        path=directory/"qr.diagnostic-incomplete.json"
        value=json.loads(path.read_text())
        if value!=required:raise ValueError("Missing or invalid explicitly incomplete D03 stop")
        sentinels.append(artifact(path))
    checks = []
    for generation in sorted(expected):
        for suffix in EXACT_SUFFIXES:
            identities = [factor_identity(directory,generation,suffix,available) for directory,available in zip(directories,last_available)]
            comparison = [(item["sha256"],item["bytes"]) for item in identities]
            if not comparison[0] == comparison[1] == comparison[2]:
                raise ValueError(f"Numerical bytes differ: qr.{generation}.{suffix}")
            checks.append({"kind":"exact_bytes_or_original_retired_factor_identity", "files":identities})
        rows = [row_bytes(directory,generation) for directory in directories]
        if not rows[0][0] == rows[1][0] == rows[2][0]:
            raise ValueError(f"Original observation rows differ at generation {generation}")
        checks.append({"kind":"exact_decompressed_row_bytes", "sha256":hashlib.sha256(rows[0][0]).hexdigest(),"files":[artifact(item[1]) for item in rows]})
        for suffix in ["factor.json", "nuisance_line_search.json"]:
            paths = [directory / f"qr.{generation}.{suffix}" for directory in directories]
            values = [json.loads(path.read_text()) for path in paths]
            if suffix == "factor.json":
                for value in values:
                    if "spool_directory" not in value:
                        raise ValueError("Factor metadata lacks explicit spool directory")
                    del value["spool_directory"]
                exclusions = ["spool_directory"]
            else:
                values = [numerical_search(value) for value in values]
                exclusions = sorted(TIMING_KEYS)
            if not values[0] == values[1] == values[2]:
                raise ValueError(f"Numerical metadata differ: qr.{generation}.{suffix}")
            checks.append({"kind":"exact_json_except_explicit_operational_fields","excluded_keys":exclusions,"files":[artifact(path) for path in paths]})
    return {"schema":"orbit-poc-d03-equivalence-v1","passed":True,
            "diagnostic_only":True,"scientific_validation_complete":False,"stop_receipts":sentinels,
            "last_generation":last_generation,"directories":[str(p) for p in directories],"checks":checks,
            "scope":"Diagnostic trace arithmetic equivalence only; no scientific gate classification is changed."}


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ["reference","trace-off","trace-on","receipt"]:
        parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--last-generation",type=int,required=True)
    args=parser.parse_args()
    if args.receipt.exists():
        parser.error("Receipt already exists")
    try:
        result=verify([args.reference,args.trace_off,args.trace_on],args.last_generation)
    except Exception as error:
        result={"schema":"orbit-poc-d03-equivalence-v1","passed":False,"error":repr(error)}
    with args.receipt.open("x") as stream:
        json.dump(result,stream,indent=2,sort_keys=True);stream.write("\n")
    raise SystemExit(0 if result["passed"] else 1)
