"""Ordered acceptance evidence required before scientific production runs.

Evidence is an auditable record, not a numerical test by itself. Each passing
gate must link nonempty, hashed results from the actual checks. Development
preparation remains available without these records; calibration does not.
"""
from datetime import datetime
from pathlib import Path


PRECALIBRATION_GATES = (
    "external_baseline", "model_correctness", "pipeline_correctness", "numerical_accuracy",
)


def read_gates(root):
    from .protocol import read_json
    path = Path(root) / "acceptance-gates.json"
    return read_json(path) if path.exists() else {}


def validate_gates(root, frozen):
    from .protocol import canonical_hash, file_hash
    record = read_gates(root)
    if not record:
        raise ValueError("Acceptance gates 1–4 must pass before calibration or evaluation; "
                         "save their hashed evidence in acceptance-gates.json")
    if record.get("schema_version") != 3 or record.get("protocol_hash") != frozen["protocol_hash"]:
        raise ValueError("Acceptance evidence belongs to another protocol/source snapshot")
    payload = {key: value for key, value in record.items() if key != "evidence_hash"}
    if record.get("evidence_hash") != canonical_hash(payload):
        raise ValueError("Acceptance evidence has been modified")
    gates = record.get("gates", {})
    previous = None
    for name in PRECALIBRATION_GATES:
        gate = gates.get(name, {})
        if gate.get("passed") is not True or not gate.get("artifacts"):
            raise ValueError(f"Acceptance gate {name} has not passed with recorded evidence")
        try:
            completed = datetime.fromisoformat(gate["completed_at"])
            if completed.tzinfo is None or previous is not None and completed < previous:
                raise ValueError("unordered or timezone-free timestamp")
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Acceptance gate {name} requires ordered UTC completion timestamps") from error
        previous = completed
        for artifact in gate["artifacts"]:
            path = Path(artifact.get("path", ""))
            if not path.is_absolute():
                path = Path(root) / path
            if not path.is_file() or not path.stat().st_size or file_hash(path) != artifact.get("sha256"):
                raise ValueError(f"Acceptance evidence is missing, empty, or modified: {name}/{path.name}")
    return record
