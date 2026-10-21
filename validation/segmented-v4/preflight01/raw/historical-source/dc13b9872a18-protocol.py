"""Freeze and run the exact v4 matrix without replacing failed attempts."""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime,timezone
import json,os,signal,socket,subprocess,time,shutil
from pathlib import Path
from orbit_poc.comparison.protocol import canonical_hash,file_hash,source_snapshot,validate_estimation_inputs,write_json,read_json
from .config import Artifact,FRESH_SEEDS,METHODS,PROFILES,is_digest

TERMINAL={'complete','failed','blocked','timeout','memory_limit','disk_limit','interrupted','nonconverged','unresolved_rank','invalid_covariance'}
FORBIDDEN={'truth','evaluation_inputs','calibration_inputs','reference_orbit','slr_validation'}
IDENTITIES=('force_model_hash','measurement_model_hash','preprocessing_hash','mask_hash')
REPORTING_INPUTS=('release_evidence','original150_report','original150_manifest','original150_plan')
class NotReady(RuntimeError):pass

def timestamp():return datetime.now(timezone.utc).isoformat()
def project_root():return Path(__file__).resolve().parents[3]
def resolve(path,project):return (Path(path) if Path(path).is_absolute() else Path(project)/path).resolve()
def artifact(path):
    p=Path(path).resolve();return {'path':str(p),'sha256':file_hash(p)}
def verify_artifact(item,project=None):
    d=asdict(item) if isinstance(item,Artifact) else item
    if not d.get('path') or not is_digest(d.get('sha256')):raise NotReady('A required artifact is not pinned')
    p=resolve(d['path'],project or project_root())
    if not p.is_file() or file_hash(p)!=d['sha256']:raise NotReady('Missing or changed pinned artifact: '+str(p))
    return p

def mask(duration,coverage):
    return {'cadence_seconds':30,'time_scale':'UTC','duration_seconds':duration*3600,
        'intervals_seconds':[[d*86400+39600,d*86400+46800] for d in range(duration//24)] if coverage=='blackout' else []}
def parameters(method):
    return ({'interval_seconds':1200.,'sigma_velocity_m_s':1e-4,'frame':'CRF'} if method=='groops_pulses' else
        {'knot_seconds':60.,'tau_seconds':1800.,'sigma_log_density':.1,'interpolation':'linear_log_density','initial_prior':'stationary_ou','empirical_acceleration':False})
def planned_cases():
    result=[]
    for orbit,seed in FRESH_SEEDS.items():
        for atmosphere,coverage in (('quiet','normal'),('disturbed','blackout')):
            generation_id=f'{orbit}-{atmosphere}-{seed}-continuous72h'
            for method in METHODS:
                family_id=f'{orbit}-{atmosphere}-{coverage}-{method}'
                for hours in (24,48,72):
                    case={'orbit':orbit,'seed':seed,'atmosphere':atmosphere,'coverage':coverage,'epoch':'2024-05-10T00:00:00','duration_hours':hours,'cadence':30.,'mask':mask(hours,coverage),'truth_model':'tudat_independent_central_j2_exponential_gnss'}
                    result.append({'case_id':f'{family_id}-{hours}h','family_id':family_id,'generation_id':generation_id,'stage':'synthetic','method':method,'case':case,'parameters':parameters(method)})
    for coverage in ('normal','blackout'):
        for method in METHODS:
            name=f'flight-2024-04-24-{coverage}-{method}'
            flight_mask={k:v for k,v in mask(24,coverage).items() if k!='duration_seconds'}
            flight_parameters=({k:v for k,v in parameters(method).items() if k!='frame'} if method=='groops_pulses' else {**parameters(method),'tau_seconds':7200.,'sigma_log_density':.3})
            result.append({'case_id':name,'family_id':name,'generation_id':None,'stage':'flight','method':method,'case':{'date':'2024-04-24','duration_hours':24.,'coverage':coverage,'mask':flight_mask},'parameters':flight_parameters})
    assert len(result)==28 and len({r['case_id'] for r in result})==28
    return result

def attempts(cases=None):
    result=[]
    for i,c in enumerate(cases or planned_cases()):
        choices=PROFILES if c['case']['duration_hours']==24 else PROFILES[:2]
        choices=choices[i%len(choices):]+choices[:i%len(choices)]
        for profile in choices:result.append({'attempt_id':c['case_id']+'--'+profile,'case_id':c['case_id'],'profile':profile,'order':len(result)})
    assert len(result)==68
    return result

@contextmanager
def exclusive(root):
    import fcntl
    root.mkdir(parents=True,exist_ok=True)
    with (root/'.segmented.lock').open('a') as stream:
        try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as e:raise NotReady('Another segmented process holds this output directory') from e
        yield

def seed_inventory(config,project):
    if not config.prior_seed_protocols:raise NotReady('Pin prior protocols before declaring610000/610001 unused')
    used=set(range(42,62))|set(range(300000,300006))|set(range(400000,400050))|set(range(500000,500005))|{510000,510001}
    def visit(v):
        if isinstance(v,dict):
            for k,x in v.items():
                if k=='seed' and type(x) is int:used.add(x)
                if 'seeds' in k:
                    collection=x.values() if isinstance(x,dict) else x if isinstance(x,list) else []
                    used.update(y for y in collection if type(y) is int)
                visit(x)
        elif isinstance(v,list):
            for x in v:visit(x)
    records=[]
    for item in config.prior_seed_protocols:
        p=verify_artifact(item,project);visit(read_json(p));records.append(artifact(p))
    if used&set(FRESH_SEEDS.values()):raise ValueError('A fresh v4 seed already appears in a pinned prior protocol')
    return {'fresh_seeds':FRESH_SEEDS,'checked_protocols':records,'overlap':[],'scope':'Pinned protocols and published historical ranges; shared prefixes/coverage are not independent trials.'}

def loader_dependencies(loader,executable,directory):
    """Resolve ELF dependencies with the pinned loader in the current namespace."""
    env={k:v for k,v in os.environ.items() if not k.startswith('LD_')}
    env['LD_LIBRARY_PATH']=str(directory)
    env['LD_TRACE_LOADED_OBJECTS']='1'
    result=subprocess.run([str(loader),'--list',str(executable)],env=env,capture_output=True,text=True,timeout=30,check=True)
    paths=set()
    for line in result.stdout.splitlines():
        line=line.strip()
        if not line:continue
        if line.startswith('linux-vdso.so.1 '):continue
        value=line.split('=>',1)[-1].strip().split(' (',1)[0]
        if not value.startswith('/') or not Path(value).is_file():raise ValueError('Unresolved or unknown native loader dependency: '+line)
        paths.add(str(Path(value).resolve()))
    if not paths:raise ValueError('Pinned loader returned no file dependencies')
    return paths


def verify_library_manifest(runtime,project):
    """Complete file membership, ELF closure, and scientific wheel inventories."""
    from .multiday import native_data_inventory
    record=read_json(verify_artifact(runtime.library_manifest,project))
    if set(record)!={'schema','directory','files','loader','executables','runtime_trees'} or record['schema']!='orbit-poc-segmented-runtime-closure-v1':raise ValueError('Invalid complete runtime closure schema')
    directory=resolve(record['directory'],project);declared=set()
    if not record['files']:raise ValueError('Empty runtime library inventory')
    for item in record['files']:
        path=verify_artifact(item,project)
        declared.add(str(path))
    actual={str(path.resolve()) for path in directory.rglob('*') if path.is_file()}
    if declared!=actual:raise ValueError('Runtime library inventory must cover the complete directory')
    trees=record['runtime_trees']
    if set(trees)!={'python_environment','native_environment'}:raise ValueError('Full Python/native runtime tree inventories are required')
    invocation=Path(runtime.python.path) if Path(runtime.python.path).is_absolute() else Path(project)/runtime.python.path
    expected={'python_environment':invocation.parent.parent.resolve(),'native_environment':directory.parent}
    for role,artifact in trees.items():
        inventory=read_json(verify_artifact(artifact,project))
        if Path(inventory['root']).resolve()!=expected[role] or native_data_inventory(inventory['root'])!=inventory:raise ValueError('Complete scientific runtime tree changed: '+role)
    binaries={'native':runtime.native,'python':runtime.python}
    if runtime.segmented_solver.path:binaries['segmented_solver']=runtime.segmented_solver
    if set(record['executables'])!=set(binaries):raise ValueError('Native/solver/Python dependency closure is incomplete')
    loader=verify_artifact(record['loader'],project)
    for role,binary in binaries.items():
        measured=record['executables'][role]
        if set(measured)!={'executable','dependencies'} or measured['executable'].get('sha256')!=binary.sha256 or verify_artifact(measured['executable'],project)!=verify_artifact(binary,project):raise ValueError('Runtime closure identifies a different executable')
        dependencies={str(verify_artifact(item,project)) for item in measured['dependencies']}
        if not dependencies or dependencies!=loader_dependencies(loader,verify_artifact(binary,project),directory):raise ValueError('Actual loaded dependency closure differs: '+role)
    return {**record,'directory':str(directory)}


def verify_runtime(runtime,project):
    if not runtime.source_root or not runtime.source_sha256:raise NotReady('Pin the runtime source inventory')
    source=resolve(runtime.source_root,project)
    if not source.is_dir() or source_snapshot(source)['sha256']!=runtime.source_sha256:raise NotReady('Runtime source inventory changed')
    native=verify_artifact(runtime.native,project);python=verify_artifact(runtime.python,project)
    if not os.access(native,os.X_OK) or not os.access(python,os.X_OK):raise NotReady('Pinned runtime files must be executable')
    build=verify_artifact(runtime.build_manifest,project);build_record=read_json(build)
    native_hash=runtime.native.sha256
    declared=build_record.get('executable_sha256',build_record.get('binary_sha256',build_record.get('native_sha256',build_record.get('binary',{}).get('sha256'))))
    if declared!=native_hash:raise ValueError('Build manifest does not identify the pinned native binary')
    libraries=None
    if not runtime.library_manifest.path:raise NotReady('Pin the complete native/solver runtime library inventory')
    if runtime.segmented_solver.path and not os.access(verify_artifact(runtime.segmented_solver,project),os.X_OK):raise NotReady('Segmented solver must be executable')
    libraries=verify_library_manifest(runtime,project)
    invocation=Path(runtime.python.path)
    if not invocation.is_absolute():invocation=Path(project)/invocation
    invocation=invocation.parent.resolve()/invocation.name
    return {'source_root':str(source),'source_sha256':runtime.source_sha256,'native':artifact(native),'python':{'path':str(invocation),'sha256':runtime.python.sha256},'build_manifest':artifact(build),'libraries':libraries,'segmented_solver':artifact(verify_artifact(runtime.segmented_solver,project)) if runtime.segmented_solver.path else None}

def verify_nested_artifacts(value):
    if isinstance(value,dict):
        if 'path' in value and 'sha256' in value:verify_artifact(value)
        for child in value.values():verify_nested_artifacts(child)
    elif isinstance(value,list):
        for child in value:verify_nested_artifacts(child)

def _verify_request(request,case):
    if FORBIDDEN&request.keys():raise ValueError('Reference/evaluation inputs cannot enter fitting')
    if any(request.get(k)!=case[k] for k in ('stage','case','method','parameters')):raise ValueError('Prepared request differs from fixed case/physics')
    validate_estimation_inputs(request['estimation_inputs'],flight=case['stage']=='flight')
    verify_nested_artifacts(request['estimation_inputs'])
    if any(not is_digest(request.get(k)) for k in IDENTITIES):raise ValueError('Missing shared model/preprocessing identities')
    if request['mask_hash']!=canonical_hash(case['case']['mask']):raise ValueError('Mask identity differs')
    from orbit_poc.comparison.backend import _preparation
    prepared=_preparation(request)
    from .multiday import native_data_inventory
    inventory=prepared.get('native_data_inventory')
    if not inventory or inventory!=native_data_inventory(Path(prepared['output_dir'])/'data'):raise ValueError('Native data directory membership or bytes changed')
    if float(prepared.get('duration_hours',0))!=case['case']['duration_hours']:raise ValueError('Native preparation duration differs')
    if case['stage']=='synthetic':
        v=prepared.get('multiday_preparation',{})
        if v.get('generation_id')!=case['generation_id'] or v.get('continuous_source_hours')!=72 or v.get('prefix_hours')!=case['case']['duration_hours'] or v.get('mask_before_initialization') is not True:
            raise ValueError('Synthetic prefixes must derive from the declared continuous72h generation and remasked initialization')
    return prepared

def flight_normalization_proofs(request):
    """Normalize only the bias-file locations, after verifying their exact bytes."""
    proofs=[]
    for item in request['estimation_inputs']:
        if item.get('metadata',{}).get('kind')!='known_gnss_osb_datum_normalization':continue
        value=read_json(verify_artifact(item));biases=value.get('bias_inputs')
        if value.get('schema_version')!=1 or not isinstance(biases,list) or not biases:raise ValueError('Unknown original flight normalization ledger')
        for bias in biases:verify_artifact(bias)
        normalized={**value,'bias_inputs':[{k:v for k,v in bias.items() if k!='path'} for bias in biases]}
        proofs.append({'receipt':artifact(verify_artifact(item)),'bias_inputs':biases,'semantic_sha256':canonical_hash(normalized),'normalization':'Only bias_inputs[*].path removed after checking each file digest; formula, all correction rows, arc, hashes and policies retained'})
    return proofs


def shared_input_identity(request):
    proofs={x['receipt']['sha256']:x for x in flight_normalization_proofs(request)} if request['stage']=='flight' else {}
    rows=[]
    for item in request['estimation_inputs']:
        if item.get('metadata',{}).get('kind')=='native_preparation':continue
        sha=proofs[item['sha256']]['semantic_sha256'] if item['sha256'] in proofs else item['sha256']
        rows.append((item['role'],sha))
    return {**{k:request[k] for k in IDENTITIES},'inputs':sorted(rows)}


def flight_sources(config,project):
    """Read the four exact April24 requests already frozen by the original150."""
    catalog=read_json(verify_artifact(config.flight_input_catalog,project))
    if set(catalog)!={'schema','original_plan','original_manifest'} or catalog['schema']!='orbit-poc-segmented-flight-inputs-v1':raise ValueError('Unknown original flight input catalog')
    plan=read_json(verify_artifact(catalog['original_plan'],project));manifest=read_json(verify_artifact(catalog['original_manifest'],project))
    if plan.get('plan_hash')!=canonical_hash({k:v for k,v in plan.items() if k!='plan_hash'}) or manifest.get('manifest_hash')!=canonical_hash({k:v for k,v in manifest.items() if k!='manifest_hash'}) or manifest.get('plan_hash')!=plan['plan_hash'] or plan.get('attempts')!=manifest.get('attempts') or len(manifest.get('cases',[]))!=50 or len(manifest.get('attempts',[]))!=150:raise ValueError('Original flight plan/manifest identity differs')
    original_cases={c['case_id']:c for c in plan['cases']};result={}
    from ..comparison.backend import _preparation
    for case in (c for c in planned_cases() if c['stage']=='flight'):
        name=f"retained-april24-{case['case']['coverage']}-{case['method']}"
        matched=[c for c in manifest['cases'] if c['case_id']==name]
        if len(matched)!=1 or name not in original_cases:raise ValueError('Missing exact original April24 case')
        original=matched[0];planned=original_cases[name]
        if original.get('origin')!='retained_flight_control' or any(original.get(k)!=planned.get(k) for k in planned) or any(original.get(k)!=case[k] for k in ('case','stage','method','parameters')):raise ValueError('Original April24 case/settings changed')
        historical=original['historical_request'];raw=read_json(verify_artifact(historical,project))
        request={k:raw[k] for k in ('stage','case','method','parameters','estimation_inputs',*IDENTITIES)}
        if request!=original.get('fit_request') or any(request.get(k)!=case[k] for k in ('case','stage','method','parameters')) or original.get('lineage',{}).get('request',{}).get('sha256')!=historical['sha256']:raise ValueError('Original April24 historical request attribution differs')
        verify_nested_artifacts(request['estimation_inputs']);flight_normalization_proofs(request);prepared=_preparation(request)
        refs=[x for x in request['estimation_inputs'] if x.get('role')=='force_auxiliary' and x.get('metadata',{}).get('kind')=='native_preparation']
        if len(refs)!=1:raise ValueError('Original flight has no unique native preparation')
        result[case['case_id']]={'request':request,'prepared':prepared,'preparation_artifact':refs[0],
            'reference':{'historical_request':historical,'original_plan':catalog['original_plan'],'original_manifest':catalog['original_manifest']}}
    return result


def wrap_flight_request(original,directory):
    """Add only a v4 directory-closure wrapper; never regenerate flight inputs."""
    from .multiday import native_data_inventory
    prepared=original['prepared']
    if 'v4_flight_reference' in prepared or 'native_data_inventory' in prepared:raise ValueError('Historical flight preparation unexpectedly already wrapped')
    value={**prepared,'native_data_inventory':native_data_inventory(Path(prepared['output_dir'])/'data'),'v4_flight_reference':original['reference']}
    path=Path(directory)/'native-preparation.json'
    if path.exists() and read_json(path)!=value:raise ValueError('Existing flight wrapper changed')
    if not path.exists():write_json(path,value)
    old=original['preparation_artifact'];request=original['request']
    return {**request,'estimation_inputs':[{**x,**artifact(path)} if x==old else x for x in request['estimation_inputs']]}


def verify_flight_request(request,original):
    from ..comparison.backend import _preparation
    prepared=_preparation(request);reference=prepared.get('v4_flight_reference')
    if reference!=original['reference'] or {k:v for k,v in prepared.items() if k not in ('native_data_inventory','v4_flight_reference')}!=original['prepared']:raise ValueError('Flight wrapper changed original preparation')
    refs=[x for x in request['estimation_inputs'] if x.get('role')=='force_auxiliary' and x.get('metadata',{}).get('kind')=='native_preparation']
    if len(refs)!=1:raise ValueError('Flight wrapper has no unique preparation')
    expected={**original['request'],'estimation_inputs':[{**x,**{k:refs[0][k] for k in ('path','sha256')}} if x==original['preparation_artifact'] else x for x in original['request']['estimation_inputs']]}
    if request!=expected:raise ValueError('Flight request differs from exact original inputs/settings')


def freeze_plan(config,root,project):
    cases=planned_cases();execution_config={k:v for k,v in asdict(config).items() if k not in REPORTING_INPUTS};plan={'schema':'orbit-poc-segmented-plan-v1','config':json.loads(json.dumps(execution_config)),'source':source_snapshot(project),'cases':cases,'attempts':attempts(cases),'expected_attempts':68,'scope':'Numerical equivalence/reliability; no accuracy-superiority claim. Shared seeds and prefixes are not independent trials.'}
    plan['plan_hash']=canonical_hash(plan);p=root/'plan.json'
    if p.exists() and read_json(p)!=plan:raise ValueError('Frozen source/config/matrix changed; use a new output directory')
    if not p.exists():write_json(p,plan)
    return plan

def prepare(config,output_dir=None,*,project=None):
    config.validate();project=Path(project or project_root()).resolve();root=resolve(output_dir or config.output_dir,project)
    with exclusive(root):
        plan=freeze_plan(config,root,project)
        if (root/'manifest.json').exists():
            manifest=verify_manifest(config,root,project);return {'status':'prepared','expected_attempts':68,'manifest_hash':manifest['manifest_hash']}
        try:
            runtimes={k:verify_runtime(getattr(config,k+'_runtime'),project) for k in ('dense','segmented')}
            if any(v['source_sha256']!=plan['source']['sha256'] for v in runtimes.values()):raise ValueError('Both runtimes must use this pinned v4 adapter source with separate native binaries')
            if not runtimes['segmented']['segmented_solver']:raise NotReady('Pin the segmented native solver executable')
            reference=read_json(verify_artifact(config.corrected_reference,project))
            if reference.get('scientific_correctness_gate_passed') is not True or reference.get('native_sha256')!=runtimes['dense']['native']['sha256']:
                raise ValueError('Dense reference must identify the audited corrected v3.1 binary')
            seeds=seed_inventory(config,project);flight=flight_sources(config,project)
            if config.prepared_input_catalog.path:
                path=verify_artifact(config.prepared_input_catalog,project);catalog=read_json(path)
            elif config.preparation.generate_missing:
                verify_artifact({'path':config.preparation.tudat_python,'sha256':config.preparation.tudat_python_sha256},project)
                from .preparation import prepare_inputs
                catalog=prepare_inputs(config,plan,root,project,runtimes['segmented'],flight)
                path=root/'prepared-input-catalog.json';write_json(path,catalog)
            else:raise NotReady('Pin a prepared input catalog or explicitly enable native preparation')
            if set(catalog)!={'schema','entries'} or catalog['schema']!='orbit-poc-segmented-input-catalog-v1':raise ValueError('Unknown input catalog schema')
            entries={e['case_id']:e for e in catalog['entries']}
            if len(entries)!=len(catalog['entries']) or set(entries)!={c['case_id'] for c in plan['cases']}:raise ValueError('Catalog must contain exactly the28 fixed cases')
            frozen=[];shared={}
            for case in plan['cases']:
                entry=entries[case['case_id']]
                if set(entry)!={'case_id','request'}:raise ValueError('Catalog entries require only case_id and pinned request')
                p=verify_artifact(entry['request'],project);request=read_json(p);prepared=_verify_request(request,case)
                if case['stage']=='flight':verify_flight_request(request,flight[case['case_id']])
                identity=shared_input_identity(request);key=canonical_hash(case['case'])
                if key in shared and shared[key]!=identity:raise ValueError('Methods must share observations, masks, forces and preprocessing')
                shared[key]=identity
                frozen.append({**case,'fit_request':request,'request_artifact':artifact(p),'preparation_sha256':canonical_hash(prepared),'flight_normalization_semantics':flight_normalization_proofs(request) if case['stage']=='flight' else []})
            manifest={'schema':'orbit-poc-segmented-manifest-v1','plan_hash':plan['plan_hash'],'cases':frozen,'attempts':plan['attempts'],'runtimes':runtimes,'seed_inventory':seeds,'corrected_reference':artifact(verify_artifact(config.corrected_reference,project)),'prepared_input_catalog':artifact(path)}
            manifest['manifest_hash']=canonical_hash(manifest);write_json(root/'manifest.json',manifest)
            result={'status':'prepared','manifest_hash':manifest['manifest_hash'],'expected_attempts':68}
        except (OSError,ValueError,RuntimeError) as error:result={'status':'blocked','error':str(error),'expected_attempts':68,'plan_hash':plan['plan_hash']}
        write_json(root/'preparation-status.json',result);return result

def verify_manifest(config,root,project):
    plan=freeze_plan(config,root,project);manifest=read_json(root/'manifest.json')
    if manifest.get('manifest_hash')!=canonical_hash({k:v for k,v in manifest.items() if k!='manifest_hash'}) or manifest['plan_hash']!=plan['plan_hash'] or manifest['attempts']!=plan['attempts']:raise ValueError('Frozen manifest identity changed')
    if len(manifest['cases'])!=28:raise ValueError('Missing frozen cases')
    flight=flight_sources(config,project)
    for frozen,case in zip(manifest['cases'],plan['cases']):
        if any(frozen[k]!=case[k] for k in case):raise ValueError('Frozen case changed')
        request=read_json(verify_artifact(frozen['request_artifact'],project))
        if request!=frozen['fit_request'] or canonical_hash(_verify_request(request,case))!=frozen['preparation_sha256']:raise ValueError('Native preparation changed')
        if case['stage']=='flight':
            verify_flight_request(request,flight[case['case_id']])
            if frozen.get('flight_normalization_semantics')!=flight_normalization_proofs(request):raise ValueError('Flight normalization semantic proof changed')
    for name in ('dense','segmented'):
        if verify_runtime(getattr(config,name+'_runtime'),project)!=manifest['runtimes'][name]:raise ValueError('Frozen runtime changed')
    verify_artifact(manifest['corrected_reference'],project);verify_artifact(manifest['prepared_input_catalog'],project);seed_inventory(config,project)
    return manifest

def attempt_job(config,manifest,case,attempt):
    runtime=manifest['runtimes']['dense' if attempt['profile']=='dense_corrected' else 'segmented']
    job={**case['fit_request'],'id':attempt['attempt_id'],'kind':'fit','split':'segmented_v4','family_id':case['family_id'],'segmented_profile':attempt['profile'],'numerics_profile':'qr_lm_staged_jacobian','numerical_controls':asdict(config.controls),'source_hash':runtime['source_sha256'],'protocol_hash':manifest['manifest_hash'],'segmented_manifest_hash':manifest['manifest_hash'],'input_manifest_hash':canonical_hash(case['fit_request']['estimation_inputs']),'backend':{'groops_executable':runtime['native']['path'],'command_timeout_seconds':7200.,'retain_native_diagnostics':True,'diagnostic_native':manifest['runtimes']['segmented']['native'],'segmented_solver':runtime.get('segmented_solver'),'segmented_solver_executable':(runtime.get('segmented_solver') or {}).get('path')},'expected_native_binary_sha256':runtime['native']['sha256']}
    job['job_sha256']=canonical_hash(job);return job

def checkpoint(directory,job):
    index=read_json(directory/'result-record.json');result=read_json(verify_artifact(index['result']))
    if read_json(directory/'request.json')!=job or index.get('job_sha256')!=job['job_sha256'] or result.get('job_sha256')!=job['job_sha256'] or result.get('status')!=index.get('status') or result.get('status') not in TERMINAL:raise ValueError('Checkpoint attribution differs')
    for a in result.get('artifacts',[]):verify_artifact(a)
    return result

def admission(config,root,project):
    import psutil
    r=config.resources;p=verify_artifact(r.admission,project);d=read_json(p)
    if not r.reserved_cpu_ids or d.get('status')!='admitted' or d.get('hostname')!=socket.gethostname() or d.get('boot_id')!=Path('/proc/sys/kernel/random/boot_id').read_text().strip() or d.get('reserved_cpu_ids')!=list(r.reserved_cpu_ids) or d.get('conflicting_processes')!=[]:raise NotReady('A current-host admission and reserved CPU set are required')
    if psutil.virtual_memory().available<r.reserve_bytes+r.maximum_process_tree_rss_bytes or shutil.disk_usage(root).free<r.minimum_free_output_bytes:raise NotReady('Available memory/output storage is below frozen budgets')
    if not set(r.reserved_cpu_ids)<=os.sched_getaffinity(0):raise NotReady('Reserved CPUs unavailable to this process')
    native_paths={str(resolve(x.path,project)) for runtime in (config.dense_runtime,config.segmented_runtime) for x in (runtime.native,runtime.segmented_solver) if x.path}
    for process in psutil.process_iter(['pid','exe','name']):
        try:
            if process.pid!=os.getpid() and (process.info['exe'] in native_paths or process.info['name'] in {'groops','orbit-poc-segmented-qr','segmented_qr'}) and set(process.cpu_affinity())&set(r.reserved_cpu_ids):
                raise NotReady('Competing native process on reserved CPUs: '+str(process.pid))
        except (psutil.NoSuchProcess,psutil.AccessDenied):continue
    return artifact(p)

WORKER="""import json,sys,os
from pathlib import Path
source,request,result,cpus=sys.argv[1:]
sys.path.insert(0,str(Path(source)/'src'))
os.sched_setaffinity(0,json.loads(cpus))
job=json.loads(Path(request).read_text())
if job.get('operation')=='prepare_catalog':
 from orbit_poc.segmented.multiday import prepare_catalog
 v={'status':'prepared','catalog':prepare_catalog(job['cases'],job['output'],job['runtime'],job['options'])}
elif job.get('operation')=='prepare_component':
 from orbit_poc.segmented.preparation import worker
 v=worker(job,Path(result).parent)
elif job.get('operation')=='validate_command':
 from orbit_poc.segmented.validation import worker
 v=worker(job,Path(result).parent)
else:
 from orbit_poc.segmented.backend import fit_job
 v=fit_job(job,Path(result).parent)
Path(result).write_text(json.dumps(v,allow_nan=False,sort_keys=True))
"""
def _execute_job(job,directory,runtime,resources):
    from .supervisor import run_owned
    request=directory/'request.json';output=directory/'worker-result.json'
    env={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME') and not k.startswith(('ORBIT_POC_','LD_'))}
    env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1')
    if runtime['libraries']:env['LD_LIBRARY_PATH']=runtime['libraries']['directory']
    args=[runtime['python']['path'],'-s','-c',WORKER,runtime['source_root'],str(request),str(output),json.dumps(resources.reserved_cpu_ids)]
    try:
        measured=run_owned(args,python_executable=runtime['python']['path'],cwd=runtime['source_root'],env=env,log_path=directory/'worker.log',receipt_path=directory/'supervisor.json',timeout_seconds=7200.,max_process_tree_rss_bytes=resources.maximum_process_tree_rss_bytes,min_free_disk_bytes=resources.minimum_free_output_bytes,working_directory=directory)
    except BaseException as error:
        return {'status':'failed','error':'Owned supervisor failed: '+type(error).__name__+': '+str(error),'converged':False,'covariance_valid':False,'harness_execution':{'runtime':runtime,'owned_process_group_cleaned':False,'cleanup_complete':False}}
    clean=measured.get('owned_process_group_cleaned') is True
    if not clean:result={'status':'failed','error':'Owned process cleanup could not be verified','converged':False,'covariance_valid':False}
    elif measured.get('status') in ('timeout','memory_limit','disk_limit','interrupted'):result={'status':measured['status'],'error':'Frozen execution limit or interruption','converged':False,'covariance_valid':False}
    elif measured.get('returncode')!=0 or not output.exists():result={'status':'failed','error':'Worker exited without a valid result','converged':False,'covariance_valid':False}
    else:result=read_json(output)
    result['harness_execution']={**measured,'runtime':runtime,'log':artifact(directory/'worker.log'),'supervisor_receipt':artifact(directory/'supervisor.json'),'scope':'One bounded fit, validation stage or preparation component; dedicated subreaper and exact pidfd ownership; no speedup claim.'}
    return result

def run(config,output_dir=None,*,project=None,max_attempts=None):
    if max_attempts is not None and (type(max_attempts) is not int or max_attempts<1):raise ValueError('max_attempts must be positive')
    config.validate();project=Path(project or project_root()).resolve();root=resolve(output_dir or config.output_dir,project)
    with exclusive(root):
        if not (root/'manifest.json').exists():return {'status':'blocked','error':'Run prepare successfully first','expected_attempts':68}
        manifest=verify_manifest(config,root,project)
        from .validation import require_passed
        require_passed(config,manifest,root,project)
        cases={c['case_id']:c for c in manifest['cases']};executed=0
        for attempt in manifest['attempts']:
            directory=root/'attempts'/attempt['attempt_id'];job=attempt_job(config,manifest,cases[attempt['case_id']],attempt)
            if (directory/'result-record.json').exists():
                previous=checkpoint(directory,job)
                if previous.get('harness_execution',{}).get('owned_process_group_cleaned') is False:raise NotReady('Prior owned cleanup is unverified; preserve campaign and audit before further work')
                continue
            if directory.exists() and any(directory.iterdir()):raise NotReady('Interrupted/running attempt has no matching terminal checkpoint; no automatic retry')
            if max_attempts is not None and executed>=max_attempts:break
            admission(config,root,project);directory.mkdir(parents=True,exist_ok=True);write_json(directory/'request.json',job)
            runtime=manifest['runtimes']['dense' if attempt['profile']=='dense_corrected' else 'segmented']
            try:result=_execute_job(job,directory,runtime,config.resources)
            except Exception as error:result={'status':'failed','error':type(error).__name__+': '+str(error),'converged':False,'covariance_valid':False,'harness_execution':{'owned_process_group_cleaned':False}}
            if result.get('status') not in TERMINAL:result={'status':'failed','error':'Backend returned unknown/nonterminal status','converged':False,'covariance_valid':False,'backend_result':result}
            if result.get('job_sha256') not in (None,job['job_sha256']):raise ValueError('Backend job identity differs')
            result.update(job_sha256=job['job_sha256'],segmented_profile=attempt['profile'],segmented_manifest_hash=manifest['manifest_hash'])
            write_json(directory/'result.json',result);write_json(directory/'result-record.json',{'attempt_id':attempt['attempt_id'],'job_sha256':job['job_sha256'],'status':result['status'],'result':artifact(directory/'result.json')});executed+=1
            if result['status']=='interrupted' or result.get('harness_execution',{}).get('owned_process_group_cleaned') is False:break
        count=sum((root/'attempts'/a['attempt_id']/'result-record.json').exists() for a in manifest['attempts'])
        return {'status':'complete' if count==68 else 'partial','terminal_attempts':count,'expected_attempts':68,'execution_complete':count==68,'release_ready':False}
