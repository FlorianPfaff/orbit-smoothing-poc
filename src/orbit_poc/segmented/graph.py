"""Lift actual native variation-of-constants and GNSS exports into local rows.

No forces are propagated here.  The stored fundamental matrices, quadrature
integrands, pulse maps and observation interpolation coefficients all come
from the same chronological native evaluation as the dense rank certificate.
"""
from __future__ import annotations

from collections import defaultdict
import csv
import json
import math
from pathlib import Path

import numpy as np
from scipy.linalg import qr, svdvals, solve_triangular

from orbit_poc.numerics.optimizer import NumericalFailure
from .solver import (EliminationGroup, SegmentedGraph, SparseRow, Variable,
                     linearization_digest)


def _records(path):
    with Path(path).open() as stream:
        for line in stream:
            value = json.loads(line, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
            if not isinstance(value, dict):
                raise ValueError("Native segmented export needs JSON objects")
            yield value


def _hex_extended(value):
    """Parse a native hexadecimal long double without first rounding to float64."""
    mantissa, exponent = value.lower().split("p")
    sign = -1 if mantissa.startswith("-") else 1
    mantissa = mantissa.lstrip("+-")
    if not mantissa.startswith("0x"):
        raise ValueError("Expected native hexadecimal interpolation coefficient")
    whole, _, fraction = mantissa[2:].partition(".")
    significand = int(whole + fraction, 16)
    return np.ldexp(np.longdouble(str(sign*significand)), int(exponent)-4*len(fraction))


def _coalesce(terms):
    by_id = defaultdict(list)
    for identifier, value in terms:
        by_id[int(identifier)].append(np.longdouble(value))
    result = []
    for identifier in sorted(by_id):
        value = float(sum(by_id[identifier], np.longdouble(0)))
        if not math.isfinite(value):
            raise NumericalFailure("invalid_segment_graph", "Nonfinite lifted coefficient")
        if value != 0.:  # Only exact zeros; never discard a small direction.
            result.append((identifier, value))
    return tuple(result)


def _epoch_eliminate(rows, local_ids, *, index):
    """Same rank-checked clock/VTEC QR on local sparse observation columns."""
    if not rows:
        if local_ids:
            raise NumericalFailure("rank_deficient", "Epoch nuisance has no weighted rows")
        return [], {"epoch": index, "local_columns": 0, "removed_rows": 0}
    local_ids = tuple(local_ids)
    local_map = {value: i for i, value in enumerate(local_ids)}
    columns = sorted({identifier for row in rows for identifier, value in row.terms
                      if value != 0 and identifier not in local_map})
    column_map = {value: i for i, value in enumerate(columns)}
    a = np.zeros((len(rows), len(columns)))
    b = np.zeros((len(rows), len(local_ids)))
    target = np.array([row.rhs for row in rows])
    for i, row in enumerate(rows):
        for identifier, value in row.terms:
            if identifier in local_map:
                b[i, local_map[identifier]] += value
            else:
                a[i, column_map[identifier]] += value
    k = len(local_ids)
    receipt = {"epoch": index, "local_columns": k, "removed_rows": k}
    if k:
        norms = np.linalg.norm(b, axis=0)
        scales = np.divide(1., norms, out=np.ones_like(norms), where=norms > 0)
        b *= scales
        singular = svdvals(b)
        largest = float(singular[0]) if singular.size else 0.
        smallest = float(singular[-1]) if len(singular) == k else 0.
        threshold = np.finfo(float).eps * max(b.shape) * largest
        if smallest <= 10*threshold:
            reason = "rank_deficient" if smallest <= threshold else "unresolved_rank"
            raise NumericalFailure(reason, f"Segmented epoch {index} clock/VTEC QR rank is {reason}")
        q, r = qr(b, mode="full", check_finite=False)
        a = q.T @ a
        target = q.T @ target
        # Conditional information is retained for nuisance recovery/audit.  It
        # is not extra residual energy: these nuisance variables are profiled.
        receipt.update(scales=scales.tolist(), ids=list(local_ids),
                       columns=columns, R=r[:k].tolist(), S=a[:k].tolist(),
                       rhs=target[:k].tolist(), removed_rhs_energy=float(target[:k] @ target[:k]))
    stage = max(row.stage for row in rows)
    reduced = [SparseRow(-1, stage, float(target[i]),
                         tuple((identifier, float(value)) for identifier, value in zip(columns, a[i]) if value != 0.),
                         f"epoch:{index}:clock_vtec_qr:{i-k}")
               for i in range(k, len(rows))]
    return reduced, receipt


def recover_epoch_nuisance(conditionals, values):
    """Recover the native clock/VTEC corrections from their retained QR rows.

    ``values`` contains unscaled original and auxiliary corrections. The
    conditional column scaling is applied only to its eliminated coordinates.
    This recovery does not change the already marginalized dynamic solution.
    """
    recovered = {}
    for conditional in conditionals:
        count = conditional["local_columns"]
        if count == 0:
            continue
        identifiers = conditional["ids"]
        columns = conditional["columns"]
        r = np.asarray(conditional["R"],dtype=float)
        s = np.asarray(conditional["S"],dtype=float)
        rhs = np.asarray(conditional["rhs"],dtype=float)
        scales = np.asarray(conditional["scales"],dtype=float)
        if (len(identifiers) != count or len(set(identifiers)) != count
                or set(identifiers)&recovered.keys() or r.shape != (count,count)
                or s.shape != (count,len(columns)) or rhs.shape != (count,)
                or scales.shape != (count,) or np.any(scales <= 0)
                or any(not np.isfinite(a).all() for a in (r,s,rhs,scales))):
            raise NumericalFailure("invalid_nuisance_conditional", "Clock/VTEC conditional identity or dimensions changed")
        try:
            remaining = np.array([values[i] for i in columns],dtype=float)
        except KeyError as error:
            raise NumericalFailure("invalid_nuisance_conditional", "A retained clock/VTEC dependency is missing") from error
        if not np.isfinite(remaining).all():
            raise NumericalFailure("invalid_nuisance_conditional", "Nonfinite retained nuisance dependency")
        try:
            result = scales*solve_triangular(r,rhs-s@remaining,lower=False,check_finite=False)
        except np.linalg.LinAlgError as error:
            raise NumericalFailure("invalid_nuisance_conditional", "Singular clock/VTEC conditional") from error
        if not np.isfinite(result).all():
            raise NumericalFailure("invalid_nuisance_conditional", "Nonfinite recovered nuisance correction")
        recovered.update(zip(identifiers,map(float,result)))
    return recovered


def build_graph(point, design_path, rows_path, observations_path, *, segment_seconds,
                segment_offset_seconds=0.):
    if segment_seconds not in (3600, 14400):
        raise ValueError("Frozen segmented profiles use one-hour or four-hour cuts")
    # This offset is an engineering test control, not a fourth benchmark
    # profile. Neither the physical grid nor any integration/interpolation
    # coefficient depends on where computational cuts are placed.
    if (isinstance(segment_offset_seconds, bool)
            or not isinstance(segment_offset_seconds, (int, float))
            or not math.isfinite(segment_offset_seconds)
            or not 0 <= segment_offset_seconds < segment_seconds):
        raise ValueError("Computational cut offset must be finite and within one segment")
    design = list(_records(design_path))
    if (not design or design[-1] != {"kind": "complete"}
            or design[0].get("schema") != "orbit-poc-segmented-design-v1"):
        raise NumericalFailure("incomplete_segment_export", "Incomplete native variation-of-constants export")
    meta = design[0]
    n, dynamic_count = int(meta["epochs"]), int(meta["parameter_count"])
    if n < 2 or meta["initial_parameter_offset"] != dynamic_count-6 or not meta.get("post_pulse"):
        raise NumericalFailure("invalid_segment_graph", "Native initial coordinates or pulse convention changed")
    epochs = {row["index"]: row for row in design if row["kind"] == "epoch"}
    if set(epochs) != set(range(n)):
        raise NumericalFailure("incomplete_segment_export", "Native grid epochs are missing or repeated")
    phi = np.array([epochs[i]["phi"] for i in range(n)]).reshape(n, 6, 6)
    if not np.isfinite(phi).all():
        raise NumericalFailure("invalid_segment_graph", "Nonfinite native fundamental matrix")
    dt = float(meta["dt"])
    if not math.isfinite(dt) or dt <= 0:
        raise NumericalFailure("invalid_segment_graph", "Invalid native cadence")
    times = np.array([(np.longdouble(epochs[i]["time"][0])-epochs[0]["time"][0])*86400 +
                      (np.longdouble(epochs[i]["time"][1])-epochs[0]["time"][1])*86400
                      for i in range(n)], dtype=np.longdouble)
    if np.max(np.abs(times-np.arange(n)*np.longdouble(dt))) > 1e-6:
        raise NumericalFailure("invalid_segment_graph", "Native variation grid is not the declared uniform grid")
    forcing = {row["index"]: row["integrand"] for row in design if row["kind"] == "forcing"}
    intervals = {row["interval"]: row["terms"] for row in design if row["kind"] == "quadrature"}
    if set(intervals) != set(range(n-1)):
        raise NumericalFailure("incomplete_segment_export", "Native quadrature intervals are missing")
    observations = list(_records(observations_path))
    if not observations:
        raise NumericalFailure("incomplete_segment_export", "Missing native observation-local designs")
    first = observations[0]["native_first"]
    with Path(rows_path).open() as stream:
        row_meta = json.loads(next(stream))
    if row_meta.get("schema") != "orbit-poc-segmented-weighted-rows-v1":
        raise NumericalFailure("invalid_segment_graph", "Wrong original weighted-row schema")
    transport = row_meta.get("dynamic_observation_terms","original_dense_columns")
    if transport not in ("original_dense_columns","native_local_stencil"):
        raise NumericalFailure("invalid_segment_graph","Unknown dynamic observation transport")
    local = int(row_meta["local_columns"])
    retained = int(row_meta["total_columns"])-local
    dynamic_ids = tuple(range(int(first)-local, int(first)-local+dynamic_count))
    if retained != len(point.scales) or dynamic_ids != tuple(np.flatnonzero(point.dynamic)):
        raise NumericalFailure("parameter_order", "Exported native dynamic block differs from original rank coordinates")
    coordinate_path = Path(point.metadata["factor_prefix"]+".parameters.tsv")
    coordinates = []
    if coordinate_path.is_file():
        with coordinate_path.open(newline="") as stream:
            reader = csv.DictReader(stream,delimiter="\t")
            if (reader.fieldnames != ["index","name","dynamic","unit","scale","coordinate_convention"]):
                raise NumericalFailure("parameter_order", "Native coordinate metadata header changed")
            coordinates = list(reader)
        if (len(coordinates) != local+retained
                or any(set(row) != set(reader.fieldnames) or None in row.values()
                       or row["index"] != str(i) or not row["name"] or not row["unit"]
                       or not row["coordinate_convention"] or row["dynamic"] not in ("0","1")
                       for i,row in enumerate(coordinates))):
            raise NumericalFailure("parameter_order", "Native coordinate identity, unit or convention changed")
        if any(float(row["scale"]) != point.scales[i]
               or bool(int(row["dynamic"])) != bool(point.dynamic[i])
               for i,row in enumerate(coordinates[local:])):
            raise NumericalFailure("parameter_order", "Native original-coordinate scale or dynamic identity changed")
    elif "diagnostics" in point.metadata:
        raise NumericalFailure("incomplete_segment_export", "Native coordinate metadata is missing")
    auxiliary = lambda epoch, component: retained + 6*int(epoch) + component

    # Native clocks retain their original IDs in a disjoint temporary space.
    clock_offset = retained+6*n
    motion = {}
    for observation in observations:
        if (observation["factor_stem"] != point.metadata["factor_prefix"]
                or observation["native_first"] != first or observation["native_count"] != dynamic_count
                or observation["arc"] != 0):
            raise NumericalFailure("stale_segment_graph", "Observation-local export belongs to another native factor/arc")
        position = np.asarray(observation["position_design"], dtype=np.longdouble).reshape(observation["rows"], 3)
        halo = observation["halo"]
        stage = max(int(term[0]) for term in halo)
        if stage >= n or any(int(term[0]) < 0 for term in halo):
            raise NumericalFailure("invalid_segment_graph", "Measurement halo lies outside the full arc")
        blocks = []
        for epoch, rounded, high, low in halo:
            weight = _hex_extended(high)+_hex_extended(low)
            if abs(float(weight)-float(rounded)) > abs(np.spacing(float(rounded))):
                raise NumericalFailure("invalid_segment_graph", "Interpolation coefficient transport changed")
            blocks.append((epoch, weight * (position @ phi[epoch, :3].astype(np.longdouble))))
        for i in range(len(position)):
            row_id = observation["row_start"]+i
            if row_id in motion:
                raise NumericalFailure("invalid_segment_graph", "Observation-local rows are duplicated")
            motion[row_id] = (stage, _coalesce((auxiliary(epoch, c), block[i, c])
                                             for epoch, block in blocks for c in range(6)))

    stochastic, epoch_receipts = [], []
    epoch_rows, epoch_columns = [], {}
    current_epoch = None
    seen_source = 0
    matched_motion = set()
    trailer = None

    def flush_epoch():
        nonlocal epoch_rows
        if current_epoch is None:
            return
        if current_epoch not in epoch_columns:
            raise NumericalFailure("incomplete_segment_export", "Epoch clock ownership metadata is missing")
        ids = [clock_offset+i for i in epoch_columns[current_epoch]]
        reduced, receipt = _epoch_eliminate(epoch_rows, ids, index=current_epoch)
        stochastic.extend(reduced)
        epoch_receipts.append(receipt)
        epoch_rows = []

    for record in _records(rows_path):
        kind = record["kind"]
        if kind == "metadata":
            continue
        if kind == "epoch":
            epoch_columns[record["index"]] = tuple(range(record["first"], record["first"]+record["count"]))
            continue
        if kind == "complete":
            trailer = record
            continue
        if kind != "row" or record["index"] != seen_source:
            raise NumericalFailure("incomplete_segment_export", "Weighted row order/accounting changed")
        seen_source += 1
        epoch = record["epoch"]
        if epoch != current_epoch:
            flush_epoch()
            current_epoch = epoch
        row_id = record["index"]
        if transport == "native_local_stencil":
            omitted = record.get("omitted_dynamic_columns")
            if (type(omitted) is not int or not 0 <= omitted <= dynamic_count
                    or omitted and row_id not in motion
                    or omitted and record["source"] != "weighted_observation"):
                raise NumericalFailure("incomplete_segment_export","Native row lacks its declared local physical columns")
        terms = []
        stage = 0
        if row_id in motion:
            if record["source"] != "weighted_observation":
                raise NumericalFailure("invalid_segment_graph", "Measurement-local map applied to a prior")
            stage, local_terms = motion[row_id]
            terms.extend(local_terms)
            matched_motion.add(row_id)
        for identifier, value in record["terms"]:
            if row_id in motion and first <= identifier < first+dynamic_count:
                continue
            if (record["source"] == "weighted_observation" and row_id not in motion
                    and first <= identifier < first+dynamic_count and value != 0):
                raise NumericalFailure("incomplete_segment_export", "A native dynamic observation row lacks a local map")
            terms.append((clock_offset+identifier if identifier < local else identifier-local, value))
        row = SparseRow(-1, stage, record["rhs"], _coalesce(terms),
                        f"native:{row_id}:{record['source']}")
        if epoch is None:
            if any(identifier >= clock_offset for identifier, _ in row.terms):
                raise NumericalFailure("unsupported_constraint", "Global or time-coupled local nuisance constraint")
            stochastic.append(row)
        else:
            epoch_rows.append(row)
    flush_epoch()
    if (trailer is None or trailer["source_rows"] != seen_source
            or trailer["reduced_rows"] != len(stochastic) or len(stochastic) != point.effective_rows
            or matched_motion != set(motion)):
        raise NumericalFailure("incomplete_segment_export", "Original/reduced row accounting does not match the native certificate")
    stochastic = [SparseRow(i, row.stage, row.rhs, row.terms, row.provenance)
                  for i, row in enumerate(stochastic)]

    # Exact native variation recurrence. Physical interpolation boundaries are
    # inherited from the export; computational segment cuts change no weights.
    equalities = []
    pulses = defaultdict(list)
    for record in design:
        if record["kind"] == "pulse":
            if record["epoch"] <= 0 or record["epoch"] >= n-1 or record["parameter"]+3 > dynamic_count-6:
                raise NumericalFailure("invalid_segment_graph", "Pulse export is not an interior native block")
            pulses[record["epoch"]].append(record)
    for epoch in range(n):
        by_component = [[] for _ in range(6)]
        for c in range(6):
            by_component[c].append((auxiliary(epoch, c), 1.))
            by_component[c].append((dynamic_ids[dynamic_count-6+c] if epoch == 0 else auxiliary(epoch-1, c), -1.))
        if epoch:
            for sample, weight, _ in intervals[epoch-1]:
                if sample not in forcing:
                    raise NumericalFailure("incomplete_segment_export", "Quadrature forcing sample is missing")
                for component, parameter, value in forcing[sample]:
                    if component not in range(6) or parameter not in range(dynamic_count-6):
                        raise NumericalFailure("parameter_order", "Force integrand contains an unknown native parameter")
                    by_component[component].append((dynamic_ids[parameter], -np.longdouble(weight)*value))
            for pulse in pulses[epoch]:
                block = np.asarray(pulse["map"]).reshape(6, 3)
                for c in range(6):
                    by_component[c].extend((dynamic_ids[pulse["parameter"]+j], -block[c, j]) for j in range(3))
        for c, terms in enumerate(by_component):
            equalities.append(SparseRow(len(stochastic)+len(equalities), epoch, 0., _coalesce(terms),
                                        f"native_variation_interval:{epoch}:component:{c}"))

    count = retained+6*n
    last_use = np.zeros(count, dtype=int)
    norms = np.zeros(count)
    for row in (*equalities, *stochastic):
        for identifier, value in row.terms:
            if identifier >= count:
                raise NumericalFailure("parameter_order", "Epoch nuisance survived the shared QR elimination")
            last_use[identifier] = max(last_use[identifier], row.stage)
            norms[identifier] = math.hypot(norms[identifier], value)
    ownership = defaultdict(lambda: [[], []])
    initial_ids = set(dynamic_ids[-6:])
    for identifier in initial_ids:
        if last_use[identifier] != 0:
            raise NumericalFailure("unsupported_constraint", "Initial coordinates have an unexpected nonlocal direct factor")
        ownership[0][0].append(identifier)
    # A forcing coefficient may stop appearing in newly arriving equations
    # before the last of those equations can be consumed. Interpolation halos
    # retain older states across a cut; their deterministic pivot must precede
    # stochastic elimination of every original parameter in that equation.
    # Otherwise the stochastic front would still touch an exact equality.
    auxiliary_owners = []
    previous = 0
    for epoch in range(n-1):
        stage = max(previous,int(max(last_use[auxiliary(epoch,c)] for c in range(6))))
        auxiliary_owners.append(stage)
        ownership[stage][0].extend(auxiliary(epoch,c) for c in range(6))
        previous = stage
    extended_dependencies = 0
    for row in equalities:
        if row.stage == 0:
            continue
        consumed_at = auxiliary_owners[row.stage-1]
        for identifier,value in row.terms:
            if identifier < retained and value != 0 and last_use[identifier] < consumed_at:
                last_use[identifier] = consumed_at
                extended_dependencies += 1
    for identifier in range(retained):
        if identifier in initial_ids:
            continue
        # The local state chain can be condensed at every grid epoch. Original
        # force/nuisance coordinates are retained through the chosen segment.
        # The uniform cadence was verified above. Use that exact grid for
        # computational ownership: rounded day fractions must not move an
        # otherwise exact cut to the following integration epoch.
        dependency_time = int(last_use[identifier])*dt
        stop = max(0., segment_offset_seconds + math.ceil(
            (dependency_time-segment_offset_seconds)/segment_seconds)*segment_seconds)
        stage = min(n-1, max(last_use[identifier], math.ceil(stop/dt)))
        ownership[stage][1].append(identifier)
    ownership[n-1][1].extend(auxiliary(n-1, c) for c in range(6))
    groups = tuple(EliminationGroup(stage, tuple(sorted(ids[0])), tuple(sorted(ids[1])))
                   for stage, ids in sorted(ownership.items()))
    variables = tuple(Variable(i, 1 if i < retained else 0,
                               float(point.scales[i]) if i < retained else (1/norms[i] if norms[i] else 1.),
                               int(last_use[i]),
                               coordinates[local+i]["name"] if i < retained and coordinates
                               else f"native:{i}" if i < retained else f"variation:{(i-retained)//6}:{(i-retained)%6}",
                               coordinates[local+i]["unit"] if i < retained and coordinates
                               else "" if i < retained else "m")
                      for i in range(count))
    graph = SegmentedGraph(variables, tuple(equalities), tuple(stochastic), groups,
                           tuple(range(retained)), linearization_digest(point), point.support_hash).validate()
    receipts = {"schema": "orbit-poc-segmented-graph-v1", "native_epochs": n,
                "native_original_columns": retained, "auxiliary_columns": 6*n,
                "equality_rows": len(equalities), "stochastic_rows": len(stochastic),
                "segment_seconds": segment_seconds, "segment_offset_seconds": segment_offset_seconds,
                "micro_front_count": len(groups),
                "ownership_extended_for_crossing_deterministic_stencils": extended_dependencies,
                "epoch_conditionals": epoch_receipts, "physical_propagation_split": False,
                "temporary_nuisance_id_offset": clock_offset,
                "original_coordinate_metadata": str(coordinate_path) if coordinates else None,
                "auxiliary_coordinate_convention": "native variation constants; velocity scaling is in Phi; auxiliary units m",
                "initial_state_recovered_through_deterministic_conditional": True,
                "physical_map": "native_phi_times_variation_constants",
                "group_removed_energy": trailer["group_removed_energy"]}
    receipts["dynamic_observation_transport"] = transport
    return graph, receipts
