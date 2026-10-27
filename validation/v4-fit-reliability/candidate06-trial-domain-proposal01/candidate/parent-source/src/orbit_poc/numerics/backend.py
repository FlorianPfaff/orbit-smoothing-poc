"""Fixed-physical-parameter GROOPS trials for the opt-in numerical benchmark.

Every evaluated point has a private directory. Force integration starts in a
fresh native process and closes in both position and velocity before GNSS
nuisances are profiled. Only the optimizer can install an accepted point.
"""
from copy import deepcopy
import csv
from dataclasses import dataclass
from pathlib import Path
import struct
import time
import xml.etree.ElementTree as ET

import numpy as np

from orbit_poc.comparison import backend as native
from orbit_poc.comparison.groops_config import build_fit_configs
from orbit_poc.comparison.initialization import _field, _standalone
from orbit_poc.comparison.protocol import artifact_record, canonical_hash, file_hash, read_json, write_json
from .config import Controls
from .optimizer import Linearization, NumericalFailure, certify_rank, minimize, proposal
from .retention import (compact_closed_closures, compact_closed_proposal,
                        compress_closed_row_provenance, discard_inactive_factors)


def read_factor(path):
    """Read the native little-endian, row-major matrix format without guessing."""
    with Path(path).open("rb") as stream:
        header = stream.read(16)
        if len(header) != 16:
            raise ValueError("Truncated native QR matrix header")
        rows, columns = struct.unpack("<QQ", header)
        if rows * columns > 100_000_000:
            raise ValueError("Native QR matrix exceeds the worker memory budget")
        values = np.frombuffer(stream.read(), dtype="<f8")
    if len(values) != rows * columns or not np.isfinite(values).all():
        raise ValueError("Invalid native QR matrix payload")
    return values.reshape(rows, columns).copy()


def write_matrix(path, values):
    values = np.asarray(values, dtype=float)
    if values.ndim == 1:
        values = values[:, None]
    if values.ndim != 2 or not np.isfinite(values).all():
        raise ValueError("Native matrix must be finite and two-dimensional")
    with Path(path).open("w") as stream:
        stream.write("groops matrix version=20200123\nMatrix( %d x %d )\n" % values.shape)
        np.savetxt(stream, values, fmt="%.17e")


def parameter_support(path):
    """Retain native coordinate identities while excluding changing QR scales."""
    with Path(path).open(newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        names = reader.fieldnames
        if (not names or len(set(names)) != len(names) or
                not {"index", "name", "dynamic", "unit", "scale"}.issubset(names)):
            raise ValueError("Invalid native parameter metadata header")
        rows = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Malformed native parameter metadata row")
            rows.append({key: value for key, value in row.items() if key != "scale"})
    return rows


def native_failure_reason(log, execution=None):
    """Separate failed numerical proposals from fatal native/runtime errors."""
    if execution and execution["timed_out"]:
        return "timeout"
    log = log.casefold()
    if "rank_deficient" in log or "rank deficient" in log:
        return "rank_deficient"
    if "unresolved" in log:
        return "unresolved_rank"
    if any(text in log for text in ("nonfinite tangent right-hand side", "nonfinite position force jacobian",
                                   "nonfinite velocity force jacobian", "nonfinite tangent integral",
                                   "nonfinite scaled tangent norm", "singular local six-state tangent preconditioner",
                                   "six-state tangent krylov breakdown",
                                   "six-state tangent did not meet its true residual tolerance")):
        return "closure_failed"
    if any(text in log for text in ("nuisance profiling exhausted", "nonfinite nuisance update",
                                   "nonfinite nuisance stationarity", "nuisance line search rejected every trial",
                                   "fresh nuisance factor did not confirm empirical resolution status",
                                   "fresh full nuisance correction did not confirm strict conditional convergence")):
        return "nuisance_failure"
    return "native_failure"


def nuisance_profile_resolution(receipt, *, covariance=False):
    """Validate native profiling status without converting a floor into convergence."""
    strict = receipt.get("nuisance_converged") is True
    limited = receipt.get("nuisance_floor_limited") is True
    if strict and not limited:
        if receipt.get("conditional_nuisance_qr") is True:
            threshold = receipt.get("threshold_m")
            change = receipt.get("fresh_full_nuisance_update_m")
            history = receipt.get("history")
            if (type(threshold) not in (int, float) or threshold != 1e-8
                    or receipt.get("fresh_full_nuisance_confirmed") is not True
                    or type(change) not in (int, float) or not np.isfinite(change) or not 0 <= change < threshold
                    or receipt.get("required_consecutive_small_updates") != 2
                    or not isinstance(history, list) or len(history) < 2
                    or any(not isinstance(row, dict) or type(row.get("maximum_update_m")) not in (int, float)
                           or not np.isfinite(row["maximum_update_m"]) or not 0 <= row["maximum_update_m"] < threshold
                           for row in history[-2:])):
                raise NumericalFailure("nuisance_failure", "Conditional nuisance profile lacks strict fresh full-system confirmation")
        return 0., False
    if limited and not strict and not covariance:
        resolution = receipt.get("nuisance_objective_resolution")
        potential = receipt.get("nuisance_predicted_reduction")
        audits = receipt.get("nuisance_floor_audit")
        complete_audits = (isinstance(audits, list) and len(audits) == 4
            and all(isinstance(audit, dict) for audit in audits)
            and all(sum(audit.get("kind") == "equivalent_arithmetic"
                        and type(audit.get("mode")) is int and audit["mode"] == mode
                        for audit in audits) == 1 for mode in (1, 2, 3))
            and sum(audit.get("kind") == "two_amplitude_symmetric_nuisance_probe"
                    and isinstance(audit.get("probes"), list) and len(audit["probes"]) == 4
                    for audit in audits) == 1)
        if complete_audits:
            probe = next(audit for audit in audits if audit["kind"] == "two_amplitude_symmetric_nuisance_probe")
            for key in ("empirical_quadratic_potential", "half_empirical_quadratic_potential",
                        "empirical_quadratic_potential_with_allowance", "half_empirical_quadratic_potential_with_allowance"):
                value = probe.get(key)
                if (not isinstance(value, (int, float)) or isinstance(value, bool)
                        or not np.isfinite(value) or not isinstance(resolution, (int, float))
                        or not 0 < value <= resolution):
                    complete_audits = False
                    break
        if (all(isinstance(value, (int, float)) and not isinstance(value, bool)
                and np.isfinite(value) and value > 0 for value in (resolution, potential))
                and potential <= resolution and complete_audits
                and receipt.get("nuisance_floor_policy") == "empirical_equivalent_arithmetic_and_symmetric_probes_v1"
                and all(isinstance(audit, dict) and audit.get("success") is True
                        and audit.get("support_unchanged") is True for audit in audits)):
            return float(resolution), True
    raise NumericalFailure("nuisance_failure", "Native nuisance profile lacks strict stationarity or a valid measured resolution diagnosis")


def require_full_native_factor(info, diagnostics):
    """Conditional inner factors never establish physical rank or covariance."""
    columns = info.get("columns")
    local = info.get("local_global_indices")
    retained = info.get("retained_global_indices")
    if (info.get("schema") != "orbit-poc-qr-factor-v1"
            or diagnostics.get("schema") != "orbit-poc-native-qr-v1"
            or diagnostics.get("rank_status") != "full"
            or type(diagnostics.get("lambda")) not in (int, float) or diagnostics["lambda"] != 0
            or type(columns) is not int or columns <= 0 or type(info.get("rows")) is not int or info["rows"] != columns
            or type(diagnostics.get("rank")) is not int or diagnostics["rank"] != columns
            or type(diagnostics.get("retained_parameters")) is not int or diagnostics["retained_parameters"] != columns
            or not isinstance(local, list) or any(type(x) is not int for x in local)
            or local != list(range(len(local)))
            or not isinstance(retained, list) or any(type(x) is not int for x in retained)
            or retained != list(range(len(local), len(local) + columns))
            or info.get("full_rank_certificate") is False or info.get("covariance_authority") is False):
        raise NumericalFailure("missing_factor", "A fresh full original-coordinate undamped QR certificate is required")


@dataclass(frozen=True)
class PhysicalState:
    initial: np.ndarray
    force: np.ndarray
    reference_orbit: Path


class NativeModel:
    def __init__(self, job, root):
        self.job, self.root = job, Path(root).resolve()
        self.binary = native._binary(job)
        self.prepared = native._preparation(job)
        self.density = job["method"] == "groops_log_drag_ou"
        self.controls = Controls(**job.get("numerical_controls", {}))
        self.start = time.monotonic()
        self.executions, self.propagations, self.sequence = [], 0, 0
        self.protected_factor = None
        self.derivatives = ("legacy_v3" if job["numerics_profile"] == "qr_lm_legacy_jacobian"
                            else "synthetic_complete_v1" if job["stage"] == "synthetic"
                            else "flight_gravity_drag_v1")
        self.input_support = canonical_hash({key: job[key] for key in (
            "force_model_hash", "measurement_model_hash", "preprocessing_hash", "mask_hash")})

    def accept(self, point):
        """Protect the installed factor until a verified successor is accepted."""
        self.protected_factor = Path(point.metadata["factor_prefix"] + ".R.bin")
        discard_inactive_factors(self.root, protected=[self.protected_factor])

    def execute(self, tree, folder, label, environment=None):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        path = native._save_xml(tree, folder / (label + ".xml"))
        remaining = self.controls.wall_time_seconds - (time.monotonic() - self.start)
        if remaining <= 0:
            raise NumericalFailure("timeout", "Per-fit wall time exhausted")
        try:
            result = native.run_native(self.binary, path, folder, label, timeout=remaining,
                                       environment_overrides=environment)
            self.executions.append(result)
        except native.NativeExecutionError as error:
            if error.execution:
                self.executions.append(error.execution)
            log = (folder / (label + ".log")).read_text(errors="replace")
            reason = native_failure_reason(log, error.execution)
            raise NumericalFailure(reason, str(error)) from error
        return path

    def initial_state(self):
        folder = self.root / "initial-input"
        path = native._file_conversion(self.prepared["native_paths"]["orbit"], folder / "orbit.txt",
                                       folder / "convert.xml")
        self.execute(ET.parse(path).getroot(), folder, "convert")
        _, states = native._orbit(folder / "orbit.txt")
        duration = self.prepared.get("duration_hours", 24) * 3600
        count = (round(duration / self.job["parameters"].get("knot_seconds", 60)) + 1
                 if self.density else 3 * (int(np.ceil(duration / self.job["parameters"]["interval_seconds"])) - 1))
        return PhysicalState(states[0].copy(), np.zeros(count), Path(self.prepared["native_paths"]["orbit"]))

    def _evaluation(self, config, source, variable, orbit, vector, *, initial=None,
                    reference=None, initial_design=None):
        node = ET.Element("OrbitPocEvaluateVariational")
        for name, value in (("inputfileVariational", variable), ("outputfileOrbit", orbit),
                            ("inputfileParameters", vector), ("inputfileInitialState", initial),
                            ("outputfileParameters", reference), ("outputfileInitialStateDesign", initial_design)):
            if value is not None:
                _field(node, name, value)
        processing = ET.parse(config["configs"]["estimate"]).find(".//GnssProcessing/parametrization/leoDynamicOrbits")
        propagation = source.find(".//PreprocessingVariationalEquation")
        for name in ("parametrizationAcceleration", "stochasticPulse", "integrationDegree", "interpolationDegree"):
            item = processing.find(name)
            if item is not None:
                node.append(deepcopy(item))
        node.append(deepcopy(propagation.find("ephemerides")))
        conversion = ET.Element("FileConvert")
        _field(conversion, "inputfile", orbit)
        _field(conversion, "outputfile", Path(orbit).with_suffix(".txt"))
        return [node, conversion]

    def _close(self, state, config, folder, tighter):
        source = ET.parse(config["configs"]["variational"]).getroot()
        template = source.find(".//PreprocessingVariationalEquation")
        if template is None:
            raise ValueError("Missing native physical propagation")
        initial = folder / "physical_initial.txt"
        vector = folder / "fixed_force.txt"
        write_matrix(initial, state.initial)
        write_matrix(vector, np.r_[np.zeros_like(state.force) if self.density else state.force, np.zeros(6)])
        previous, previous_epochs = None, None
        reference_orbit = state.reference_orbit
        history = []
        tolerance = .1 if tighter else 1.
        for index in range(1, 17):
            iteration = folder / f"closure-{index:02d}"
            iteration.mkdir(parents=True)
            variable, orbit = iteration / "variational.dat", iteration / "orbit.dat"
            reference, design = iteration / "reference.txt", iteration / "initial_design.txt"
            propagation = deepcopy(template)
            _field(propagation, "inputfileOrbit", reference_orbit)
            _field(propagation, "outputfileVariational", variable)
            _field(propagation, "orbitPocDerivativeProfile", self.derivatives)
            if self.derivatives != "legacy_v3":
                _field(propagation, "orbitPocDerivativeDiagnostics", iteration / "derivatives.json")
            programs = [propagation, *self._evaluation(config, source, variable, orbit, vector,
                        initial=initial, reference=reference, initial_design=design)]
            self.execute(_standalone(source, programs, config["date"]), iteration, "propagate")
            self.propagations += 1
            epochs, states = native._orbit(orbit.with_suffix(".txt"))
            # The complete text is now in memory. Preserve it losslessly and
            # retain only this completed binary pair for subsequent closure,
            # proposals and covariance; partial native outputs stay untouched.
            compact_closed_closures(folder, iteration)
            if previous is not None:
                if not np.array_equal(epochs, previous_epochs):
                    raise NumericalFailure("changed_support", "Trajectory epoch grid changed during closure")
                difference = states - previous
                dr = float(np.max(np.linalg.norm(difference[:, :3], axis=1)))
                dv = float(np.max(np.linalg.norm(difference[:, 3:], axis=1)))
                history.append({"iteration": index, "position_change_m": dr, "velocity_change_m_s": dv})
                if dr < 2e-6 * tolerance and dv < 3e-9 * tolerance:
                    write_json(folder / "closure.json", {"converged": True, "tighter": tighter,
                        "iterations": history, "force_state_reset": "fresh native process at every iteration"})
                    config["native_paths"]["variational"] = str(variable)
                    return orbit, variable, reference, design, epochs, states
            previous, previous_epochs, reference_orbit = states, epochs, orbit
        write_json(folder / "closure.json", {"converged": False, "iterations": history})
        raise NumericalFailure("closure_failed", "Fixed physical trajectory failed position/velocity closure")

    def evaluate(self, state, label, tighter=False, *, covariance=False):
        self.sequence += 1
        folder = self.root / f"point-{self.sequence:03d}-{label}"
        folder.mkdir(parents=True)
        private = folder / "native"
        native._private_data(self.prepared, private)
        config = build_fit_configs(self.prepared, private, self.job["method"], self.job["parameters"])
        # Standalone processing bypasses the template's directory-creation
        # programs; audit exporters use ordinary streams and need their parent.
        for output in config["result_paths"].values():
            Path(output).parent.mkdir(parents=True, exist_ok=True)
        pulse_reference = folder / "full_pulses_um_s.txt"
        if self.density:
            density_file = private / "log_density.txt"
            epochs = [line.split()[0] for line in density_file.read_text().splitlines() if line.strip()]
            native._write_density_values(density_file, epochs, state.force)
        else:
            np.savetxt(pulse_reference, state.force, fmt="%.17e")
        orbit, variable, reference, design, epochs, states = self._close(state, config, folder, tighter)
        source = ET.parse(config["configs"]["estimate"]).getroot()
        processing = deepcopy(source.find(".//GnssProcessing"))
        exports = [deepcopy(step) for step in processing.findall("processingStep")
                   if step.find("writeResiduals") is not None or step.find("writeAprioriSolution") is not None]
        dynamic = processing.find("parametrization/leoDynamicOrbits")
        _field(dynamic, "inputfileVariational", variable)
        _field(dynamic, "inputfileNumericsReferenceParameters", reference)
        for step in list(processing.findall("processingStep")):
            processing.remove(step)
        prefix = folder / "qr"
        profile = ET.SubElement(ET.SubElement(processing, "processingStep"), "orbitPocNumerics")
        _field(profile, "outputfilePrefix", prefix)
        if not self.density:
            _field(profile, "inputfilePulseReference", pulse_reference)
        if covariance:
            ET.SubElement(ET.SubElement(processing, "processingStep"), "computeCovarianceMatrix")
        else:
            for tag in ("outputfileCovariance", "outputfileParameterCovariance", "outputfileCovarianceObservationEpochs"):
                for node in list(dynamic.findall(tag)):
                    dynamic.remove(node)
        ET.SubElement(ET.SubElement(processing, "processingStep"), "writeResults")
        if covariance:
            for export in exports:
                processing.append(export)
        environment = {"ORBIT_POC_NUMERICS_QR_PREFIX": str(prefix),
                       "ORBIT_POC_NUMERICS_SOLVER": "scaled_qr_v1",
                       "ORBIT_POC_NUMERICS_MODE": "profile_step", "ORBIT_POC_NUMERICS_LAMBDA": "0",
                       "ORBIT_POC_NUMERICS_KEEP_INTERMEDIATE_FACTORS": "0",
                       "ORBIT_POC_NUMERICS_COMPRESS_ROW_PROVENANCE": "1",
                       "ORBIT_POC_NUMERICS_SPOOL_DIRECTORY": str(self.root / "row-spool")}
        (self.root / "row-spool").mkdir(exist_ok=True)
        if not self.density:
            environment["ORBIT_POC_NUMERICS_PULSE_REFERENCE"] = str(pulse_reference)
        try:
            configuration = self.execute(_standalone(source, [processing], config["date"]), folder, "profile", environment)
        finally:
            # The native process has exited, including on a rejected/failed
            # proposal. Preserve every row losslessly before removing its
            # uncompressed copy; keep the accepted and newest native factors.
            compress_closed_row_provenance(folder)
            discard_inactive_factors(self.root, protected=([self.protected_factor] if self.protected_factor else []))
        receipt = read_json(str(prefix) + ".profile.json")
        resolution, floor_limited = nuisance_profile_resolution(receipt, covariance=covariance)
        factors = sorted(folder.glob("qr.*.factor.json"), key=lambda p: int(p.name.split(".")[1]))
        if not factors:
            raise NumericalFailure("missing_factor", "No original-row native QR factor was exported")
        base = str(factors[-1]).removesuffix(".factor.json")
        info, diagnostics, cost = (read_json(base + suffix) for suffix in (
            ".factor.json", ".diagnostics.json", ".profile.json"))
        require_full_native_factor(info, diagnostics)
        # Parameter scales change with the linearization and are not support.
        support = canonical_hash({"input": self.input_support,
            "audit": file_hash(config["result_paths"]["preprocessing_audit"]),
            "parameters": parameter_support(base + ".parameters.tsv")})
        mask = np.asarray(info["dynamic"], dtype=bool)
        if int(mask.sum()) != len(state.force) + 6:
            raise NumericalFailure("parameter_order", "Retained dynamic columns do not match the physical model")
        result = Linearization(read_factor(base + ".R.bin"), read_factor(base + ".rhs.bin").ravel(),
            np.asarray(info["scales"]), mask, int(diagnostics["reduced_rows"]), float(cost["direct_cost"]),
            float(info["orthogonal_energy"]), support,
            PhysicalState(state.initial.copy(), state.force.copy(), orbit),
            objective_floor=resolution,
            metadata={"folder": str(folder), "config": config, "configuration": str(configuration),
                      "source": str(config["configs"]["variational"]), "reference": str(reference),
                      "design": str(design), "epochs": epochs, "states": states,
                      "nuisance_floor_limited": floor_limited,
                      "nuisance_objective_resolution": resolution,
                      "factor_prefix": base, "diagnostics": diagnostics})
        return result.validate()

    def trial(self, point, step):
        delta = np.asarray(step)[point.dynamic]
        design = native.read_native_table(point.metadata["design"])
        if design.shape != (6, len(delta)):
            raise NumericalFailure("parameter_order", "Physical initial-state design shape changed")
        initial = point.state.initial + design @ delta
        force = point.state.force + delta[:-6]
        folder = Path(point.metadata["folder"]) / f"proposal-{len(list(Path(point.metadata['folder']).glob('proposal-*'))):03d}"
        folder.mkdir()
        vector = folder / "parameters.txt"
        write_matrix(vector, native.read_native_table(point.metadata["reference"]).ravel() + delta)
        config = point.metadata["config"]
        source = ET.parse(point.metadata["source"]).getroot()
        orbit = folder / "orbit.dat"
        programs = self._evaluation(config, source, config["native_paths"]["variational"], orbit, vector)
        self.execute(_standalone(source, programs, config["date"]), folder, "linearized-proposal")
        epochs, states = native._orbit(orbit.with_suffix(".txt"))
        if not np.array_equal(epochs, point.metadata["epochs"]):
            raise NumericalFailure("changed_support", "Proposal changed the trajectory epoch grid")
        metrics = {"position_change_m": float(np.max(np.linalg.norm(states[:, :3]-point.metadata["states"][:, :3], axis=1))),
                   "density_update": float(np.max(np.abs(delta[:-6]), initial=0)) if self.density else 0.,
                   "pulse_update_m_s": float(np.max(np.abs(delta[:-6]), initial=0))*1e-6 if not self.density else 0.}
        compact_closed_proposal(folder, metrics)
        return PhysicalState(initial, force, point.state.reference_orbit), metrics

    def finish(self, point):
        final = self.evaluate(point.state, "final-covariance", tighter=True, covariance=True)
        if final.support_hash != point.support_hash:
            raise NumericalFailure("changed_support", "Final covariance changed observation support")
        certify_rank(final)
        step, _, gradient = proposal(final)
        _, metrics = self.trial(final, step)
        if (metrics["position_change_m"] >= self.controls.maximum_position_change_m or
                metrics["density_update"] >= self.controls.maximum_density_update or
                metrics["pulse_update_m_s"] >= self.controls.maximum_pulse_update_m_s or
                gradient >= self.controls.normalized_gradient_tolerance):
            raise NumericalFailure("stale_covariance", "Fresh final undamped correction failed convergence")
        outputs = final.metadata["config"]["result_paths"]
        mjd, states = native._orbit(outputs["orbit"])
        covariance, invalid = native._covariance(outputs["covariance"], mjd)
        prediction_mjd = native.read_native_table(outputs["covariance_observations"], 37)[:, 0]
        prediction_covariance, invalid_prediction = native._covariance(outputs["covariance_observations"], prediction_mjd)
        if invalid or invalid_prediction:
            raise NumericalFailure("invalid_covariance", "Native selected QR covariance is not positive definite")
        estimate = self.root / "fit.npz"
        np.savez_compressed(estimate, times=(mjd-mjd[0])*86400., mjd=mjd, states=states, covariance=covariance,
                            prediction_mjd=prediction_mjd, prediction_covariance=prediction_covariance)
        physical = self.root / "physical_parameters.json"
        write_json(physical, {"initial_state_si": final.state.initial.tolist(), "force": final.state.force.tolist(),
            "force_units": "log density" if self.density else "um/s", "objective": final.objective,
            "derivative_profile": self.derivatives, "covariance_scope": "local Gaussian, selected hyperparameters fixed"})
        artifacts = [artifact_record("state_estimate", estimate), artifact_record("physical_parameters", physical),
            artifact_record("native_nuisance_profile", Path(final.metadata["folder"]) / "qr.profile.json"),
            artifact_record("native_initial_state_design", final.metadata["design"]),
            artifact_record("native_reference_parameters", final.metadata["reference"]),
            artifact_record("native_fit_configuration", final.metadata["configuration"]),
            artifact_record("native_variational", final.metadata["config"]["native_paths"]["variational"])]
        for suffix, role in ((".R.bin", "native_qr_factor"), (".rhs.bin", "native_qr_rhs"),
                             (".factor.json", "native_qr_coordinates"), (".diagnostics.json", "native_qr_diagnostics"),
                             (".profile.json", "native_objective"), (".parameters.tsv", "native_qr_parameters"),
                             (".rows.tsv.gz", "native_qr_row_provenance"),
                             (".rows.tsv.compression.json", "native_qr_row_compression_receipt")):
            artifacts.append(artifact_record(role, final.metadata["factor_prefix"] + suffix))
        for key, role in (("orbit_native", "estimated_orbit_native"), ("parameter_covariance", "native_parameter_covariance"),
                          ("parameters", "native_parameters"), ("preprocessing_audit", "native_preprocessing_audit"),
                          ("phase_recovery", "phase_recovery"), ("apriori_solution", "full_native_solution"),
                          ("parameter_names", "native_parameter_names")):
            artifacts.append(artifact_record(role, outputs[key]))
        return {"objective": final.objective, "covariance_valid": True, "artifacts": artifacts,
                "preprocessing_audit_sha256": file_hash(outputs["preprocessing_audit"]),
                "rank": final.metadata["diagnostics"]}


def fit_job(job, job_dir):
    if job.get("numerics_profile") not in ("qr_lm_legacy_jacobian", "qr_lm_staged_jacobian"):
        raise ValueError("New native backend requires an explicit registered QR/LM profile")
    if job.get("method") not in ("groops_pulses", "groops_log_drag_ou"):
        raise ValueError("QR/LM supports only the two primary float methods")
    if any(key in job for key in ("evaluation_inputs", "calibration_inputs", "truth", "reference_orbit")):
        raise ValueError("Fitting accepts blind estimation inputs only")
    root = Path(job_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    model = NativeModel(job, root)
    try:
        result = minimize(model, model.initial_state(), controls=model.controls,
                          started_at=model.start,
                          emit=lambda value: write_json(root / "iterations.json", value))
    except NumericalFailure as error:
        result = {"status": error.reason, "converged": False, "covariance_valid": False, "error": str(error)}
    final = result.pop("result", {})
    runtime = {**result, "execution": model.executions, "propagation_count": model.propagations,
        "elapsed_seconds": time.monotonic()-model.start,
        "peak_rss_bytes": max((x["peak_rss_bytes"] for x in model.executions), default=0),
        "peak_rss_scope": "maximum individual native parent-process RSS; excludes nuisance trial children; benchmark harness records recursive process-tree RSS",
        "native_binary_sha256": file_hash(model.binary), "source_hash": job["source_hash"],
        "row_storage": {"spool_directory": str(root / "row-spool"),
                        "keep_intermediate_factors": False, "keep_iteration_diagnostics": True,
                        "closed_row_provenance": "verified lossless gzip",
                        "closure_trajectories": "verified lossless gzip; current completed orbit/variational pair retained; superseded binary bytes hashed before removal",
                        "proposal_trajectories": "verified lossless gzip and correction metrics; completed unused binary bytes hashed before removal",
                        "point_factors": "accepted factor plus newest diagnostic factor; superseded bytes hashed before removal"},
        "derivative_profile": model.derivatives}
    write_json(root / "native_runtime.json", runtime)
    write_json(root / "iterations.json", result)
    retention_artifacts = ([artifact_record("online_factor_retention", root / "factor-retention.json")]
                           if (root / "factor-retention.json").exists() else [])
    retention_artifacts.extend(artifact_record("online_closure_retention", path)
                               for path in sorted(root.glob("point-*/closure-retention.json")))
    retention_artifacts.extend(artifact_record("online_proposal_retention", path)
                               for path in sorted(root.glob("point-*/proposal-*/proposal-retention.json")))
    numerical_status = result["status"]
    status = numerical_status if numerical_status in ("complete", "timeout", "unresolved_rank", "invalid_covariance") else "failed"
    return {**result, **final, "status": status, "numerical_status": numerical_status,
        "method": job["method"], "covariance_valid": bool(final.get("covariance_valid")),
        "covariance_scope": "marginalized", "parameter_blocks": ["initial_state", "log_density" if model.density else "pulses",
            "receiver_clock", "ionosphere", "signal_bias", "float_ambiguities"],
        "runtime": runtime, "numerical_diagnostics": runtime,
        "elapsed_seconds": runtime["elapsed_seconds"], "peak_rss_bytes": runtime["peak_rss_bytes"],
        "peak_rss_scope": runtime["peak_rss_scope"],
        "metadata": {"reference_inputs_used": False, "derivative_profile": model.derivatives,
            "nuisance_profile_policy": "Strict fresh nuisance stationarity required for convergence/covariance; empirically resolution-limited profiles permit only resolved nonfinal physical progress",
            "gnss_numerical_policy": {
                "name": "relative_query_clock_range_v1",
                "time_queries": "Explicit sub-Time polynomial offsets for receiver state/design and transmitter light time",
                "range_residual": "High/low interpolated receiver/transmitter coordinates and extended-precision corrected geometry/clock arithmetic before residual rounding",
                "receiver_scope": "Inertial LEO receivers; Earth-fixed receivers explicitly unsupported",
                "remaining_representation_limits": ["Other metadata and attitude consumers retain native Time",
                    "Orbit archives and derivative matrices retain native double precision"]},
            "states_frame": "CRF", "states_units": "m,m/s", "ambiguity_policy": "jointly estimated float ambiguities",
            "covariance_scope": "local Gaussian; fixed selected hyperparameters; no damping",
            "ionosphere_policy": "Per-observation STEC locally eliminated; independent epoch VTEC and receiver clocks jointly eliminated by QR; all conditionally recovered; nonlinear STEC terms reprofiled",
            "omitted_flight_derivatives": (["thermal-history state sensitivities", "force gradients other than gravity and drag",
                "atmospheric event-time sensitivities"] if model.derivatives == "flight_gravity_drag_v1" else [])},
        "source_hash": job["source_hash"], "native_binary_sha256": file_hash(model.binary),
        "artifacts": [*final.get("artifacts", []), *retention_artifacts,
                      artifact_record("native_runtime", root / "native_runtime.json")],
        **{key: job[key] for key in ("force_model_hash", "measurement_model_hash", "preprocessing_hash", "mask_hash")}}
