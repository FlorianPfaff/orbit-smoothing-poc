"""Execute the fixed correctness gates serially before any v4 benchmark fit."""
from __future__ import annotations
from dataclasses import asdict
import json,os,subprocess,sys
from pathlib import Path
import xml.etree.ElementTree as ET
from . import protocol as p

ORIGINAL=('tests/test_numerics_native_qr.py','tests/test_numerics_original_objective.py','tests/test_numerics_mean_residual.py','tests/test_numerics_derivatives.py','tests/test_numerics_geometry_precision.py','tests/test_numerics_synthetic_force_arithmetic.py')
CORRECTIONS=('tests/test_numerics_query_precision.py','tests/test_numerics_reference_precision.py','tests/test_numerics_precise_residual.py','tests/test_numerics_precise_objective.py','tests/test_numerics_light_time_precision.py')
STRUCTURAL=('tests/test_segmented_native_qr.py','tests/test_segmented_graph.py','tests/test_segmented_linear_system.py','tests/test_segmented_solver.py','tests/test_segmented_tangent.py','tests/test_segmented_diagnostics.py','tests/test_segmented_linearization_gate.py','tests/test_numerics_optimizer.py','tests/test_segmented_protocol.py','tests/test_segmented_multiday.py','tests/test_segmented_validation.py','tests/test_segmented_products.py','tests/test_segmented_supervisor.py','tests/test_segmented_backend.py','tests/test_segmented_engineering.py')
GATE1=('native-tests','correction-tests','synthetic-refinement-log_drag_ou','synthetic-refinement-pulses','flight-refinement','eccentric-24h-refinement','objective-log_drag_ou','objective-pulses','nuisance-replay','nuisance-replay-candidate1-point012')
STAGES=GATE1+('segmented-native-tangent','segmented-structural','linearization-log_drag_ou','linearization-pulses')
SCRIPTS=('scripts/validate_numerics_synthetic_refinement.py','scripts/validate_numerics_flight_refinement.py','scripts/validate_numerics_objective.py','scripts/validate_numerics_nuisance.py','scripts/validate_segmented_linearization.py')
PROTECTED=ORIGINAL+CORRECTIONS+SCRIPTS[:-1]
REFERENCE_PINS_SHA='5b9d252353acf55c21993017f465f6d973e2dc859209b93eefaf2dc2c5083699'


def original_input_hashes():
    from .validation_reference import ORIGINAL_INPUT_HASHES
    return dict(ORIGINAL_INPUT_HASHES)


def verify_inputs(config,manifest,project):
    """Original14 bytes, protected gate sources and all glob-visible data."""
    from ..comparison.backend import _preparation
    from .multiday import native_data_inventory
    path=p.verify_artifact(config.validation_inputs,project);value=p.read_json(path)
    if set(value)!={'schema','input_artifacts','source_reference','data_directories','dependencies'} or value['schema']!='orbit-poc-segmented-validation-inputs-v1':raise ValueError('Unknown validation input schema')
    inputs=value['input_artifacts'];expected=original_input_hashes()
    if set(inputs)!=set(expected) or len(inputs)!=14:raise ValueError('Validation requires all14 distinct original inputs')
    for role,item in inputs.items():
        if item.get('sha256')!=expected[role]:raise ValueError('Original validation input substituted: '+role)
        p.verify_artifact(item,project)
    reference=p.read_json(p.verify_artifact(config.corrected_reference,project))
    freeze=p.read_json(p.verify_artifact(value['source_reference'],project))
    if value['source_reference']['sha256']!=reference['identity']['source_freeze_sha256']:raise ValueError('Protected source reference is not corrected c24')
    original=freeze['source']['files'];source=Path(manifest['runtimes']['segmented']['source_root'])
    for name in PROTECTED:
        if p.file_hash(source/name)!=original.get(name):raise ValueError('Original validation source changed: '+name)
    if not value['dependencies'] or not value['data_directories']:raise ValueError('Validation dependency closure is missing')
    p.verify_nested_artifacts(value['dependencies'])
    directories={str(Path(item['root']).absolute()):item for item in value['data_directories']}
    if len(directories)!=len(value['data_directories']):raise ValueError('Duplicate validation data inventory')
    for item in directories.values():
        if native_data_inventory(item['root'])!=item:raise ValueError('Validation native data membership changed')
    for role in ('density_request','pulse_request','full_day_request'):
        request=p.read_json(p.verify_artifact(inputs[role],project));p.verify_nested_artifacts(request['estimation_inputs']);prepared=_preparation(request)
        if str((Path(prepared['output_dir'])/'data').absolute()) not in directories:raise ValueError('Unpinned native request data tree')
    flight=p.read_json(p.verify_artifact(inputs['flight_prepared'],project));p.verify_nested_artifacts(flight['estimation_inputs'])
    if str((Path(flight['output_dir'])/'data').absolute()) not in directories:raise ValueError('Unpinned flight native data tree')
    # Preserve exact original XML: canonical aliases must be available on the
    # execution host. We never rewrite a historical profile to easier inputs.
    for role,prefix in (('old_nuisance_replay','old'),('candidate1_nuisance_replay','new')):
        raw=p.verify_artifact(inputs[role],project).read_bytes()
        if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('Replay XML entities forbidden')
        tree=ET.fromstring(raw)
        for tag,suffix in (('inputfileVariational','variational'),('inputfileNumericsReferenceParameters','reference'),('inputfileLogDensity','density')):
            values=[(n.text or '').strip() for n in tree.iter(tag)]
            if not values or any(p.file_hash(Path(v))!=inputs[prefix+'_replay_'+suffix]['sha256'] for v in values):raise ValueError('Original replay XML physical input differs')
    return value


def command(stage,inputs,runtime,output):
    """Allowlisted argv; no command text or success flags come from input JSON."""
    if stage not in STAGES:raise ValueError('Unknown validation stage')
    source=Path(runtime['source_root']);output=Path(output);binary=runtime['native']['path'];python=runtime['python']['path'];a=inputs['input_artifacts']
    path=lambda role:str(p.verify_artifact(a[role]))
    suites={'native-tests':ORIGINAL,'correction-tests':CORRECTIONS,'segmented-native-tangent':('tests/test_segmented_native_tangent.py',),'segmented-structural':STRUCTURAL}
    if stage in suites:return [python,'-m','pytest','-q','-s','-p','no:cacheprovider','--basetemp='+str(output/'pytest-temp'),'--junitxml='+str(output/'tests.xml'),*[str(source/f) for f in suites[stage]]]
    if stage.startswith('linearization-'):
        role='density_request' if stage.endswith('log_drag_ou') else 'pulse_request'
        return [python,str(source/SCRIPTS[-1]),'--request',path(role),'--binary',binary,'--solver',runtime['segmented_solver']['path'],'--initial-state-from',path('initial_state'),'--output',str(output/'result')]
    if stage.startswith('synthetic-refinement-') or stage=='eccentric-24h-refinement':
        role='full_day_request' if stage=='eccentric-24h-refinement' else 'density_request' if stage.endswith('log_drag_ou') else 'pulse_request'
        return [python,str(source/SCRIPTS[0]),'--request',path(role),'--binary',binary,'--output',str(output/'result')]
    if stage=='flight-refinement':return [python,str(source/SCRIPTS[1]),'--prepared',path('flight_prepared'),'--binary',binary,'--output',str(output/'result')]
    if stage.startswith('objective-'):
        role='density_request' if stage.endswith('log_drag_ou') else 'pulse_request'
        return [python,str(source/SCRIPTS[2]),'--request',path(role),'--native-binary',binary,'--initial-state-from',path('initial_state'),'--output',str(output/'result')]
    role='old_nuisance_replay' if stage=='nuisance-replay' else 'candidate1_nuisance_replay'
    return [python,str(source/SCRIPTS[3]),'--source-profile',path(role),'--native',binary,'--output',str(output/'result'),'--allow-floor-limited']


def worker(job,directory):
    """Called only inside the pinned, resource-supervised validation worker."""
    runtime=job['runtime'];inputs=p.read_json(p.verify_artifact(job['validation_inputs']))
    for key in ('native','python','segmented_solver'):p.verify_artifact(runtime[key])
    for item in job['sources'].values():p.verify_artifact(item)
    args=command(job['stage'],inputs,runtime,directory)
    if args!=job['argv']:raise ValueError('Validation command differs from fixed registry')
    env=dict(os.environ,PYTHONPATH=str(Path(runtime['source_root'])/'src'),ORBIT_POC_V31_NATIVE=runtime['native']['path'],ORBIT_POC_GROOPS=runtime['native']['path'],ORBIT_POC_CORRECTNESS_NATIVE=runtime['native']['path'],ORBIT_POC_SEGMENTED_GROOPS=runtime['native']['path'],ORBIT_POC_SEGMENTED_SOLVER=runtime['segmented_solver']['path'],ORBIT_POC_SEGMENTED_SOLVER_SHA256=runtime['segmented_solver']['sha256'])
    completed=subprocess.run(args,cwd=runtime['source_root'],env=env,check=False)
    return {'status':'complete' if completed.returncode==0 else 'failed','returncode':completed.returncode,'argv':args}


def junit(path,stage):
    from .report import fixed_test_inventory
    root=ET.parse(path).getroot();cases=root.findall('.//testcase')
    inventory=[{'classname':x.get('classname',''),'name':x.get('name','')} for x in cases]
    if not cases or len({(x['classname'],x['name']) for x in inventory})!=len(cases) or any(x.find('failure') is not None or x.find('error') is not None or x.find('skipped') is not None for x in cases):raise ValueError('Validation JUnit failed, skipped, empty or duplicated')
    if stage in ('native-tests','correction-tests'):
        key='original_native_tests' if stage=='native-tests' else 'correctness_tests'
        if inventory!=fixed_test_inventory(key):raise ValueError('Original test inventory changed')
    if stage=='segmented-native-tangent' and len(cases)!=3:raise ValueError('Native tangent test inventory changed')
    if stage=='segmented-structural':
        expected={Path(f).stem for f in STRUCTURAL}
        found={x['classname'].split('.')[-1] for x in inventory}
        if found!=expected:raise ValueError('Structural test suite omitted a required file')
    return {'tests':len(cases),'inventory':inventory,'junit':p.artifact(path)}


def check_result(stage,directory,inputs,manifest,reference):
    """Inspect actual outputs after command success; no logged sigma proxy."""
    from .report import objective_validation,replay_validation,number
    root=Path(directory)/'result'
    if stage in ('native-tests','correction-tests','segmented-native-tangent','segmented-structural'):return junit(Path(directory)/'tests.xml',stage)
    if 'refinement' in stage:
        path=root/'result.json';value=p.read_json(path);signals=value.get('native_signals',{}).get('signals',[])
        if value.get('passed') is not True or value.get('status')!='complete' or value.get('binary_sha256')!=manifest['runtimes']['segmented']['native']['sha256'] or not signals or any(not number(x.get('maximum_fraction_of_sigma')) or not 0<=x['maximum_fraction_of_sigma']<.01 for x in signals) or any(not number(x) or not 0<=x<3e-5 for x in value.get('metrics',{}).values()):raise ValueError('Unchanged numerical refinement failed')
        if not value.get('metrics'):raise ValueError('Refinement has no measurements')
        return {'result':p.artifact(path),'maximum_fraction_of_sigma':max(x['maximum_fraction_of_sigma'] for x in signals)}
    if stage.startswith('objective-'):
        path=root/'validation.json';method='groops_log_drag_ou' if stage.endswith('log_drag_ou') else 'groops_pulses'
        return {'result':p.artifact(path),'accepted_scales':objective_validation(p.artifact(path),method,manifest,Path.cwd())}
    if stage.startswith('nuisance-replay'):
        path=root/'receipt.json';value=p.read_json(path);prefix='old' if stage=='nuisance-replay' else 'new';a=inputs['input_artifacts'];original=reference['nuisance_replays'][stage]
        physical={key:{**a[prefix+'_replay_'+key]} for key in ('density','reference','variational')}
        source=a['old_nuisance_replay' if prefix=='old' else 'candidate1_nuisance_replay']
        # Canonical paths can differ from the host artifact path but remain
        # identical in the original and executed XML.
        tree=ET.parse(p.verify_artifact(source))
        for tag,key in (('inputfileVariational','variational'),('inputfileNumericsReferenceParameters','reference'),('inputfileLogDensity','density')):physical[key]['execution_path']=tree.find('.//'+tag).text.strip()
        row={'receipt':p.artifact(path),'source_profile':source,'executed_profile':p.artifact(root/'profile.xml'),'physical_inputs':physical,'provenance':original['provenance'],'status':'strict_converged','floor_limited':False,'raw_update_m':(value.get('profile') or {}).get('maximum_update_m')}
        return {'result':p.artifact(path),'raw_update_m':replay_validation(row,original,manifest,Path.cwd()),'strict':True}
    path=root/'validation.json';value=p.read_json(path)
    if value.get('schema')!='orbit-poc-segmented-linearization-gate-v1' or value.get('passed') is not True or value.get('source_sha256')!=manifest['runtimes']['segmented']['source_sha256'] or value.get('native',{}).get('sha256')!=manifest['runtimes']['segmented']['native']['sha256'] or value.get('solver',{}).get('sha256')!=manifest['runtimes']['segmented']['segmented_solver']['sha256'] or value.get('physical_evaluations')!=1 or value.get('accepted_fit_covariance') is not False:raise ValueError('Actual native linearization identity failed')
    if value.get('map_tolerance_posterior_sd')!=1e-7 or value.get('relative_covariance_tolerance')!=1e-8 or value.get('normalized_residual_energy_tolerance')!=2e-12 or value.get('damping_values')!=[0.,1e-3,1e3]:raise ValueError('Linearization gate thresholds changed')
    oracle=value['comparison'].get('independent_gtsam',{})
    if oracle.get('version')!='4.2' or oracle.get('elimination_api')!='JacobianFactor.eliminate(Ordering) -> EliminateQR' or not isinstance(oracle.get('rows'),int) or not isinstance(oracle.get('columns'),int) or min(oracle['rows'],oracle['columns'])<=0:raise ValueError('Independent actual-row GTSAM QR oracle is missing')
    for key,limit in (('maximum_equality_substitution_residual',2e-12),('maximum_map_discrepancy_posterior_sd',1e-7),('covariance_relative_error',1e-8),('normalized_residual_energy_difference',2e-12)):
        if not number(oracle.get(key)) or not 0<=oracle[key]<limit:raise ValueError('Independent actual-row GTSAM criterion failed')
    if not number(oracle.get('full_residual_energy')) or oracle['full_residual_energy']<0:raise ValueError('Independent GTSAM residual energy is missing')
    p.verify_artifact(oracle['original_rows_and_result'])
    profiles=value['comparison']['profiles']
    if [x['segment_seconds'] for x in profiles]!=[3600,14400]:raise ValueError('Linearization cut profiles changed')
    maximum_map=maximum_cov=maximum_residual=maximum_equality=0.
    for profile in profiles:
        if [x['damping'] for x in profile['trials']]!=[0.,1e-3,1e3] or profile.get('covariance_optimization_damping')!=0 or profile.get('covariance_all_original_coordinates') is not True:raise ValueError('Linearization trial/covariance policy changed')
        if not number(profile.get('covariance_relative_error')) or not 0<=profile['covariance_relative_error']<1e-8:raise ValueError('Small covariance criterion failed')
        maximum_cov=max(maximum_cov,profile['covariance_relative_error'])
        for trial in profile['trials']:
            values=[trial.get(k) for k in ('maximum_map_discrepancy_posterior_sd','normalized_residual_energy_difference','normalized_orthogonal_residual_energy_difference')]
            if not all(number(x) and x>=0 for x in values) or values[0]>=1e-7 or max(values[1:])>=2e-12:raise ValueError('Small MAP/lift residual criterion failed')
            equality=trial.get('maximum_equality_backward_error')
            if trial.get('equality_residual_normalization')!='max_i |d_i-E_i*x| / (|d_i|+sum_j |E_ij*x_j|); zero denominator gives zero':raise ValueError('Lift residual normalization changed')
            if not number(equality) or not 0<=equality<2e-12:raise ValueError('True lifted equality residual criterion failed')
            maximum_equality=max(maximum_equality,equality)
            maximum_map=max(maximum_map,values[0]);maximum_residual=max(maximum_residual,*values[1:])
    p.verify_nested_artifacts(value)
    return {'result':p.artifact(path),'maximum_map_posterior_sd':maximum_map,'maximum_covariance_relative_error':maximum_cov,'maximum_normalized_energy_difference':maximum_residual,'maximum_lift_residual':maximum_equality,'independent_equality_substitution_residual':oracle['maximum_equality_substitution_residual'],'lift_residual_scope':'Native equality backward error of each actual constrained QR trial; energy accounting is separate'}


def execution_context(config,root,project,manifest=None):
    """Run original gates before costly new data generation, without a partial manifest."""
    plan=p.freeze_plan(config,root,project)
    runtimes={key:p.verify_runtime(getattr(config,key+'_runtime'),project) for key in ('dense','segmented')}
    if any(item['source_sha256']!=plan['source']['sha256'] for item in runtimes.values()) or not runtimes['segmented']['segmented_solver']:raise ValueError('Validation requires the frozen shared v4 source and segmented solver')
    reference=p.read_json(p.verify_artifact(config.corrected_reference,project))
    if reference.get('scientific_correctness_gate_passed') is not True or reference.get('native_sha256')!=runtimes['dense']['native']['sha256']:raise ValueError('Corrected dense audit identity differs')
    if manifest is not None and (manifest.get('plan_hash')!=plan['plan_hash'] or manifest.get('runtimes')!=runtimes):raise ValueError('Benchmark does not match executed validation source/plan/runtime')
    value={'schema':'orbit-poc-segmented-validation-context-v1','plan_hash':plan['plan_hash'],'runtimes':runtimes,'validation_inputs':p.artifact(p.verify_artifact(config.validation_inputs,project)),'corrected_reference':p.artifact(p.verify_artifact(config.corrected_reference,project)),'scope':'Original fixed gates and v4 native/structural gates before new benchmark preparation; not a prepared68-input manifest'}
    value['validation_context_hash']=p.canonical_hash(value);path=root/'validation'/'context.json'
    if path.exists() and p.read_json(path)!=value:raise ValueError('Validation context changed; preserve the prior campaign')
    if not path.exists():p.write_json(path,value)
    return value


def frozen_plan(config,manifest,root,project):
    inputs=verify_inputs(config,manifest,project);runtime=manifest['runtimes']['segmented'];source=Path(runtime['source_root'])
    names=sorted(set(ORIGINAL+CORRECTIONS+STRUCTURAL+SCRIPTS+('tests/test_segmented_native_tangent.py',)))
    value={'schema':'orbit-poc-segmented-validation-plan-v1','validation_context_hash':manifest['validation_context_hash'],'runtime':runtime,'validation_inputs':p.artifact(p.verify_artifact(config.validation_inputs,project)),'sources':{name:p.artifact(source/name) for name in names},'stages':list(STAGES),'gate1':list(GATE1),'resources':asdict(config.resources),'corrected_reference':p.artifact(p.verify_artifact(config.corrected_reference,project))}
    value=json.loads(json.dumps(value));value['plan_hash']=p.canonical_hash(value);path=root/'validation'/'plan.json'
    if path.exists() and p.read_json(path)!=value:raise ValueError('Validation plan/input/source changed; choose a new campaign')
    if not path.exists():p.write_json(path,value)
    return value,inputs


def verify_attempt(pipeline,plan,inputs,manifest,reference):
    if pipeline.get('plan_hash')!=plan['plan_hash'] or [x['name'] for x in pipeline.get('steps',[])]!=list(STAGES):raise ValueError('Validation attempt plan or ordered inventory changed')
    evidence={}
    for step in pipeline['steps']:
        if step.get('status')!='passed':raise ValueError('Prebenchmark gate not passed: '+step['name'])
        directory=Path(step['directory']);result=p.read_json(p.verify_artifact(step['execution']))
        if result.get('status')!='complete' or result.get('returncode')!=0 or result.get('harness_execution',{}).get('owned_process_group_cleaned') is not True:raise ValueError('Gate execution failed or cleanup unverified')
        expected=command(step['name'],inputs,plan['runtime'],directory)
        request=p.read_json(directory/'request.json')
        expected_job={'operation':'validate_command','stage':step['name'],'validation_inputs':plan['validation_inputs'],'runtime':plan['runtime'],'sources':plan['sources'],'argv':expected,'plan_hash':plan['plan_hash'],'validation_context_hash':manifest['validation_context_hash']}
        if result.get('argv')!=expected or request!=expected_job or result['harness_execution'].get('runtime')!=plan['runtime']:raise ValueError('Gate command attribution changed')
        checked=check_result(step['name'],directory,inputs,manifest,reference)
        if checked!=step.get('evidence'):raise ValueError('Gate output bytes or measurements changed')
        evidence[step['name']]=checked
    return evidence


def require_passed(config,manifest,root,project):
    context=execution_context(config,root,project,manifest);plan,inputs=frozen_plan(config,context,root,project)
    latest=p.read_json(root/'validation'/'latest.json');path=p.verify_artifact(latest['pipeline']);pipeline=p.read_json(path)
    evidence=verify_attempt(pipeline,plan,inputs,context,p.read_json(p.verify_artifact(config.corrected_reference,project)))
    if pipeline.get('status')!='passed':raise ValueError('Validation did not finish successfully')
    return {'status':'passed','pipeline':p.artifact(path),'plan_hash':plan['plan_hash'],'checks':evidence,'scope':'Executed prebenchmark gates only; paired nonlinear/flight and original150 completion remain separate.'}


def validate(config,output_dir=None,*,project=None):
    config.validate();project=Path(project or p.project_root()).resolve();root=p.resolve(output_dir or config.output_dir,project)
    with p.exclusive(root):
        manifest=execution_context(config,root,project);plan,inputs=frozen_plan(config,manifest,root,project);base=root/'validation';base.mkdir(exist_ok=True)
        old=sorted(base.glob('attempt-*/pipeline.json'))
        if old:
            previous=p.read_json(old[-1])
            unsafe=previous.get('status')=='running' or any(x.get('status') in ('running','interrupted_or_failed') for x in previous.get('steps',[])) or any('execution' in x and p.read_json(p.verify_artifact(x['execution'])).get('harness_execution',{}).get('owned_process_group_cleaned') is not True for x in previous.get('steps',[]))
            if unsafe:raise p.NotReady('Previous validation has unverified owned cleanup; preserve and audit it before another campaign')
        directory=base/('attempt-'+str(len(old)+1).zfill(4));directory.mkdir();path=directory/'pipeline.json'
        journal={'schema':'orbit-poc-segmented-validation-run-v1','status':'running','plan_hash':plan['plan_hash'],'validation_context_hash':manifest['validation_context_hash'],'started_at':p.timestamp(),'steps':[{'name':name,'status':'not_run','directory':str(directory/name)} for name in STAGES]}
        reference=p.read_json(p.verify_artifact(config.corrected_reference,project));p.write_json(path,journal)
        try:
            for step in journal['steps']:
                if step['name']==STAGES[len(GATE1)] and any(x['status']!='passed' for x in journal['steps'][:len(GATE1)]):break
                execution_context(config,root,project);frozen_plan(config,manifest,root,project);p.admission(config,root,project)
                folder=Path(step['directory']);folder.mkdir();args=command(step['name'],inputs,plan['runtime'],folder)
                job={'operation':'validate_command','stage':step['name'],'validation_inputs':plan['validation_inputs'],'runtime':plan['runtime'],'sources':plan['sources'],'argv':args,'plan_hash':plan['plan_hash'],'validation_context_hash':manifest['validation_context_hash']}
                p.write_json(folder/'request.json',job);step.update(status='running',started_at=p.timestamp());p.write_json(path,journal)
                result=p._execute_job(job,folder,plan['runtime'],config.resources);p.write_json(folder/'execution.json',result);step['execution']=p.artifact(folder/'execution.json')
                try:
                    if result.get('status')!='complete' or result.get('returncode')!=0 or result.get('harness_execution',{}).get('owned_process_group_cleaned') is not True or result.get('argv')!=args:raise ValueError('Gate command or owned cleanup failed')
                    step.update(status='passed',evidence=check_result(step['name'],folder,inputs,manifest,reference))
                except (OSError,ValueError,RuntimeError,KeyError,TypeError) as error:step.update(status='failed',error=type(error).__name__+': '+str(error))
                step['finished_at']=p.timestamp();p.write_json(path,journal)
                if result.get('status')=='interrupted' or result.get('harness_execution',{}).get('owned_process_group_cleaned') is not True:break
        except BaseException as error:
            journal['error']=type(error).__name__+': '+str(error)
            for step in journal['steps']:
                if step['status']=='running':step.update(status='interrupted_or_failed',error=journal['error'],finished_at=p.timestamp())
        finally:
            journal.update(status='passed' if all(x['status']=='passed' for x in journal['steps']) else 'failed',finished_at=p.timestamp());p.write_json(path,journal);p.write_json(base/'latest.json',{'pipeline':p.artifact(path),'plan_hash':plan['plan_hash']})
        return {'status':journal['status'],'pipeline':str(path),'passed_stages':sum(x['status']=='passed' for x in journal['steps']),'planned_stages':len(STAGES),'benchmark_authorized':journal['status']=='passed','release_ready':False}
