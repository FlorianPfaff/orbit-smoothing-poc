"""Report every frozen attempt; missing scientific gates never imply release."""
from __future__ import annotations
from collections import Counter
import html,json,math
from pathlib import Path
from . import protocol as p


def number(x):return type(x) in (int,float) and math.isfinite(x)

def strict_result(result,job):
    from ..numerics.protocol import validate_complete_result
    validate_complete_result(result,job)
    if result.get('strict_nuisance_converged') is not True:raise ValueError('Fresh strict nuisance stationarity is not established')
    d=result.get('strict_final_correction',{})
    if d.get('fresh_undamped') is not True:raise ValueError('Fresh undamped correction is missing')
    limits={'maximum_position_change_m':3e-5,'normalized_scaled_gradient':1e-8,
        'maximum_density_update' if job['method']=='groops_log_drag_ou' else 'maximum_pulse_update_m_s':1e-4 if job['method']=='groops_log_drag_ou' else 1e-8}
    for key,limit in limits.items():
        if not number(d.get(key)) or not 0<=d[key]<limit:raise ValueError('Strict final correction failed: '+key)
    return True


def equivalence(dense,segmented):
    """Compare only identical case inputs, never different disturbance models."""
    import numpy as np
    if not p.is_digest(dense.get('preprocessing_audit_sha256')) or dense['preprocessing_audit_sha256']!=segmented.get('preprocessing_audit_sha256'):raise ValueError('Native preprocessing support/weights changed across profiles')
    from ..numerics.protocol import read_cartesian_estimate
    def state(r):
        a=[a for a in r['artifacts'] if a['role']=='state_estimate']
        if len(a)!=1:raise ValueError('Unique state estimate required')
        return read_cartesian_estimate(a[0])
    a,b=state(dense),state(segmented)
    def observation_covariance(result):
        item=next(x for x in result['artifacts'] if x['role']=='state_estimate')
        with np.load(p.verify_artifact(item),allow_pickle=False) as z:
            epochs,covariance=z['prediction_mjd'],z['prediction_covariance']
        if epochs.ndim!=1 or not len(epochs) or np.any(np.diff(epochs)<=0) or covariance.shape!=(len(epochs),6,6) or not np.isfinite(epochs).all() or not np.isfinite(covariance).all():raise ValueError('Invalid nominal-observation covariance arrays')
        sd=np.sqrt(np.diagonal(covariance,axis1=1,axis2=2))
        if np.any(sd<=0) or not np.isfinite(sd).all() or not np.allclose(covariance,covariance.transpose(0,2,1),rtol=1e-9,atol=1e-14):raise ValueError('Invalid nominal-observation covariance')
        np.linalg.cholesky(covariance/sd[:,:,None]/sd[:,None,:])
        return epochs,covariance,sd
    ea,oa,osa=observation_covariance(dense);eb,ob,_=observation_covariance(segmented)
    if not np.array_equal(ea,eb):raise ValueError('Nominal-observation covariance epochs differ')
    observation_cov=float(np.max(np.linalg.norm((ob-oa)/osa[:,:,None]/osa[:,None,:],axis=(1,2))))
    if not np.array_equal(a['mjd'],b['mjd']):raise ValueError('Equivalent profiles require identical output epochs')
    position=float(np.max(np.linalg.norm(a['states'][:,:3]-b['states'][:,:3],axis=1)))
    ca,cb=a['covariance'],b['covariance'];scales=np.sqrt(np.diagonal(ca,axis1=1,axis2=2))
    normalized=(cb-ca)/scales[:,:,None]/scales[:,None,:]
    cov=float(np.max(np.linalg.norm(normalized,axis=(1,2))))
    def one(result,role):
        values=[item for item in result['artifacts'] if item['role']==role]
        if len(values)!=1:raise ValueError('Required unique artifact missing: '+role)
        return p.verify_artifact(values[0])
    pa,pb=(p.read_json(one(result,'physical_parameters')) for result in (dense,segmented))
    units=pa.get('force_units')
    if units not in ('log density','um/s') or pb.get('force_units')!=units:raise ValueError('Native force coordinate units differ')
    fa,fb=(np.asarray(record['force'],float) for record in (pa,pb))
    if fa.shape!=fb.shape or not fa.size or not np.isfinite(fa).all() or not np.isfinite(fb).all():raise ValueError('Force coordinate inventory differs')
    force=float(np.max(abs(fa-fb)))*(1e-6 if units=='um/s' else 1.)
    force_limit=1e-8 if units=='um/s' else 1e-4
    def blocks(role,keys):
        values=[]
        for result in (dense,segmented):
            with np.load(one(result,role),allow_pickle=False) as z:values.append({k:z[k] for k in z.files})
        first,second=values
        if any(not np.array_equal(first[k],second[k]) for k in keys):raise ValueError('Selected covariance query identity differs: '+role)
        first,second=first['covariance'],second['covariance']
        if first.shape!=second.shape or first.ndim not in (2,3) or first.shape[-1]!=first.shape[-2] or not first.size or not np.isfinite(first).all() or not np.isfinite(second).all():raise ValueError('Invalid selected covariance blocks')
        sd=np.sqrt(np.diagonal(first,axis1=-2,axis2=-1))
        if not np.isfinite(sd).all() or np.any(sd<=0):raise ValueError('Invalid selected posterior scales')
        difference=(second-first)/sd[..., :,None]/sd[...,None,:]
        diagonal_normalized=float(np.max(np.linalg.norm(difference,axis=(-1,-2))))
        if role=='cross_segment_covariance':
            if first.ndim!=3 or first.shape[1:]!=(12,12):raise ValueError('Cross queries must be joint12 Cartesian blocks')
            numerator=np.linalg.norm(second[:,:6,6:]-first[:,:6,6:],axis=(1,2))
            denominator=np.sqrt(np.linalg.norm(first[:,:6,:6],axis=(1,2))*np.linalg.norm(first[:,6:,6:],axis=(1,2)))
            if np.any(denominator<=0):raise ValueError('Cross marginal scales must be positive')
            return float(np.max(numerator/denominator)),diagonal_normalized
        return diagonal_normalized
    cross,cross_joint=blocks('cross_segment_covariance',('indices','mjd'))
    dynamic=blocks('selected_dynamic_covariance',('force_indices',))
    # Native predictions retain observed signal and fixed sigma per row.
    def predictions(r):
        items=[x for x in r['artifacts'] if x['role']=='segmented_predictions']
        if len(items)!=1:raise ValueError('Native prediction rows with fixed noise are required')
        with np.load(p.verify_artifact(items[0]),allow_pickle=False) as z:return {k:z[k] for k in z.files}
    x,y=predictions(dense),predictions(segmented)
    if set(x)!={'row_ids','values_m','sigma_m'} or set(y)!=set(x) or not np.array_equal(x['row_ids'],y['row_ids']) or not np.array_equal(x['sigma_m'],y['sigma_m']):raise ValueError('Prediction support/noise changed')
    if any(z['values_m'].ndim!=1 or z['sigma_m'].shape!=z['values_m'].shape or z['row_ids'].shape!=z['values_m'].shape or len(np.unique(z['row_ids']))!=len(z['row_ids']) for z in (x,y)):raise ValueError('Prediction rows must have unique identities and matching scalar arrays')
    if not np.isfinite(x['values_m']).all() or not np.isfinite(y['values_m']).all() or not np.isfinite(x['sigma_m']).all() or np.any(x['sigma_m']<=0) or not x['sigma_m'].size:raise ValueError('Invalid native prediction rows')
    prediction=float(np.max(abs(x['values_m']-y['values_m'])/x['sigma_m']))
    for r in (dense,segmented):
        if not number(r.get('objective')) or not number(r.get('objective_resolution')) or r['objective_resolution']<0:raise ValueError('Actual objective and measured resolution are required')
    delta=abs(dense['objective']-segmented['objective']);resolution=dense['objective_resolution']+segmented['objective_resolution']
    return {'status':'passed' if cov<1e-6 and observation_cov<1e-6 and cross<1e-6 and dynamic<1e-6 and position<3e-5 and force<force_limit and prediction<.01 and delta<=resolution else 'failed',
        'maximum_normalized_covariance_difference':cov,'maximum_normalized_observation_covariance_difference':observation_cov,'maximum_normalized_cross_covariance_difference':cross,'cross_normalization':'Frobenius difference divided by sqrt(||Paa_dense||_F*||Pbb_dense||_F)','maximum_diagonal_normalized_joint12_difference':cross_joint,'maximum_normalized_dynamic_covariance_difference':dynamic,'maximum_position_difference_m':position,'maximum_force_difference_si':force,'force_tolerance_si':force_limit,'maximum_prediction_noise_ratio':prediction,
        'objective_difference':delta,'measured_objective_resolution':resolution,
        'scope':'Same observations, priors, weights and model; local Gaussian covariance at selected hyperparameters.'}


def original_benchmark(config,project):
    """Require the original150 attempts and pinned native runtime identities."""
    from ..numerics.protocol import attempt_job as original_job
    from ..numerics.config import config_from_dict
    manifest=p.read_json(p.verify_artifact(config.original150_manifest,project));report=p.read_json(p.verify_artifact(config.original150_report,project))
    if manifest.get('manifest_hash')!=p.canonical_hash({k:v for k,v in manifest.items() if k!='manifest_hash'}):raise ValueError('Original150 manifest hash differs')
    if report.get('manifest_hash')!=manifest['manifest_hash'] or report.get('expected_attempts')!=150 or report.get('terminal_attempts')!=150 or report.get('execution_complete') is not True:raise ValueError('Original150 benchmark report is incomplete')
    attempts=manifest.get('attempts',[]);rows=report.get('attempts',[])
    if len(attempts)!=150 or len(rows)!=150 or len({x['attempt_id'] for x in rows})!=150:raise ValueError('Original150 attempt inventory differs')
    if len({x['attempt_id'] for x in attempts})!=150 or Counter(x['profile'] for x in attempts)!={'legacy_v3':50,'qr_lm_legacy_jacobian':50,'qr_lm_staged_jacobian':50}:raise ValueError('Original150 profile inventory differs')
    plan=p.read_json(p.verify_artifact(config.original150_plan,project))
    if plan.get('plan_hash')!=p.canonical_hash({k:v for k,v in plan.items() if k!='plan_hash'}) or manifest.get('plan_hash')!=plan['plan_hash'] or report.get('plan_hash')!=plan['plan_hash'] or plan.get('attempts')!=attempts:raise ValueError('Original150 plan identity differs')
    original_config=config_from_dict(plan['config']);cases={c['case_id']:c for c in manifest['cases']}
    if len(cases)!=50:raise ValueError('Original150 case inventory differs')
    indexed={x['attempt_id']:x for x in rows}
    for attempt in attempts:
        row=indexed.get(attempt['attempt_id'],{})
        if row.get('status') not in p.TERMINAL:raise ValueError('Original150 has a missing/nonterminal attempt')
        result_path=p.verify_artifact(row['result'],project);result=p.read_json(result_path)
        job=original_job(original_config,manifest,cases[attempt['case_id']],attempt)
        if p.read_json(result_path.parent/'request.json')!=job or result.get('request_hash')!=p.canonical_hash(job) or result.get('input_manifest_hash')!=job['input_manifest_hash']:raise ValueError('Original150 per-attempt request/input identity differs')
        profile=attempt['profile'];runtime=manifest['legacy_runtime' if profile=='legacy_v3' else 'new_runtime']
        measured=result.get('harness_execution',{}).get('runtime',{})
        if measured.get('native',{}).get('sha256')!=runtime['native']['sha256'] or measured.get('source_sha256')!=runtime['source_sha256']:raise ValueError('Original150 runtime was substituted')
        if result.get('numerics_manifest_hash')!=manifest['manifest_hash'] or result.get('numerics_profile')!=profile or result.get('status')!=row['status']:raise ValueError('Original150 result attribution differs')
    return {'status':'passed','attempts':150,'manifest':p.artifact(p.verify_artifact(config.original150_manifest,project)),'report':p.artifact(p.verify_artifact(config.original150_report,project)),'scope':'Completion with original runtimes; failures remain reported.'}


def fixed_test_inventory(name):
    """Immutable corrected-c24 names are shipped with the pinned source."""
    from .validation_reference import TEST_INVENTORIES
    return [dict(item) for item in TEST_INVENTORIES[name]]


def replay_validation(row,original,manifest,project):
    """Read the native receipt and its exact physical-input request, not labels."""
    import xml.etree.ElementTree as ET
    data=p.read_json(p.verify_artifact(row['receipt'],project));profile=data.get('profile') or {}
    if data.get('schema')!='orbit-poc-native-nuisance-validation-v1' or data.get('native_sha256')!=manifest['runtimes']['segmented']['native']['sha256'] or data.get('native_unchanged') is not True or data.get('passed') is not True or data.get('returncode')!=0 or data.get('timed_out') is not False or data.get('strict_nuisance_converged') is not True or data.get('progress_only_floor_validated') is not False:raise ValueError('Actual original replay receipt failed strict convergence')
    if profile.get('threshold_m')!=1e-8 or profile.get('required_consecutive_small_updates')!=2 or profile.get('nuisance_converged') is not True or profile.get('nuisance_floor_limited') is not False or profile.get('dynamic_updates') is not False or profile.get('fixed_weights') is not True:raise ValueError('Replay profile policy changed')
    history=profile.get('history',[])
    if len(history)<2 or any(not number(x.get('maximum_update_m')) or not 0<=x['maximum_update_m']<1e-8 for x in history[-2:]) or profile.get('maximum_update_m')!=history[-1]['maximum_update_m']:raise ValueError('Replay lacks two strict undamped updates')
    provenance=original['provenance'];trees=[]
    for key,digest in (('source_profile',provenance['source_profile_sha256']),('executed_profile',data['replay_profile_sha256'])):
        path=p.verify_artifact(row[key],project);raw=path.read_bytes()
        if p.file_hash(path)!=digest or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('Replay XML identity differs')
        trees.append(ET.fromstring(raw))
    if data.get('source_profile_sha256')!=provenance['source_profile_sha256']:raise ValueError('Replay original source was substituted')
    for tag,key in (('inputfileVariational','variational'),('inputfileNumericsReferenceParameters','reference'),('inputfileLogDensity','density')):
        item=row['physical_inputs'][key];path=p.verify_artifact(item,project)
        if p.file_hash(path)!=provenance['physical_input_hashes'][key]:raise ValueError('Replay physical-input bytes changed')
        # XML paths remain the actual original execution paths. Explicit aliases
        # are permitted for transferred files, but must be equal in both XMLs.
        expected=item.get('execution_path',str(path))
        for tree in trees:
            values=[(x.text or '').strip() for x in tree.iter(tag)]
            if not values or any(value!=expected for value in values):raise ValueError('Replay XML physical input differs')
    if row.get('provenance')!=provenance or row.get('status')!='strict_converged' or row.get('floor_limited') is not False or row.get('raw_update_m')!=profile['maximum_update_m']:raise ValueError('Replay summary differs from native receipt')
    searches=data.get('searches',[])
    if len(searches)!=len(history) or len(searches)<2 or data.get('zero_update_replay_exact') is not True or data.get('fixed_observations_and_weights_verified_every_trial') is not True:raise ValueError('Replay transaction history is incomplete')
    for index,search in enumerate(searches):
        zero=search.get('zero_update_replay') or {}
        if search.get('generation')!=index+1 or zero.get('status')!=0 or zero.get('actual_reduction')!=0 or zero.get('maximum_update_m')!=0 or zero.get('cost')!=search.get('objective_before'):raise ValueError('Replay zero transaction differs')
    if any(x.get('stationary_without_update') is not True or x.get('nuisance_floor_limited') is not False or not number(x.get('undamped_maximum_update_m')) or not 0<=x['undamped_maximum_update_m']<1e-8 for x in searches[-2:]):raise ValueError('Replay final searches are not strict')
    return profile['maximum_update_m']


def _gate_identity(value,name,manifest,schema):
    if value.get('schema')!=schema or value.get('check')!=name or value.get('manifest_hash')!=manifest['manifest_hash'] or value.get('source_sha256')!=manifest['runtimes']['segmented']['source_sha256'] or value.get('native_sha256')!=manifest['runtimes']['segmented']['native']['sha256']:
        raise ValueError('Gate evidence identity differs: '+name)


def _gate_result(item,name,manifest,project):
    receipt=p.read_json(p.verify_artifact(item['evidence'],project))
    _gate_identity(receipt,name,manifest,'orbit-poc-segmented-gate-receipt-v1')
    if receipt.get('status')!='passed':raise ValueError('Gate receipt failed: '+name)
    invocation=p.read_json(p.verify_artifact(receipt['invocation'],project))
    _gate_identity(invocation,name,manifest,'orbit-poc-segmented-gate-invocation-v1')
    if invocation.get('returncode')!=0 or invocation.get('status')!='completed' or invocation.get('timed_out') is not False or invocation.get('cleanup_verified') is not True or not invocation.get('argv'):raise ValueError('Gate invocation failed/incomplete: '+name)
    path=p.verify_artifact(receipt['result'],project)
    if name in ('original_native_tests','correctness_tests'):
        import xml.etree.ElementTree as ET
        root=ET.parse(path).getroot();cases=root.findall('.//testcase')
        inventory=[{'classname':x.get('classname',''),'name':x.get('name','')} for x in cases]
        expected=p.read_json(p.verify_artifact(receipt['test_inventory'],project))
        if not isinstance(expected,list) or inventory!=expected or len({(x['classname'],x['name']) for x in inventory})!=len(inventory):raise ValueError('Native test inventory differs')
        if any(x.find('failure') is not None or x.find('error') is not None or x.find('skipped') is not None for x in cases):raise ValueError('Native JUnit contains a failed/skipped test')
        if inventory!=fixed_test_inventory(name):raise ValueError('Required source/reference test inventory was substituted')
        return {'passed':len(cases),'expected':len(expected),'failed':0,'skipped':0}
    result=p.read_json(path);_gate_identity(result,name,manifest,'orbit-poc-segmented-measured-gate-v1')
    if result.get('status')!='passed':raise ValueError('Measured gate result failed: '+name)
    # Retain and recheck every underlying output used to derive this measurement.
    if not result.get('raw_artifacts'):raise ValueError('Measured gate has no underlying artifacts: '+name)
    for artifact in result['raw_artifacts']:p.verify_artifact(artifact,project)
    return result


def objective_validation(artifact,method,manifest,project):
    """Recompute the unchanged prior and consecutive-scale objective criteria."""
    value=p.read_json(p.verify_artifact(artifact,project))
    if value.get('passed') is not True or value.get('native_binary_sha256')!=manifest['runtimes']['segmented']['native']['sha256'] or value.get('relative_derivative_tolerance')!=1e-4:raise ValueError('Native objective validation failed or differs')
    prior=value.get('prior',{});density=method=='groops_log_drag_ou';tolerance=2e-8 if density else 1e-12
    if prior.get('rows')!=(61 if density else 6) or prior.get('source')!=('constraint.logDensityOu' if density else 'constraint.pulses') or prior.get('absolute_tolerance')!=tolerance or not number(prior.get('maximum_residual_difference')) or not 0<=prior['maximum_residual_difference']<=tolerance or not number(prior.get('cost')) or not 0<prior['cost']<=prior.get('objective',-1):raise ValueError('Nonzero full prior criterion failed')
    policy=value.get('derivative_refinement_policy',{})
    if policy!={'maximum_scales':9,'physical_repeat_allowance_multiplier':10,'ratio':.5,'required_consecutive_passing_scales':2}:raise ValueError('Objective refinement policy changed')
    repeat=value.get('objective_repeat_difference');physical=value.get('empirical_physical_objective_resolution')
    if not number(repeat) or repeat<0 or not number(physical) or physical<10*repeat:raise ValueError('Physical repeat allowance was omitted')
    directions=value.get('directional_derivatives',[])
    if not 2<=len(directions)<=9 or directions[0].get('scale')!=1.:raise ValueError('Objective scale inventory changed')
    streak=[];last_scale=None
    for row in directions:
        scale=row['scale'];negative=row['negative_cost'];positive=row['positive_cost'];native=row['native_derivative'];checks=row['endpoint_resolution_checks']
        if not all(number(x) for x in (scale,negative,positive,native)) or scale<=0 or (last_scale is not None and scale!=last_scale*.5):raise ValueError('Objective scale/values differ')
        if len(checks)!=2 or {x['sign'] for x in checks}!={-1,1}:raise ValueError('Missing objective repeat endpoints')
        if any(not number(x.get('empirical_resolution')) or x['empirical_resolution']<0 for x in checks):raise ValueError('Missing objective repeat resolution')
        for endpoint in checks:
            original=negative if endpoint['sign']==-1 else positive
            if not number(endpoint.get('repeat_cost')) or not number(endpoint.get('repeat_difference')) or not math.isclose(abs(original-endpoint['repeat_cost']),endpoint['repeat_difference'],rel_tol=1e-12,abs_tol=1e-15) or endpoint['empirical_resolution']<max(physical,10*endpoint['repeat_difference']):raise ValueError('Objective repeat allowance differs')
        finite=(positive-negative)/(2*scale);denominator=max(abs(finite),abs(native),1e-12)
        error=abs(finite-native)/denominator+sum(x['empirical_resolution'] for x in checks)/(2*scale*denominator)
        passed=error<=1e-4
        if row.get('passes_unchanged_tolerance') is not passed or not math.isclose(row.get('relative_difference_plus_resolution',-1),error,rel_tol=1e-12,abs_tol=1e-15):raise ValueError('Objective criterion arithmetic differs')
        streak=streak+[scale] if passed else [];last_scale=scale
    if len(streak)<2 or value.get('accepted_derivative_scales')!=streak[-2:]:raise ValueError('Objective has no consecutive passing scales')
    return streak[-2:]


def external_gates(config,manifest,project):
    value=p.read_json(p.verify_artifact(config.release_evidence,project))
    if value.get('schema')!='orbit-poc-segmented-gates-v1' or value.get('manifest_hash')!=manifest['manifest_hash'] or value.get('native_sha256')!=manifest['runtimes']['segmented']['native']['sha256'] or value.get('source_sha256')!=manifest['runtimes']['segmented']['source_sha256']:raise ValueError('Release gates not bound to this source/runtime/input freeze')
    verified={}
    for name,count in (('original_native_tests',106),('correctness_tests',51)):
        row=_gate_result(value[name],name,manifest,project)
        if row!={'passed':count,'expected':count,'failed':0,'skipped':0}:raise ValueError('Required unchanged test count differs: '+name)
        verified[name]=row
    ref=_gate_result(value['refinements'],'refinements',manifest,project)['measurements']
    expected={'synthetic_log_drag_ou','synthetic_pulses','flight_window','eccentric24h'}
    if {x['case'] for x in ref}!=expected or len(ref)!=4 or any(not number(x.get('maximum_fraction_of_sigma')) or not 0<=x['maximum_fraction_of_sigma']<.01 for x in ref):raise ValueError('Propagation/measurement refinement criterion failed')
    objectives=_gate_result(value['objectives'],'objectives',manifest,project)['measurements']
    if len(objectives)!=2 or {x['method'] for x in objectives}!={'groops_pulses','groops_log_drag_ou'}:raise ValueError('Objective methods differ')
    for row in objectives:
        scales=objective_validation(row['validation'],row['method'],manifest,project)
        if row.get('accepted_scales')!=scales:raise ValueError('Objective summary differs from measured consecutive scales')
    replays=_gate_result(value['original_replays'],'original_replays',manifest,project)['measurements']
    original=p.read_json(p.verify_artifact(config.corrected_reference,project))['nuisance_replays']
    expected_names={'nuisance-replay','nuisance-replay-candidate1-point012'}
    if len(replays)!=2 or {x['name'] for x in replays}!=expected_names:raise ValueError('Distinct original replay inventory differs')
    for row in replays:
        replay_validation(row,original[row['name']],manifest,project)
    for name,limit in (('maximum_lift_true_residual',2e-12),('small_map_posterior_sd',1e-7),('small_covariance_relative_error',1e-8)):
        row=_gate_result(value[name],name,manifest,project);measurement=row.get('value')
        if not number(measurement) or not 0<=measurement<limit:raise ValueError('Measured scalar criterion failed: '+name)
        verified[name]=measurement
    for name in ('rank_classification','unit_row_block_invariance','constraint_and_cross_covariance','transactional_rollback','propagated_derivatives'):
        row=_gate_result(value[name],name,manifest,project)
        if not row.get('checks') or any(x.get('passed') is not True for x in row['checks']):raise ValueError('Structural gate has failed/missing checks: '+name)
    return {'status':'passed','evidence':p.artifact(p.verify_artifact(config.release_evidence,project)),'verified_measurements':verified}


def prebenchmark_gates(config,manifest,root,project):
    from .validation import require_passed
    checked=require_passed(config,manifest,root,project)
    if config.release_evidence.path:checked['additional_attached_evidence']=external_gates(config,manifest,project)
    return checked


def reporting_inputs(config,root,manifest):
    """Append-only pins added after execution; never part of the fit identity."""
    from dataclasses import asdict
    value={'schema':'orbit-poc-segmented-reporting-inputs-v1','manifest_hash':manifest['manifest_hash'] if manifest else None,
        'artifacts':{name:asdict(getattr(config,name)) for name in p.REPORTING_INPUTS}}
    digest=p.canonical_hash(value);path=root/'reporting-inputs'/(digest+'.json')
    if path.exists() and p.read_json(path)!=value:raise ValueError('Reporting attachment identity changed')
    if not path.exists():p.write_json(path,value)
    return p.artifact(path)


def release_conditions(rows,pairs,gates):
    indexed={row['attempt_id']:row for row in rows}
    required=[x for x in rows if x['profile']=='segmented_1h' and x['case'].get('orbit')=='leo500' and x['case'].get('atmosphere')=='disturbed' and x['case']['duration_hours']==72]
    flight=[x for x in pairs if indexed[x['segmented_attempt']]['stage']=='flight']
    evaluated=[x for x in pairs if indexed[x['dense_attempt']]['strict_success'] and indexed[x['segmented_attempt']]['strict_success']]
    return {'all68_terminal':len(rows)==68 and all(x['status'] in p.TERMINAL for x in rows),
        'all_successful_pairs_equivalent':bool(evaluated) and all(x['status']=='passed' for x in evaluated),
        'flight_equivalence':len(flight)==8 and all(x['status']=='passed' for x in flight),
        'required72h_both_methods_strict':len(required)==2 and {x['method'] for x in required}=={'groops_pulses','groops_log_drag_ou'} and all(x['strict_success'] for x in required),
        'no_dense_success_segmented_failure':not any(x['regression'] for x in pairs),
        'all_external_gates':all(x['status']=='passed' for x in gates.values()) and len(gates)==2}


def create_report(config,output_dir=None,*,project=None):
    config.validate();project=Path(project or p.project_root()).resolve();root=p.resolve(output_dir or config.output_dir,project)
    plan=p.freeze_plan(config,root,project);errors=[];manifest=None
    try:manifest=p.verify_manifest(config,root,project)
    except (OSError,ValueError,RuntimeError,KeyError,TypeError) as e:errors.append('Preparation: '+str(e))
    cases={x['case_id']:x for x in (manifest or plan)['cases']};rows=[];raw={}
    for attempt in plan['attempts']:
        case=cases[attempt['case_id']];row={**attempt,'stage':case['stage'],'method':case['method'],'family_id':case['family_id'],'case':case['case'],'status':'not_run','strict_success':False}
        d=root/'attempts'/attempt['attempt_id']
        if (d/'result-record.json').exists() and manifest:
            try:
                job=p.attempt_job(config,manifest,case,attempt);result=p.checkpoint(d,job)
                row.update(status=result['status'],result=p.artifact(d/'result.json'),error=result.get('error'),
                    elapsed_seconds=result.get('harness_execution',{}).get('elapsed_seconds'),peak_process_tree_rss_bytes=result.get('harness_execution',{}).get('peak_process_tree_rss_bytes'),
                    objective=result.get('objective'),objective_resolution=result.get('objective_resolution'),numerical_diagnostics=result.get('numerical_diagnostics'))
                if result['status']=='complete':row['strict_success']=strict_result(result,job)
                raw[attempt['attempt_id']]=result
            except (OSError,ValueError,RuntimeError,KeyError,TypeError) as e:row.update(status='invalid',error=str(e))
        elif d.exists():row.update(status='interrupted_or_unverified',error='No matching verified terminal checkpoint')
        rows.append(row)
    indexed={x['attempt_id']:x for x in rows};pairs=[]
    for row in rows:
        if row['profile']=='dense_corrected':continue
        dense_id=row['case_id']+'--dense_corrected';dense=indexed[dense_id]
        pair={'dense_attempt':dense_id,'segmented_attempt':row['attempt_id'],'status':'unavailable','regression':dense['strict_success'] and not row['strict_success']}
        if dense['strict_success'] and row['strict_success']:
            try:pair.update(equivalence(raw[dense_id],raw[row['attempt_id']]))
            except (OSError,ValueError,RuntimeError,KeyError,TypeError) as e:pair.update(status='invalid',error=str(e))
        pairs.append(pair)
    gates={}
    for name,call in (('native_correctness',lambda:prebenchmark_gates(config,manifest,root,project)),('original150_completion',lambda:original_benchmark(config,project))):
        try:
            if manifest is None:raise ValueError('No verified input manifest')
            gates[name]=call()
        except (OSError,ValueError,RuntimeError,KeyError,TypeError) as e:gates[name]={'status':'pending_or_failed','error':str(e)}
    terminal=sum(x['status'] in p.TERMINAL for x in rows)
    conditions=release_conditions(rows,pairs,gates);ready=all(conditions.values())
    report={'schema':'orbit-poc-segmented-report-v1','manifest_hash':manifest['manifest_hash'] if manifest else None,'plan_hash':plan['plan_hash'],
        'expected_attempts':68,'terminal_attempts':terminal,'execution_complete':terminal==68,'release_ready':ready,'legacy_default_unchanged':True,
        'reporting_inputs':reporting_inputs(config,root,manifest),'release_conditions':conditions,'status_counts':dict(Counter(x['status'] for x in rows)),'attempts':rows,'equivalence':pairs,'gates':gates,'input_errors':errors,
        'limitations':['No speedup or accuracy-superiority claim.','Shared seeds, prefix arcs and coverage variants are dependent observations, not independent statistical trials.',
            'Runtime and peak RSS include failures and timeouts. Rank defects and unresolved nuisance profiles cannot authorize covariance.',
            'Flight gravity/drag derivatives omit thermal history, other force gradients and atmospheric event-time derivatives; flight equivalence does not certify a complete Jacobian.',
            'The original150 benchmark must finish with its own pinned binaries; corrected/segmented results cannot replace it.']}
    p.write_json(root/'report.json',report)
    esc=html.escape
    content=['<!doctype html><meta charset="utf-8"><title>v4 segmented numerical benchmark</title><style>body{font:16px system-ui;max-width:1250px;margin:auto;padding:2rem}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:.4rem}code{overflow-wrap:anywhere}</style><h1>v4 segmented numerical benchmark</h1>',
        f'<p>{terminal}/68 terminal attempts. Release readiness: <b>{str(ready).lower()}</b>. Legacy defaults remain unchanged.</p>',
        '<p><a href="report.json">Complete machine-readable report, identities and diagnostics</a></p>',
        '<table><tr><th>Attempt</th><th>Status</th><th>Strict success</th><th>Wall seconds</th><th>Peak RSS bytes</th></tr>']
    for row in rows:content.append('<tr>'+''.join('<td>'+esc(str(row.get(k,'')))+'</td>' for k in ('attempt_id','status','strict_success','elapsed_seconds','peak_process_tree_rss_bytes'))+'</tr>')
    content.append('</table><h2>Paired numerical equivalence</h2><p>Every segmented attempt is paired with its corrected dense counterpart on identical inputs. Unavailable comparisons are retained.</p><table><tr><th>Segmented attempt</th><th>Status</th><th>Position m</th><th>Force SI</th><th>Grid covariance</th><th>Observation covariance</th><th>Cross covariance</th><th>Dynamic covariance</th><th>Prediction / noise</th><th>Objective difference / resolution</th></tr>')
    for pair in pairs:
        keys=('segmented_attempt','status','maximum_position_difference_m','maximum_force_difference_si','maximum_normalized_covariance_difference','maximum_normalized_observation_covariance_difference','maximum_normalized_cross_covariance_difference','maximum_normalized_dynamic_covariance_difference','maximum_prediction_noise_ratio')
        content.append('<tr>'+''.join('<td>'+esc(str(pair.get(k,'')))+'</td>' for k in keys)+'<td>'+esc(str(pair.get('objective_difference',''))+' / '+str(pair.get('measured_objective_resolution','')))+'</td></tr>')
        if pair.get('error'):content.append('<tr><td colspan="10">'+esc(pair['error'])+'</td></tr>')
    content.extend(['</table><h2>Gates</h2><pre>'+esc(json.dumps(gates,indent=2))+'</pre><h2>Limits</h2><ul>',*['<li>'+esc(x)+'</li>' for x in report['limitations']],'</ul>'])
    (root/'index.html').write_text('\n'.join(content))
    return {'status':'complete' if terminal==68 else 'partial','report':str(root/'report.json'),'html':str(root/'index.html'),'terminal_attempts':terminal,'release_ready':ready}
