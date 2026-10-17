#!/usr/bin/env python3
"""Independent Decimal replay of bounded, numerically equivalent native row traces.

This tool does not run an estimator or modify any trace. It requires the successful
three-way numerical-equivalence receipt before it produces an actual analysis.
All high-precision chains use exact stored binary64 primitive coefficients and
states; optional ideal-state update checks are labelled separately.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, localcontext
import hashlib
import json
import math
from pathlib import Path
import re
import struct

PRECISION = 110
SELECTED = {(0, 13, 30): 5, (0, 4, 115): 1, (0, 16, 8): 4,
            (0, 9, 114): 4, (0, 9, 113): 5}
HEX = re.compile(r"([+-]?)0x([0-9a-f]+)(?:\.([0-9a-f]*))?p([+-]?\d+)\Z", re.I)


def exact_hex(text: str) -> Decimal:
    """Parse binary floating notation exactly, including x87 beyond binary64."""
    match = HEX.fullmatch(text)
    if not match:
        raise ValueError(f"Finite hexadecimal floating value required: {text!r}")
    sign, whole, fraction, exponent = match.groups()
    fraction = fraction or ""
    number = int(whole + fraction, 16)
    exponent = int(exponent) - 4 * len(fraction)
    if abs(exponent) > 20000:
        raise ValueError("Unbounded floating exponent")
    if exponent < 0:
        digits = str(number * 5 ** (-exponent))
        return Decimal((int(sign == "-"), tuple(map(int, digits)), exponent))
    return Decimal((int(sign == "-"), tuple(map(int, str(number << exponent))), 0))


def rounded64(value: Decimal) -> Decimal:
    """Nearest-even binary64 rounding, separate from Decimal expression replay."""
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Nonfinite reconstructed binary64 value")
    return Decimal.from_float(result)


def artifact(path: Path) -> dict:
    return {"path": str(path), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


@dataclass(frozen=True)
class Record:
    file: str
    line: int
    stem: str
    phase: str
    alpha: Decimal
    block: tuple[int, int, int]
    row: int
    component: str
    stage: str
    kind: str
    index: int
    value: Decimal
    bits: str
    evaluation: int
    event: int
    audit_mode: str


def parse_trace(path: Path) -> list[Record]:
    records = []
    previous_event = -1
    for line_number, text in enumerate(path.read_text().splitlines(), 1):
        fields = text.split("\t")
        if len(fields) != 16:
            raise ValueError(f"Expected 16 columns at {path}:{line_number}")
        stem, phase, alpha, recv, trans, epoch, row, component, stage, kind, index, val, bits, evaluation, event, audit = fields
        value = exact_hex(val)
        if kind == "double":
            if not re.fullmatch("[0-9a-f]{16}", bits):
                raise ValueError("Invalid binary64 bit pattern")
            decoded = struct.unpack(">d", bytes.fromhex(bits))[0]
            if not math.isfinite(decoded) or Decimal.from_float(decoded) != value:
                raise ValueError("Hexadecimal value disagrees with binary64 bits")
            if decoded == 0 and (bits[0] in "89abcdef") != value.is_signed():
                raise ValueError("Signed zero disagrees with binary64 bits")
        elif kind != "long_double" or bits != "-":
            raise ValueError("Unknown or malformed floating representation")
        block = int(recv), int(trans), int(epoch)
        if block not in SELECTED:
            raise ValueError(f"Unapproved observation block {block}")
        event = int(event)
        if event <= previous_event:
            raise ValueError("Nonmonotonic per-process event counter")
        previous_event = event
        records.append(Record(str(path), line_number, stem, phase, exact_hex(alpha), block,
                              int(row), component, stage, kind, int(index), value, bits,
                              int(evaluation), event, audit))
    return records


def one(records, stage, row=None, index=None, component=None, required=True):
    matches = [r for r in records if r.stage == stage and
               (row is None or r.row == row) and
               (index is None or r.index == index) and
               (component is None or r.component == component)]
    if len(matches) == 1:
        return matches[0].value
    if not matches and not required:
        return None
    raise ValueError(f"Expected one {stage} row={row} index={index} component={component}, found {len(matches)}")


def matrix(records, stage, component=None):
    result = {}
    for r in records:
        if r.stage == stage and (component is None or r.component == component):
            key = r.row, r.index
            if key in result:
                raise ValueError(f"Ambiguous repeated matrix entry: {stage} {key}")
            result[key] = r.value
    return result


def difference(label, observed, precise):
    return {"stage": label, "observed": str(observed), "precise_at_stored_inputs": str(precise),
            "observed_minus_precise": str(observed - precise)}


def stored_stec_term(number, values, stec):
    """Same native rounded coefficient; high-precision product/state arithmetic."""
    ap, s, r, b = (values[key] for key in ("Ap", "s", "r", "bending"))
    f2, f3, f4 = (values[key] for key in ("f2", "f3", "f4"))
    coefficient = {1: lambda: rounded64(-ap / f2),
                   2: lambda: rounded64(rounded64(-s / 2) / f3),
                   3: lambda: rounded64(rounded64(-r / 3) / f4),
                   4: lambda: rounded64(b / f4),
                   5: lambda: rounded64(ap / f2),
                   6: lambda: rounded64(s / f3),
                   7: lambda: rounded64(r / f4)}[number]()
    power = 2 if number in (3, 4, 7) else 1
    precise = coefficient * stec ** power
    native_product = rounded64(coefficient * (rounded64(stec * stec) if power == 2 else stec))
    return coefficient, precise, native_product


def segments(records):
    """Observed starts an equation; explicit counters separate repeated evaluations."""
    open_segments = {}
    result = []
    for record in records:
        key = record.file, record.evaluation, record.block
        if record.stage == "observed":
            if key in open_segments:
                result.append(open_segments.pop(key))
            open_segments[key] = []
        if key in open_segments:
            open_segments[key].append(record)
    result.extend(open_segments.values())
    return sorted(result, key=lambda rows: (rows[0].file, rows[0].event))


def validate_model_corrections(records, row):
    """Accept Group only when its traced child sequence explains every change."""
    stack = []
    for record in records:
        if record.row != row:
            continue
        if record.stage.startswith("before_model:"):
            stack.append({"name": record.stage.removeprefix("before_model:"),
                          "before": record.value, "children": []})
        elif record.stage.startswith("after_model:"):
            name = record.stage.removeprefix("after_model:")
            if not stack or stack[-1]["name"] != name:
                raise ValueError("Unbalanced model trace nesting")
            model = stack.pop()
            model["after"] = record.value
            if re.fullmatch(r"(?:\d+)?GnssParametrizationGroup", name):
                children = model["children"]
                if children:
                    boundaries = [(model["before"], children[0]["before"]),
                                  (children[-1]["after"], model["after"])]
                    boundaries += [(left["after"], right["before"]) for left, right in zip(children, children[1:])]
                    if any(left != right for left, right in boundaries):
                        raise ValueError("Group wrapper changes residual outside its traced children")
                elif model["before"] != model["after"]:
                    raise ValueError("Nonzero Group wrapper lacks traced children")
            elif not re.fullmatch(r"(?:\d+)?GnssParametrizationIonosphereSTEC", name):
                if model["before"] != model["after"]:
                    raise ValueError(f"Unreconstructed nonzero correction from {name}")
            if stack:
                stack[-1]["children"].append(model)
    if stack:
        raise ValueError("Unclosed model trace nesting")


def analyze_equation(records):
    first = records[0]
    row = SELECTED[first.block]
    result = {"file": first.file, "stem": first.stem, "phase": first.phase,
              "alpha": str(first.alpha), "block": list(first.block), "row": row,
              "evaluation": first.evaluation, "first_event": first.event,
              "audit_mode": first.audit_mode, "complete": False, "stages": []}
    try:
        chain = one(records, "range_twofold_high", row) + one(records, "range_twofold_low", row)
        result["stages"].append(difference("range_narrowed", one(records, "range_narrowed", row), chain))
        result["native_state"] = {stage: str(one(records, stage)) for stage in
                                  ("receiver_clock_seconds", "transmitter_clock_seconds", "transmitter_scale")}
        for component in ("receiver", "transmitter"):
            bias = matrix(records, "signal_bias_operand", component)
            pattern = matrix(records, "antenna_pattern_operand", component)
            native = matrix(records, component + "_antenna_operand", component)
            if not native or set(bias) != set(native) or set(pattern) != set(native):
                raise ValueError(f"Incomplete {component} antenna input vectors")
            precise = {k: bias[k] + pattern[k] for k in native}
            result["stages"].extend(difference(f"{component}_antenna_operand[{k[0]}]", native[k], precise[k]) for k in native)
            if component == "receiver":
                term = precise[row, 0]
            else:
                composition = matrix(records, "signal_composition")
                coefficients = {j: v for (i, j), v in composition.items() if i == row}
                if set(coefficients) != {i for i, j in precise if j == 0}:
                    raise ValueError("Incomplete transmitter composition inputs")
                term = sum((v * precise[j, 0] for j, v in coefficients.items()), Decimal(0))
                result["stages"].append(difference("transmitter_composed_operand", one(records, "transmitter_composed_operand", row), term))
            chain -= term
            result["stages"].append(difference(f"after_{component}_antenna", one(records, f"after_{component}_antenna", row), chain))
        ambiguity = one(records, "ambiguity_operand", row, required=False)
        if ambiguity is not None:
            mapping = one(records, "ambiguity_type_mapping", row, required=False)
            if mapping is None:
                if ambiguity != 0:
                    raise ValueError("Nonzero ambiguity lacks native coordinate mapping")
                term = Decimal(0)
            else:
                if mapping != int(mapping):
                    raise ValueError("Noninteger ambiguity mapping")
                coordinates = matrix(records, "ambiguity_native_coordinates")
                composition = matrix(records, "ambiguity_composition")
                coefficients = {j: v for (i, j), v in composition.items() if i == int(mapping)}
                if set(coefficients) != {i for i, j in coordinates if j == 0}:
                    raise ValueError("Incomplete ambiguity composition inputs")
                term = sum((v * coordinates[j, 0] for j, v in coefficients.items()), Decimal(0))
            result["stages"].append(difference("ambiguity_operand", ambiguity, term))
            chain -= term
        result["stages"].append(difference("after_ambiguity", one(records, "after_ambiguity", row), chain))
        # Refuse to silently absorb unimplemented models into an arithmetic error.
        validate_model_corrections(records, row)
        stec = one(records, "STEC")
        primitives = {key: one(records, "ionosphere_" + key, row) for key in ("f2", "f3", "f4", "Ap", "s", "r", "bending")}
        operations = []
        for number in range(1, 8):
            before = one(records, f"stec_operation_{number}_before", row, required=False)
            if before is None:
                continue
            after = one(records, f"stec_operation_{number}_after", row)
            flag = {1: "apply1stOrder", 2: "apply2ndOrder", 3: "apply3rdOrder", 4: "applyBending",
                    5: "apply1stOrder", 6: "apply2ndOrder", 7: "apply3rdOrder"}[number]
            coefficient, term, native_product = stored_stec_term(number, primitives, stec)
            active = one(records, flag) != 0
            expected = rounded64(before - native_product) if active else before
            if active:
                chain -= term
            operations.append({"operation": number, "active": active, "coefficient": str(coefficient),
                               "native_separate_operations_match": expected == after,
                               "native_replay_minus_observed": str(expected - after),
                               **difference(f"stec_operation_{number}_after", after, chain)})
        if not operations:
            raise ValueError("No STEC operations in selected observation")
        result["stec_operations"] = operations
        result["native_replay_all_match"] = all(item["native_separate_operations_match"] for item in operations)
        result["stages"].append(difference("before_homogenize", one(records, "before_homogenize", row), chain))
        sigma = one(records, "homogenize_sigma", row)
        weight = rounded64(Decimal(1) / sigma)
        chain *= weight
        observed = one(records, "after_homogenize", row)
        result["stages"].append(difference("after_homogenize", observed, chain))
        result["sigma"] = str(sigma)
        result["native_weight"] = str(weight)
        result["observed_weighted_row"] = str(observed)
        result["precise_weighted_row_at_stored_state"] = str(chain)
        retained = one(records, "retained_original_rows", row, index=0, required=False)
        result["has_retained_original_row"] = retained is not None
        if retained is not None:
            result["retained_original_row"] = str(retained)
            if retained != observed:
                raise ValueError("Retained original row disagrees with after_homogenize")
        prior = one(records, "STEC_prior_row", required=False)
        if prior is not None:
            precise_prior = -one(records, "dSTEC") / one(records, "sigmaSTEC")
            result["stec_prior"] = difference("STEC_prior_row", prior, precise_prior)
        result["complete"] = True
    except (ValueError, KeyError, ZeroDivisionError) as error:
        result["unavailable_reason"] = str(error)
    return result


def update_checks(records):
    """Only updates with explicit before/delta/after operands can be inferred."""
    result = []
    for offset, first in enumerate(records):
        if first.stage not in ("local_STEC_before", "VTEC_STEC_before"):
            continue
        # Each update writes a contiguous bounded set, all within one context.
        following = []
        for current in records[offset:offset + 16]:
            if (current.file, current.evaluation, current.block) != (first.file, first.evaluation, first.block):
                break
            if current is not first and current.stage == first.stage:
                break
            following.append(current)
        try:
            if first.stage == "local_STEC_before":
                delta = one(following, "local_STEC_delta")
                for state in ("STEC", "dSTEC"):
                    before = one(following, "local_" + state + "_before")
                    after = one(following, "local_" + state + "_after")
                    result.append({"file": first.file, "evaluation": first.evaluation, "event": first.event,
                                   "block": list(first.block), "state": "local_" + state,
                                   "ideal_before_plus_delta": str(before + delta),
                                   "stored_after": str(after), "stored_minus_ideal": str(after - (before + delta)),
                                   "native_rounding_match": rounded64(before + delta) == after})
            else:
                coefficient = one(following, "VTEC_mapping_shadow")
                cosine = one(following, "VTEC_cos_shadow")
                sine = one(following, "VTEC_sin_shadow")
                delta = one(following, "VTEC_delta")
                gx = one(following, "VTEC_gradient_x_delta")
                gy = one(following, "VTEC_gradient_y_delta")
                ideal_delta = coefficient * (delta + cosine * gx + sine * gy)
                native_delta = rounded64(coefficient * rounded64(rounded64(delta + rounded64(cosine * gx)) + rounded64(sine * gy)))
                after = one(following, "VTEC_STEC_after")
                result.append({"file": first.file, "evaluation": first.evaluation, "event": first.event,
                               "block": list(first.block), "state": "VTEC_STEC", "shadow_coefficients": True,
                               "ideal_before_plus_delta": str(first.value + ideal_delta), "stored_after": str(after),
                               "stored_minus_ideal": str(after - (first.value + ideal_delta)),
                               "native_separate_operations_match": rounded64(first.value + native_delta) == after})
        except (ValueError, ZeroDivisionError) as error:
            result.append({"file": first.file, "event": first.event, "unavailable_reason": str(error)})
    return result


def paired_rows(equations):
    """Pair only a unique retained baseline and each trial with the same stem/block."""
    baselines = defaultdict(list)
    for eq in equations:
        if eq["complete"] and eq["has_retained_original_row"] and eq["phase"] == "linearization" and eq["audit_mode"] == "0":
            baselines[eq["stem"], tuple(eq["block"]), eq["row"]].append(eq)
    result = []
    for trial in equations:
        if not trial["complete"] or trial["phase"] != "trial":
            continue
        candidates = baselines[trial["stem"], tuple(trial["block"]), trial["row"]]
        entry = {key: trial[key] for key in ("file", "stem", "evaluation", "first_event", "block", "row", "alpha", "audit_mode")}
        if not trial["has_retained_original_row"]:
            entry["unavailable_reason"] = "Trial equation does not carry a retained original row"
        elif len(candidates) != 1:
            entry["unavailable_reason"] = f"Need one baseline; found {len(candidates)}"
        else:
            baseline = candidates[0]
            b, t = (Decimal(eq["observed_weighted_row"]) for eq in (baseline, trial))
            bp, tp = (Decimal(eq["precise_weighted_row_at_stored_state"]) for eq in (baseline, trial))
            native = (b - t) * (b + t) / 2
            precise = (bp - tp) * (bp + tp) / 2
            entry.update({"baseline_file": baseline["file"], "baseline_evaluation": baseline["evaluation"],
                          "native_row_actual_reduction": str(native), "precise_row_actual_reduction_at_stored_states": str(precise),
                          "native_minus_precise_reduction": str(native - precise),
                          "native_residual_change": str(t - b), "precise_residual_change_at_stored_states": str(tp - bp)})
            entry["native_stec_replay_matches_both"] = baseline["native_replay_all_match"] and trial["native_replay_all_match"]
            if "stec_prior" in baseline and "stec_prior" in trial:
                b, t = (Decimal(eq["stec_prior"]["observed"]) for eq in (baseline, trial))
                bp, tp = (Decimal(eq["stec_prior"]["precise_at_stored_inputs"]) for eq in (baseline, trial))
                entry["stec_prior_native_actual_reduction"] = str((b-t)*(b+t)/2)
                entry["stec_prior_precise_actual_reduction_at_stored_states"] = str((bp-tp)*(bp+tp)/2)
        result.append(entry)
    return result


def analyze(paths, equivalence):
    proof = json.loads(equivalence.read_text())
    if proof.get("schema") != "orbit-poc-diagnostic-row-trace-equivalence-v1" or proof.get("passed") is not True:
        raise ValueError("Successful original/off/on equivalence receipt is mandatory")
    # Reverify exact artifact identities captured by the equivalence receipt.
    for check in proof.get("checks", []):
        for item in check.get("files", []):
            source = Path(item["path"])
            if "retention_receipt" in item:
                item = item["retention_receipt"]
                source = Path(item["path"])
            if not source.is_file() or artifact(source)["sha256"] != item["sha256"]:
                raise ValueError(f"Equivalence evidence is absent or changed: {source}")
    if not proof.get("checks"):
        raise ValueError("Empty equivalence evidence")
    directories = proof.get("directories", [])
    if len(directories) != 3:
        raise ValueError("Equivalence receipt must identify original/off/on directories")
    on_directory = Path(directories[2]).resolve()
    if not paths or len(set(path.resolve() for path in paths)) != len(paths):
        raise ValueError("Require distinct nonempty trace paths")
    all_records = [record for path in paths for record in parse_trace(path)]
    if not all_records:
        raise ValueError("Empty trace")
    initialization_records = [record for record in all_records if record.stem == "" and
                              record.phase == "unassigned" and record.evaluation == 0]
    records = [record for record in all_records if not (record.stem == "" and
               record.phase == "unassigned" and record.evaluation == 0)]
    if not records:
        raise ValueError("Trace contains only unassigned initialization records")
    for record in records:
        if Path(record.stem).parent.resolve() != on_directory:
            raise ValueError(f"Trace stem is outside verified trace-on directory: {record.stem}")
    with localcontext() as context:
        context.prec = PRECISION
        equations = [analyze_equation(rows) for rows in segments(records)]
        updates = update_checks(records)
        pairs = paired_rows(equations)
    return {"schema": "orbit-poc-row-arithmetic-decimal-audit-v1", "diagnostic_only": True,
            "decimal_precision": PRECISION, "rounding_assumption": "IEEE binary64 round-to-nearest ties-to-even; uncontracted products are separately tested against actual native stage outputs",
            "equivalence_receipt": artifact(equivalence), "trace_artifacts": [artifact(path) for path in paths],
            "record_count": len(all_records), "fit_record_count": len(records),
            "excluded_initialization_record_count": len(initialization_records),
            "initialization_exclusion_rule": "empty stem AND phase=unassigned AND evaluation=0; parsed and bit-checked, outside any fit generation",
            "equations": equations, "updates": updates, "paired_selected_rows": pairs,
            "limitations": ["Five selected rows are a bounded diagnostic, not the full nonlinear objective or a scientific acceptance gate.",
                            "Precise evaluation retains exact stored native states and rounded native STEC coefficients; it does not replace them with ideal nuisance updates.",
                            "Only local STEC and VTEC updates have explicit before/delta/after operands. Ideal clock, signal-bias and ambiguity update-rounding attribution remains unavailable.",
                            "VTEC mapping/cosine/sine are native shadow evaluations; actual native operation replay is checked separately.",
                            "Unknown nonzero model corrections and ambiguous/missing trace stages fail closed for that equation.",
                            "No row-to-Jacobian prediction comparison is claimed by this trace-only analyzer."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, action="append", required=True)
    parser.add_argument("--equivalence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.trace, args.equivalence)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
