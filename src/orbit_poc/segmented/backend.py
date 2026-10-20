"""Opt-in v4 adapter around the corrected chronological objective/LM path.

Only the linear solve representation changes. Every nonlinear physical trial
and nuisance profile remains the corrected v3.1 evaluation, in a fresh native
process. Neither reference truth nor a previous segment's nominal orbit enters
the statistical problem.
"""
from dataclasses import replace
from pathlib import Path
import time
import xml.etree.ElementTree as ET

import numpy as np

from orbit_poc.comparison import backend as native
from orbit_poc.comparison.initialization import _field,_standalone
from orbit_poc.comparison.protocol import artifact_record,file_hash,write_json
from orbit_poc.numerics.backend import NativeModel
from orbit_poc.numerics.nuisance_warm_start import without_inherited_warm_environment
from orbit_poc.numerics.optimizer import DenseLinearSystem,NumericalFailure,certify_rank,minimize,proposal,selected_covariance
from .graph import build_graph
from .solver import SegmentedLinearSystem
from .diagnostics import (physical_queries,covariance_is_valid,prediction_artifacts,
                          covariance_pairs,selected_original_design)


class TimedDenseSystem(DenseLinearSystem):
    """The identical dense arithmetic with external wall-time accounting."""
    def __init__(self):
        self.metrics = {"rank_seconds":0.,"rank_calls":0,"proposal_seconds":0.,"proposal_calls":0,
            "scope":"Python dense adapter; native profiling QR/SVD remains in the profile stage"}

    def certify_rank(self,point):
        started = time.monotonic()
        try:
            return super().certify_rank(point)
        finally:
            self.metrics["rank_seconds"] += time.monotonic()-started
            self.metrics["rank_calls"] += 1

    def proposal(self,point,damping=0.):
        started = time.monotonic()
        try:
            return super().proposal(point,damping)
        finally:
            self.metrics["proposal_seconds"] += time.monotonic()-started
            self.metrics["proposal_calls"] += 1


class V4Model(NativeModel):
    def __init__(self,job,root):
        super().__init__(job,root)
        self.profile = job["segmented_profile"]
        self.segment_seconds = {"dense_corrected":None,"segmented_1h":3600,"segmented_4h":14400}[self.profile]
        self.segmented = self.segment_seconds is not None
        self.linear_diagnostics = []
        self.covariance_diagnostics = {}
        self.final_correction = None
        self.solver = None
        if file_hash(self.binary) != job["expected_native_binary_sha256"]:
            raise ValueError("Native executable differs from the immutable benchmark")
        if self.segmented:
            pin = job.get("backend",{}).get("segmented_solver")
            if not isinstance(pin,dict) or not pin.get("path") or file_hash(pin["path"]) != pin.get("sha256"):
                raise ValueError("Segmented QR requires its pinned standalone executable")
            self.solver = Path(pin["path"]).resolve()

    def _evaluation(self,config,source,variable,orbit,vector,*,initial=None,reference=None,initial_design=None):
        programs = super()._evaluation(config,source,variable,orbit,vector,initial=initial,
                                      reference=reference,initial_design=initial_design)
        if self.segmented and initial_design is not None:
            _field(programs[0],"outputfileSegmentedDesign",Path(initial_design).parent/"local-design.jsonl")
        return programs

    def execute(self,tree,folder,label,environment=None):
        if self.segmented and label == "profile":
            environment = dict(environment or {},ORBIT_POC_SEGMENTED_ROWS="1")
            processing = tree.find(".//GnssProcessing")
            covariance = processing.find("processingStep/computeCovarianceMatrix") is not None
            if covariance:
                environment["ORBIT_POC_SEGMENTED_COVARIANCE_QUERIES"] = "1"
                for node in list(processing.findall("processingStep")):
                    if node.find("computeCovarianceMatrix") is not None:
                        processing.remove(node)
                dynamic = processing.find("parametrization/leoDynamicOrbits")
                for tag in ("outputfileCovariance","outputfileParameterCovariance","outputfileCovarianceObservationEpochs"):
                    for node in list(dynamic.findall(tag)):
                        dynamic.remove(node)
        return super().execute(tree,folder,label,environment)

    def evaluate(self,state,label,tighter=False,*,covariance=False):
        point = super().evaluate(state,label,tighter,covariance=covariance)
        if not self.segmented:
            system = TimedDenseSystem()
            self.linear_diagnostics.append({"point":label,"dense":system.metrics})
            return replace(point,linear_system=system).validate()
        start = time.monotonic()
        base = point.metadata["factor_prefix"]
        design = Path(point.metadata["design"]).parent/"local-design.jsonl"
        graph,receipt = build_graph(point,design,base+".segmented_rows.jsonl",
                                   base+".segmented_observations.jsonl",segment_seconds=self.segment_seconds)
        receipt["assembly_seconds"] = time.monotonic()-start
        receipt["factor_prefix"] = base
        receipt["design_export"] = artifact_record("segmented_design",design)
        graph_receipt = Path(point.metadata["folder"])/"segmented-graph.json"
        write_json(graph_receipt,receipt)
        system = SegmentedLinearSystem(graph,self.solver,Path(point.metadata["folder"])/"segmented-solves",
                                       deadline=self.start+self.controls.wall_time_seconds)
        # Keep metrics, not old graph objects, beyond a point's lifetime.
        self.linear_diagnostics.append({"point":label,"graph":artifact_record("segmented_graph",graph_receipt),
            "assembly_seconds":receipt["assembly_seconds"],"calls":system.calls,
            "rank_certification":system.rank_metrics,
            "original_columns":len(point.scales),"auxiliary_columns":receipt["auxiliary_columns"],
            "stochastic_rows":receipt["stochastic_rows"],"equality_rows":receipt["equality_rows"]})
        return replace(point,linear_system=system,
                       metadata={**point.metadata,"segmented_design":str(design),
                                 "segmented_graph_receipt":str(graph_receipt)}).validate()

    def _segmented_covariance(self,final,mjd):
        base = final.metadata["factor_prefix"]
        query_path = base+".segmented_covariance_queries.jsonl"
        groups = physical_queries(final,final.metadata["segmented_design"],query_path)
        trajectory,observations = groups["trajectory"],groups["nominal_observation"]
        grid = np.array([float(row["time"][0])+float(row["time"][1]) for row,_ in trajectory])
        observation_mjd = np.array([float(row["time"][0])+float(row["time"][1]) for row,_ in observations])
        if not np.array_equal(grid,mjd):
            raise NumericalFailure("changed_support","Native trajectory covariance query epochs changed")
        if not len(observation_mjd) or np.any(np.diff(observation_mjd)<=0):
            raise NumericalFailure("changed_support","Nominal observation covariance query epochs are not unique")
        blocks = [queries for _,queries in (*trajectory,*observations)]
        # Selected cross-segment pairs: first/last and epochs nearest the first
        # two computational cuts. A joint12 block keeps their correlation.
        pair_indices = covariance_pairs(mjd)
        for a,b in pair_indices:
            blocks.append(trajectory[a][1]+trajectory[b][1])
        # Required original-coordinate dynamic blocks: physical initial state
        # (not the scaled native initial coefficients) and force coordinates at
        # the first, middle and last knot/pulse block, jointly with initial SI.
        dynamic_queries,selected_force = self._dynamic_selection(final)
        blocks.append(dynamic_queries)
        started = time.monotonic()
        values = final.linear_system.covariance_blocks(final,blocks)
        covariance = np.asarray(values[:len(trajectory)])
        prediction_covariance = np.asarray(values[len(trajectory):len(trajectory)+len(observations)])
        cross_start = len(trajectory)+len(observations)
        cross = self.root/"cross-segment-covariance.npz"
        np.savez_compressed(cross,indices=np.asarray(pair_indices,dtype=int),
                            covariance=np.asarray(values[cross_start:cross_start+len(pair_indices)]),
                            mjd=mjd[np.asarray(pair_indices,dtype=int)])
        selected = self.root/"selected-dynamic-covariance.npz"
        np.savez_compressed(selected,covariance=values[-1],force_indices=np.asarray(selected_force,dtype=int))
        self.covariance_diagnostics = {"seconds":time.monotonic()-started,
            "trajectory_blocks":len(trajectory),"observation_blocks":len(observations),
            "cross_blocks":len(pair_indices),"source":"undamped native deterministic/stochastic conditionals",
            "dense_covariance_used":False,"deterministic_innovation_variance":0}
        return covariance,observation_mjd,prediction_covariance,[
            artifact_record("segmented_covariance_queries",query_path),
            artifact_record("cross_segment_covariance",cross),
            artifact_record("selected_dynamic_covariance",selected)]

    def _dynamic_selection(self,final):
        initial = native.read_native_table(final.metadata["design"])
        dynamic = np.flatnonzero(final.dynamic)
        if initial.shape != (6,len(dynamic)):
            raise NumericalFailure("parameter_order","Physical initial-state map differs from native dynamics")
        initial_queries = tuple(tuple((int(dynamic[j]),float(value)) for j,value in enumerate(row) if value)
                                for row in initial)
        force_count = len(dynamic)-6
        width = 1 if self.density else 3
        selected = sorted(set(range(min(width,force_count)))|set(range((force_count//(2*width))*width,
            min(force_count,(force_count//(2*width)+1)*width)))|set(range(max(0,force_count-width),force_count)))
        return initial_queries+tuple(((int(dynamic[j]),1.),) for j in selected),selected

    def _dense_covariance_extras(self,final,mjd):
        """Read-only diagnostic export; the archived solver stays untouched."""
        pin = self.job.get("backend",{}).get("diagnostic_native")
        if not isinstance(pin,dict) or not pin.get("path") or file_hash(pin["path"]) != pin.get("sha256"):
            raise ValueError("Dense cross-block diagnostics require the separately pinned v4 native exporter")
        folder = self.root/"dense-postfit-operator";folder.mkdir()
        config = final.metadata["config"]
        source = ET.parse(final.metadata["source"]).getroot()
        node = super()._evaluation(config,source,config["native_paths"]["variational"],
            folder/"unused-orbit.dat",None)[0]
        design = folder/"local-design.jsonl"
        _field(node,"outputfileSegmentedDesign",design);_field(node,"segmentedExportOnly","1")
        tree = _standalone(source,[node],config["date"])
        path = native._save_xml(tree,folder/"export.xml")
        remaining = self.controls.wall_time_seconds-(time.monotonic()-self.start)
        if remaining <= 0:raise NumericalFailure("timeout","Per-fit deadline reached before selected dense diagnostics")
        with without_inherited_warm_environment():
            execution = native.run_native(pin["path"],path,folder,"export",timeout=remaining,
                environment_overrides={"ORBIT_POC_NUMERICS_QR_PREFIX":str(folder/"precise"),
                                       "ORBIT_POC_NUMERICS_SOLVER":"scaled_qr_v1"})
        execution["diagnostic_only_native_sha256"] = pin["sha256"]
        execution["scope"] = "Read-only native operator export; no estimation, propagation or modification of archived dense result"
        self.executions.append(execution)
        pairs = covariance_pairs(mjd)
        maps = selected_original_design(design,sorted({i for pair in pairs for i in pair}))
        dynamic = np.flatnonzero(final.dynamic)
        covariance = []
        for a,b in pairs:
            query = np.zeros((12,len(final.scales)))
            query[:,dynamic] = np.vstack((maps[a],maps[b]))
            covariance.append(selected_covariance(final,query))
        cross = self.root/"cross-segment-covariance.npz"
        np.savez_compressed(cross,indices=np.asarray(pairs,dtype=int),covariance=np.asarray(covariance),
                            mjd=mjd[np.asarray(pairs,dtype=int)])
        queries,selected = self._dynamic_selection(final)
        query = np.zeros((len(queries),len(final.scales)))
        for i,row in enumerate(queries):
            for j,value in row:query[i,j]=value
        selected_path = self.root/"selected-dynamic-covariance.npz"
        np.savez_compressed(selected_path,covariance=selected_covariance(final,query),force_indices=np.asarray(selected,dtype=int))
        return [artifact_record("cross_segment_covariance",cross),artifact_record("selected_dynamic_covariance",selected_path),
                artifact_record("dense_diagnostic_native_operator",design),artifact_record("dense_diagnostic_configuration",path)]

    def finish(self,point):
        # Same fresh, tighter, strict undamped gate as corrected v3.1. No final
        # correction is applied; covariance refers to these accepted parameters.
        final = self.evaluate(point.state,"final-covariance",tighter=True,covariance=True)
        if final.support_hash != point.support_hash:
            raise NumericalFailure("changed_support","Final covariance changed observation support")
        rank = certify_rank(final)
        step,_,gradient = proposal(final)
        _,metrics = self.trial(final,step)
        if (metrics["position_change_m"] >= self.controls.maximum_position_change_m
                or metrics["density_update"] >= self.controls.maximum_density_update
                or metrics["pulse_update_m_s"] >= self.controls.maximum_pulse_update_m_s
                or gradient >= self.controls.normalized_gradient_tolerance
                or final.metadata["nuisance_floor_limited"]):
            raise NumericalFailure("stale_covariance","Fresh final undamped correction failed convergence")
        self.final_correction = {"fresh_undamped":True,"maximum_position_change_m":metrics["position_change_m"],
            "maximum_density_update":metrics["density_update"],"maximum_pulse_update_m_s":metrics["pulse_update_m_s"],
            "normalized_scaled_gradient":gradient}
        outputs = final.metadata["config"]["result_paths"]
        mjd,states = native._orbit(outputs["orbit"])
        if self.segmented:
            covariance,prediction_mjd,prediction_covariance,artifacts = self._segmented_covariance(final,mjd)
        else:
            covariance,invalid = native._covariance(outputs["covariance"],mjd)
            prediction_mjd = native.read_native_table(outputs["covariance_observations"],37)[:,0]
            prediction_covariance,invalid_prediction = native._covariance(outputs["covariance_observations"],prediction_mjd)
            if invalid or invalid_prediction:
                raise NumericalFailure("invalid_covariance","Native selected QR covariance is not positive definite")
            artifacts = [artifact_record("native_parameter_covariance",outputs["parameter_covariance"]),
                         *self._dense_covariance_extras(final,mjd)]
        covariance_is_valid(covariance);covariance_is_valid(prediction_covariance)
        estimate = self.root/"fit.npz"
        np.savez_compressed(estimate,times=(mjd-mjd[0])*86400.,mjd=mjd,states=states,covariance=covariance,
                            prediction_mjd=prediction_mjd,prediction_covariance=prediction_covariance)
        physical = self.root/"physical_parameters.json"
        write_json(physical,{"initial_state_si":final.state.initial.tolist(),"force":final.state.force.tolist(),
            "force_units":"log density" if self.density else "um/s","objective":final.objective,
            "derivative_profile":self.derivatives,"covariance_scope":"local Gaussian; selected hyperparameters fixed"})
        artifacts += [artifact_record("state_estimate",estimate),artifact_record("physical_parameters",physical),
            artifact_record("native_nuisance_profile",Path(final.metadata["folder"])/"qr.profile.json"),
            artifact_record("native_initial_state_design",final.metadata["design"]),
            artifact_record("native_reference_parameters",final.metadata["reference"]),
            artifact_record("native_fit_configuration",final.metadata["configuration"]),
            artifact_record("native_variational",final.metadata["config"]["native_paths"]["variational"])]
        for suffix,role in ((".R.bin","native_qr_factor"),(".rhs.bin","native_qr_rhs"),
            (".factor.json","native_qr_coordinates"),(".diagnostics.json","native_qr_diagnostics"),
            (".profile.json","native_objective"),(".parameters.tsv","native_qr_parameters"),
            (".rows.tsv.gz","native_qr_row_provenance"),(".rows.tsv.compression.json","native_qr_row_compression_receipt")):
            artifacts.append(artifact_record(role,final.metadata["factor_prefix"]+suffix))
        for key,role in (("orbit_native","estimated_orbit_native"),("parameters","native_parameters"),
            ("preprocessing_audit","native_preprocessing_audit"),("phase_recovery","phase_recovery"),
            ("apriori_solution","full_native_solution"),("parameter_names","native_parameter_names")):
            artifacts.append(artifact_record(role,outputs[key]))
        if self.segmented:
            artifacts += [artifact_record("segmented_final_graph",final.metadata["segmented_graph_receipt"]),
                          artifact_record("segmented_final_design",final.metadata["segmented_design"])]
        artifacts += prediction_artifacts(self,final)
        return {"objective":final.objective,"covariance_valid":True,"artifacts":artifacts,
                "strict_nuisance_converged":True,"strict_final_correction":self.final_correction,
                "preprocessing_audit_sha256":file_hash(outputs["preprocessing_audit"]),"rank":rank}


def fit_job(job,job_dir):
    if job.get("segmented_profile") not in ("dense_corrected","segmented_1h","segmented_4h"):
        raise ValueError("Explicit registered v4 profile required")
    if job.get("numerics_profile") != "qr_lm_staged_jacobian" or job.get("method") not in ("groops_pulses","groops_log_drag_ou"):
        raise ValueError("v4 preserves the corrected staged Jacobian and primary float models")
    if any(key in job for key in ("evaluation_inputs","calibration_inputs","truth","reference_orbit")):
        raise ValueError("Fitting accepts blind estimation inputs only")
    root = Path(job_dir).resolve();root.mkdir(parents=True,exist_ok=True)
    model = V4Model(job,root)
    try:
        result = minimize(model,model.initial_state(),controls=model.controls,started_at=model.start,
                          emit=lambda value:write_json(root/"iterations.json",value))
    except NumericalFailure as error:
        result = {"status":error.reason,"converged":False,"covariance_valid":False,"error":str(error)}
    final = result.pop("result",{})
    numerical_status = result["status"]
    status = numerical_status if numerical_status in ("complete","timeout","unresolved_rank","invalid_covariance") else "failed"
    runtime = {**result,"execution":model.executions,"propagation_count":model.propagations,
        "elapsed_seconds":time.monotonic()-model.start,"linear_systems":model.linear_diagnostics,
        "covariance":model.covariance_diagnostics,"native_binary_sha256":file_hash(model.binary),
        "profile":model.profile,"derivative_profile":model.derivatives,
        "dense_rank_certification_included":True,
        "scratch_storage_bytes":sum(p.stat().st_size for p in root.rglob("*") if p.is_file() and not p.is_symlink()),
        "peak_rss_bytes":max((x["peak_rss_bytes"] for x in model.executions),default=0),
        "peak_rss_scope":"maximum native parent RSS; harness separately measures recursive process-tree RSS"}
    write_json(root/"native_runtime.json",runtime);write_json(root/"iterations.json",result)
    return {**result,**final,"status":status,"numerical_status":numerical_status,"method":job["method"],
        "objective_resolution":result.get("objective_floor"),"covariance_valid":bool(final.get("covariance_valid")),
        "covariance_scope":"marginalized","parameter_blocks":["initial_state","log_density" if model.density else "pulses",
            "receiver_clock","ionosphere","signal_bias","float_ambiguities"],
        "runtime":runtime,"numerical_diagnostics":runtime,"elapsed_seconds":runtime["elapsed_seconds"],
        "peak_rss_bytes":runtime["peak_rss_bytes"],"peak_rss_scope":runtime["peak_rss_scope"],
        "metadata":{"reference_inputs_used":False,"derivative_profile":model.derivatives,
            "states_frame":"CRF","states_units":"m,m/s","ambiguity_policy":"jointly estimated float ambiguities",
            "covariance_scope":"local Gaussian; fixed selected hyperparameters; fresh undamped linearization",
            "omitted_flight_derivatives":["thermal-history state sensitivities","force gradients other than gravity and drag",
                "atmospheric event-time sensitivities"] if model.derivatives=="flight_gravity_drag_v1" else [],
            "physical_propagation":"whole arc chronological; fresh force history every closure; unchanged physical boundaries",
            "linear_system":model.profile,"rank_certificate":"original-coordinate dense QR/SVD; original stochastic row/column counts"},
        "source_hash":job["source_hash"],"native_binary_sha256":file_hash(model.binary),
        "artifacts":[*final.get("artifacts",[]),artifact_record("native_runtime",root/"native_runtime.json")],
        **{key:job[key] for key in ("force_model_hash","measurement_model_hash","preprocessing_hash","mask_hash")}}
