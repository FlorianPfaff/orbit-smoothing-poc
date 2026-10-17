"""Original-coordinate adapter for native constrained segment QR.

The native program receives original stochastic rows and exact equalities,
never a normal matrix or the dense rank certificate.  The latter is retained
only for the unchanged statistical rank rule and LM prediction diagnostics.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time

import numpy as np

from orbit_poc.numerics.optimizer import NumericalFailure, _dense_certify_rank


@dataclass(frozen=True)
class Variable:
    identifier: int
    kind: int  # 0: deterministic auxiliary, 1: original stochastic coordinate
    scale: float
    last_use_stage: int
    name: str = ""
    unit: str = ""


@dataclass(frozen=True)
class SparseRow:
    identifier: int
    stage: int
    rhs: float
    terms: tuple[tuple[int, float], ...]
    provenance: str = ""


@dataclass(frozen=True)
class EliminationGroup:
    stage: int
    deterministic: tuple[int, ...]
    stochastic: tuple[int, ...]


@dataclass(frozen=True)
class SegmentedGraph:
    variables: tuple[Variable, ...]
    equalities: tuple[SparseRow, ...]
    stochastic: tuple[SparseRow, ...]
    groups: tuple[EliminationGroup, ...]
    retained_ids: tuple[int, ...]
    linearization_sha256: str
    support_hash: str

    def validate(self):
        identifiers = [v.identifier for v in self.variables]
        if (not identifiers or identifiers != list(range(len(identifiers)))
                or any(type(i) is not int for i in identifiers)):
            raise NumericalFailure("invalid_segment_graph", "Variable IDs must be consecutive in native input order")
        known = set(identifiers)
        if (not self.retained_ids or len(set(self.retained_ids)) != len(self.retained_ids)
                or not set(self.retained_ids) <= known):
            raise NumericalFailure("invalid_segment_graph", "Invalid original-chart coordinate map")
        for variable in self.variables:
            if (variable.kind not in (0, 1) or not math.isfinite(variable.scale)
                    or variable.scale <= 0 or variable.last_use_stage < 0):
                raise NumericalFailure("invalid_segment_graph", "Invalid variable units, scale or ownership")
        stages = [g.stage for g in self.groups]
        if not stages or stages != sorted(set(stages)) or stages[0] < 0:
            raise NumericalFailure("invalid_segment_graph", "Elimination stages must be strictly increasing")
        last_use = {v.identifier: v.last_use_stage for v in self.variables}
        elimination_stage = {}
        for group in self.groups:
            for identifier in (*group.deterministic, *group.stochastic):
                if identifier not in known or identifier in elimination_stage:
                    raise NumericalFailure("invalid_segment_graph", "Missing or repeated elimination coordinate")
                if last_use[identifier] > group.stage:
                    raise NumericalFailure("premature_elimination", "Coordinate still has a future physical/prior dependency")
                elimination_stage[identifier] = group.stage
        if set(elimination_stage) != known:
            raise NumericalFailure("invalid_segment_graph", "Every coordinate needs an explicit elimination owner")
        seen = set()
        for ledger, rows in (("equality", self.equalities), ("stochastic", self.stochastic)):
            for row in rows:
                ids = [i for i, _ in row.terms]
                if (type(row.identifier) is not int or row.identifier < 0
                        or row.identifier in seen or row.stage < 0 or row.stage > stages[-1]
                        or not math.isfinite(row.rhs) or len(set(ids)) != len(ids)
                        or not set(ids) <= known
                        or any(not math.isfinite(v) for _, v in row.terms)):
                    raise NumericalFailure("invalid_segment_graph", f"Invalid {ledger} row identity/support")
                seen.add(row.identifier)
                for identifier, coefficient in row.terms:
                    if coefficient != 0 and (row.stage > last_use[identifier]
                                              or row.stage > elimination_stage[identifier]):
                        raise NumericalFailure("premature_elimination", "Row arrives after its coordinate was eliminated")
        return self

    def with_damping(self, point, damping):
        if not np.isfinite(damping) or damping < 0:
            raise ValueError("Damping must be finite and nonnegative")
        if not damping:
            return self
        next_id = max((r.identifier for r in (*self.equalities, *self.stochastic)), default=-1) + 1
        owners = {v.identifier: v.last_use_stage for v in self.variables}
        rows = tuple(SparseRow(next_id + j, owners[identifier], 0.,
                              ((identifier, math.sqrt(damping)/point.scales[j]),),
                              "optimization_damping_original_dynamic_only")
                     for j, identifier in enumerate(self.retained_ids) if point.dynamic[j])
        return replace(self, stochastic=self.stochastic + rows)


def linearization_digest(point):
    """Bind a lifted graph to one numerical point, not merely its fixed support."""
    digest = hashlib.sha256()
    for value in (point.factor, point.rhs, point.scales, point.dynamic):
        array = np.ascontiguousarray(value)
        digest.update(str((array.shape, array.dtype.str)).encode("ascii"))
        digest.update(array.tobytes())
    digest.update(str(point.effective_rows).encode("ascii"))
    digest.update(point.support_hash.encode("utf-8"))
    return digest.hexdigest()


def write_native_problem(stream, graph, queries=(), *, block_sizes=None):
    """Versioned, lossless text transport; no shell interpolation or JSON parser."""
    graph.validate()
    if block_sizes is not None:
        if (any(type(n) is not int or n <= 0 for n in block_sizes)
                or sum(block_sizes) != len(queries)):
            raise ValueError("Positive covariance block sizes must partition the query rows")
    stream.write("SEGMENTED_QR_V1\n" if block_sizes is None else "SEGMENTED_QR_BLOCKS_V1\n")
    stream.write(f"{len(graph.variables)} {len(graph.equalities)} {len(graph.stochastic)} "
                 f"{len(graph.groups)} {len(queries)}" +
                 ("\n" if block_sizes is None else f" {len(block_sizes)}\n"))
    for v in graph.variables:
        stream.write(f"{v.identifier} {v.kind} {v.scale:.17g} {v.last_use_stage}\n")
    for row in (*graph.equalities, *graph.stochastic):
        stream.write(f"{row.identifier} {row.stage} {row.rhs:.17g} {len(row.terms)}")
        for identifier, coefficient in row.terms:
            stream.write(f" {identifier} {coefficient:.17g}")
        stream.write("\n")
    for group in graph.groups:
        ids = (*group.deterministic, *group.stochastic)
        stream.write(f"{group.stage} {len(group.deterministic)} {len(group.stochastic)}")
        for identifier in ids:
            stream.write(f" {identifier}")
        stream.write("\n")
    for query in queries:
        stream.write(str(len(query)))
        for identifier, coefficient in query:
            stream.write(f" {identifier} {coefficient:.17g}")
        stream.write("\n")
    if block_sizes is not None:
        stream.write(" ".join(str(n) for n in block_sizes)+"\n")


class SegmentedLinearSystem:
    """Native constrained solve with the original dense rank certificate.

    The caller supplies a graph from the same native export generation.  No
    graph is manufactured from R, and there is no dense-solve fallback.
    """

    def __init__(self, graph, executable, directory, *, deadline=None):
        self.graph = graph.validate()
        self.executable = Path(executable).resolve()
        self.directory = Path(directory).resolve()
        self.deadline = deadline
        self.calls = []
        self.rank_seconds = 0.
        self.rank_metrics = {"seconds":0., "calls":0,
                             "scope":"Python original-chart undamped dense SVD; native profile QR/SVD remains in profile stage"}
        self._sequence = 0

    def validate(self, point):
        if (len(self.graph.retained_ids) != len(point.scales)
                or self.graph.support_hash != point.support_hash
                or self.graph.linearization_sha256 != linearization_digest(point)):
            raise NumericalFailure("stale_segment_graph", "Lifted graph does not identify this exact native linearization")
        variables = {v.identifier: v for v in self.graph.variables}
        for column, identifier in enumerate(self.graph.retained_ids):
            variable = variables[identifier]
            if variable.kind != 1 or variable.scale != point.scales[column]:
                raise NumericalFailure("invalid_segment_graph", "Original native scaling/coordinate identity changed")
        if any(row.rhs != 0. for row in self.graph.equalities):
            raise NumericalFailure("invalid_segment_graph", "A closed physical linearization requires homogeneous tangent equations")

    def certify_rank(self, point):
        self.validate(point)
        start = time.monotonic()
        try:
            return _dense_certify_rank(point)
        finally:
            elapsed = time.monotonic() - start
            self.rank_seconds += elapsed
            self.rank_metrics["seconds"] += elapsed
            self.rank_metrics["calls"] += 1

    def _run(self, graph, queries=(), *, block_sizes=None):
        if not self.executable.is_file():
            raise NumericalFailure("missing_segment_solver", "Pinned native segmented QR executable is absent")
        remaining = None if self.deadline is None else self.deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            raise NumericalFailure("timeout", "Per-fit deadline reached before segmented QR")
        self.directory.mkdir(parents=True, exist_ok=True)
        self._sequence += 1
        stem = self.directory / f"solve-{self._sequence:04d}"
        input_path, output_path = stem.with_suffix(".rows"), stem.with_suffix(".json")
        with input_path.open("x") as stream:
            write_native_problem(stream, graph, queries, block_sizes=block_sizes)
        started = time.monotonic()
        environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
        try:
            with input_path.open("r") as stream, output_path.open("x") as output:
                result = subprocess.run([str(self.executable)], stdin=stream, stdout=output,
                                        stderr=subprocess.PIPE, text=True, timeout=remaining,
                                        env=environment, check=False)
        except subprocess.TimeoutExpired as error:
            raise NumericalFailure("timeout", "Native segmented QR exhausted the per-fit deadline") from error
        stem.with_suffix(".stderr").write_text(result.stderr)
        record = {"input": str(input_path), "output": str(output_path),
                  "input_bytes": input_path.stat().st_size,
                  "elapsed_seconds": time.monotonic()-started, "returncode": result.returncode}
        self.calls.append(record)
        try:
            payload = json.loads(output_path.read_text())
        except (ValueError, OSError) as error:
            raise NumericalFailure("segmented_solver_failed", "Native QR did not produce valid diagnostics") from error
        if result.returncode or payload.get("status") != "complete":
            raise NumericalFailure(payload.get("reason", "segmented_solver_failed"),
                                   payload.get("message", result.stderr))
        equality_error = payload.get("equality_max_backward_error")
        if (type(equality_error) not in (int, float)
                or not math.isfinite(equality_error) or not 0 <= equality_error < 2e-12):
            record["validation_failure"] = "constraint_residual_inconsistent"
            raise NumericalFailure("constraint_residual_inconsistent",
                                   "Native exact-equation backward error must be below 2e-12")
        record.update({key: payload[key] for key in (
            "max_front_rows", "max_front_columns", "residual_energy",
            "orthogonal_residual_energy", "equality_max_backward_error") if key in payload})
        record["factor_nonzeros"] = sum(int(np.count_nonzero(c["R"]))+int(np.count_nonzero(c["S"]))
                                         for c in payload.get("conditionals", []))
        record["conditional_count"] = len(payload.get("conditionals", []))
        record["output_bytes"] = output_path.stat().st_size
        return payload

    def proposal(self, point, damping=0.):
        self.certify_rank(point)
        result = self._run(self.graph.with_damping(point, damping))
        values = np.asarray(result["step"], dtype=float)
        identifiers = result.get("variable_ids", [v.identifier for v in self.graph.variables])
        if values.shape != (len(identifiers),) or not np.isfinite(values).all():
            raise NumericalFailure("segmented_solver_failed", "Native correction is invalid")
        mapped = dict(zip(identifiers, values))
        step = np.array([mapped[i] for i in self.graph.retained_ids])
        scaled = step / point.scales
        change = point.factor @ scaled
        predicted = float(point.rhs @ change - .5 * (change @ change))
        gradient = float(np.max(np.abs(point.factor.T @ point.rhs)) /
                         max(1., np.sqrt(2 * point.objective)))
        return step, predicted, gradient

    def selected_covariance(self, point, design):
        self.certify_rank(point)
        design = np.asarray(design, dtype=float)
        if design.ndim != 2 or design.shape[1] != len(point.scales) or not np.isfinite(design).all():
            raise ValueError("Finite requested design with one column per original retained parameter required")
        queries = [tuple((identifier, float(value)) for identifier, value in zip(self.graph.retained_ids, row)
                         if value != 0.) for row in design]
        result = self._run(self.graph, queries)  # Never append optimization damping.
        covariance = np.asarray(result["covariance"], dtype=float)
        if covariance.shape != (len(design), len(design)) or not np.isfinite(covariance).all():
            raise NumericalFailure("invalid_covariance", "Invalid selected native conditional covariance")
        return covariance

    def covariance_blocks(self, point, blocks):
        """Selected native-coordinate query blocks, including lifted grid states.

        Each block gets its own conditional adjoint sweep; no all-epoch dense
        covariance is formed. A joint block retains cross-segment covariance.
        """
        self.certify_rank(point)
        blocks = tuple(tuple(block) for block in blocks)
        if not blocks or any(not block for block in blocks):
            raise ValueError("At least one nonempty covariance query block is required")
        queries = [query for block in blocks for query in block]
        result = self._run(self.graph, queries, block_sizes=[len(block) for block in blocks])
        records = result.get("covariance_blocks")
        if result.get("covariance") != [] or not isinstance(records,list) or len(records) != len(blocks):
            raise NumericalFailure("invalid_covariance", "Native selected block covariance is incomplete")
        covariance, offset = [], 0
        for record, block in zip(records, blocks):
            values = np.asarray(record.get("covariance"),dtype=float)
            if (record.get("query_start") != offset or record.get("query_count") != len(block)
                    or values.shape != (len(block),len(block)) or not np.isfinite(values).all()):
                raise NumericalFailure("invalid_covariance", "Native covariance block identity changed")
            covariance.append(values)
            offset += len(block)
        return covariance
