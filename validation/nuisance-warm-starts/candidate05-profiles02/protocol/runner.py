#!/usr/bin/env python3
"""Freeze and run separate real GNSS nuisance initialization experiments.

This developer harness never resumes or replaces a native attempt. Production
campaigns and public estimator defaults are not accessed by this script.
"""
from pathlib import Path
import argparse, datetime, hashlib, json, os, re, socket, sys, time
import xml.etree.ElementTree as ET

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(__file__).resolve().parent))
import nuisance_profile_launch as launch
sys.path.insert(0,str(REPO/'src'))
from orbit_poc.segmented.supervisor import run_owned

FULL='receiver_clock_signal_float_v1';CLOCK='receiver_clock_v1'
CASES=[('disabled_source','source','disabled',FULL,None),
       ('cold_source_full','source','cold_export',FULL,None),
       ('cold_source_repeat_full','source_repeat','cold_export',FULL,None),
       ('warm_source_full','source','warm',FULL,'cold_source_full'),
       ('cold_target_full','target','cold_export',FULL,None),
       ('cold_target_repeat_full','target_repeat','cold_export',FULL,None),
       ('warm_target_full','target','warm',FULL,'cold_source_full'),
       ('cold_source_clock','source','cold_export',CLOCK,None),
       ('warm_target_clock','target','warm',CLOCK,'cold_source_clock')]

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):
    p=Path(p);s=p.stat();h=digest(p);a=p.stat()
    if (s.st_ino,s.st_dev,s.st_size,s.st_mtime_ns)!=(a.st_ino,a.st_dev,a.st_size,a.st_mtime_ns):raise ValueError('File changed while hashing: '+str(p))
    return {'path':str(p),'sha256':h,'bytes':s.st_size}
def verify(p):
    if pin(p['path'])!=p:raise ValueError('Frozen file changed: '+p['path'])
def save(p,v):
    with Path(p).open('x') as f:json.dump(v,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
def read(p):return json.loads(Path(p).read_text())
def admission():
    active=[]
    for p in Path('/proc').glob('[0-9]*'):
        try:
            n=(p/'comm').read_text().strip()
            if n.startswith('groops') or n in ('cc1plus','f951','ninja','segmented_qr'):active.append({'pid':int(p.name),'name':n})
        except FileNotFoundError:pass
    if active:raise RuntimeError('Competing native workload: '+repr(active))
    return {'host':socket.gethostname(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'cpu':0,'threads':1,'native_processes':active,'scope':'Cooperative current-host admission; no unrelated process signals'}
def configure(template,destination):
    root=ET.parse(template).getroot();old=str(Path(template).parent);new=str(destination.parent)
    for e in root.iter():
        if e.text and e.text.strip().startswith(old+'/'):
            if e.tag.startswith('outputfile') or e.attrib.get('label')=='tmpDir':e.text=new+e.text.strip()[len(old):]
    root.find('.//orbitPocNumerics/outputfilePrefix').text=str(destination.parent/'qr')
    proc=root.find('.//GnssProcessing');step=ET.SubElement(proc,'processingStep');res=ET.SubElement(step,'writeResiduals')
    select=ET.SubElement(res,'selectReceivers');ET.SubElement(select,'all')
    ET.SubElement(res,'outputfileResiduals').text=str(destination.parent/'diagnostic/residuals.{station}.xml')
    for e in root.iter():
        if (e.tag.startswith('outputfile') or e.attrib.get('label')=='tmpDir') and e.text:
            p=Path(e.text.strip())
            if not p.resolve().is_relative_to(destination.parent.resolve()):raise ValueError('Output escapes experiment: '+str(p))
            (p if e.attrib.get('label')=='tmpDir' else p.parent).mkdir(parents=True,exist_ok=True)
    ET.ElementTree(root).write(destination,encoding='utf-8',xml_declaration=True)

def prepare(args):
    out=args.output.resolve();out.mkdir(exist_ok=False)
    prep=read(args.preparation);build=read(args.build_record)
    if build['execution']['status']!='complete' or not build['inputs_and_originals_unchanged']:raise ValueError('Unverified candidate build')
    verify(build['native']);verify(build['build_manifest'])
    if not read(build['build_manifest']['path']).get('nuisance_warm_extension'):raise ValueError('Missing native warm extension')
    for p in build['libraries']:verify(p)
    copies={p['path']:p for p in prep['copies']}
    for p in copies.values():
        if digest(p['copy'])!=p['copy_sha256'] or Path(p['copy']).stat().st_size!=p['bytes']:raise ValueError('Prepared copy changed')
    jobs=[]
    if set(build['runtime_environment'])!={'LD_LIBRARY_PATH'}:raise ValueError('Unexpected build runtime environment')
    common={**build['runtime_environment'],'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','NUMEXPR_NUM_THREADS':'1','BLIS_NUM_THREADS':'1','GOTO_NUM_THREADS':'1',
            'PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1',
            'ORBIT_POC_NUISANCE_PERFORMANCE':'1','ORBIT_POC_NUISANCE_INTERPOLATION_CACHE':'1',
            'ORBIT_POC_NUMERICS_KEEP_INTERMEDIATE_FACTORS':'1','ORBIT_POC_NUMERICS_COMPRESS_ROW_PROVENANCE':'0'}
    for group in prep['groups']:
        context=hashlib.sha256(json.dumps({'group':group['name'],'preparation':digest(args.preparation),'native':build['native'],'model':group['method'],'kind':'same-fixed-support-different-physical-states'},sort_keys=True).encode()).hexdigest()
        for name,point,treatment,mode,donor in CASES:
            job_id=group['name']+'--'+name;d=out/job_id;d.mkdir();p=next(p for p in group['points'] if p['name']==point)
            if digest(p['profile_template']['path'])!=p['profile_template']['sha256']:raise ValueError('Prepared template changed')
            configure(p['profile_template']['path'],d/'config.xml')
            paths=set(p['input_paths'])|{copies[x['path']]['copy'] for x in p['physical'].values()}
            env={**common,**launch.scientific_controls(d/'config.xml',d),
                 'ORBIT_POC_NUISANCE_WARM_STARTS':'0' if treatment=='disabled' else '1'}
            if treatment!='disabled':env.update(ORBIT_POC_NUISANCE_WARM_MODE=mode,ORBIT_POC_NUISANCE_WARM_CONTEXT_SHA256=context,ORBIT_POC_NUISANCE_WARM_OUTPUT=str(d/'seed.bin'))
            if donor:env['ORBIT_POC_NUISANCE_WARM_INPUT']=str(out/(group['name']+'--'+donor)/'seed.bin')
            jobs.append({'id':job_id,'root':str(d),'profile_sha256':digest(d/'config.xml'),'group':group['name'],'point':point,'treatment':treatment,'mode':mode,'context_sha256':context,'source_donor_job_id':group['name']+'--'+donor if donor else None,'environment':env,'input_inventory':[pin(x) for x in sorted(paths)]})
    # Interleave groups in a fixed rotation; dependency order remains unchanged.
    order=[]
    for k in range(len(CASES)):
        groups=prep['groups'][k%len(prep['groups']):]+prep['groups'][:k%len(prep['groups'])]
        order.extend(g['name']+'--'+CASES[k][0] for g in groups)
    frozen_sources=[pin(p) for folder in ['src','groops/extension'] for p in sorted((REPO/folder).rglob('*')) if p.is_file() and p.suffix in ('.py','.h','.cpp','.f','.F90')]
    freeze={'schema':'orbit-poc-nuisance-warm-profile-freeze-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'native_launch_mode':launch.MODE,'launch_guard':pin(REPO/'scripts/nuisance_profile_launch.py'),
            'preparation':pin(args.preparation),'build_record':pin(args.build_record),'native':build['native'],'runner':pin(__file__),
            'supervisor':pin(REPO/'src/orbit_poc/segmented/supervisor.py'),'checker':pin(REPO/'scripts/check_nuisance_warm_profiles.py'),
            'python':pin(sys.executable),'source_files':frozen_sources,'jobs':jobs,'execution_order':order,'admission':admission(),
            'limits':{'timeout_seconds':900,'max_process_tree_rss_bytes':8*1024**3,'min_free_disk_bytes':16*1024**3,'cpu':0,'threads':1},
            'thresholds':{'strict_nuisance_update_m':1e-8,'required_consecutive_small_updates':2,'code_prediction_m':0.003,'phase_prediction_m':0.00003,'diagnostic_covariance_relative':1e-8},
            'scope':'Fixed physical trajectories, fresh nuisance fits only. No accepted orbit covariance or whole-fit convergence claim; unchanged frozen campaigns are separate.',
            'failure_policy':'Preserve every attempt; donor failures block their dependents. Never overwrite, replace or silently resume an attempt.'}
    save(out/'freeze.json',freeze);print(json.dumps({'freeze':pin(out/'freeze.json'),'attempts':len(jobs)}),flush=True)

def verify_frozen(freeze):
    if freeze.get('native_launch_mode')!=launch.MODE:raise ValueError('Required prelaunch numerics mode missing')
    for key in ['preparation','build_record','native','runner','supervisor','checker','python','launch_guard']:verify(freeze[key])
    if digest(launch.__file__)!=freeze['launch_guard']['sha256']:raise ValueError('Native launch helper differs from frozen guard')
    for job in freeze['jobs']:
        config=Path(job['root'])/'config.xml'
        if digest(config)!=job['profile_sha256']:raise ValueError('Frozen XML changed')
        launch.validate_environment(job['environment'],config,job['root'])
    for p in freeze['source_files']:verify(p)
    build=read(freeze['build_record']['path']);verify(build['build_manifest'])
    for p in build['libraries']:verify(p)
    for rel,h in build['patched_source'].items():
        if digest(Path(build['source_root'])/rel)!=h:raise ValueError('Patched native source changed')

def run(args):
    freeze_path=args.freeze.resolve();launch_pin=pin(freeze_path);freeze=read(freeze_path);verify(launch_pin);verify_frozen(freeze);jobs={j['id']:j for j in freeze['jobs']}
    result_path=freeze_path.parent/'run-result.json'
    if result_path.exists():raise FileExistsError(result_path)
    outcomes=[]
    for job_id in freeze['execution_order']:
        j=jobs[job_id];d=Path(j['root'])
        if (d/'execution.json').exists() or (d/'supervisor.json').exists() or (d/'admission.json').exists():raise FileExistsError('Attempt already started: '+job_id)
        entries=list(d.rglob('*'))
        if any(p.is_symlink() for p in entries) or sorted(str(p.relative_to(d)) for p in entries if p.is_file())!=['config.xml']:
            raise ValueError('Attempt is not the fresh prepared skeleton: '+job_id)
        verify(launch_pin);verify_frozen(freeze)
        for p in j['input_inventory']:verify(p)
        if digest(d/'config.xml')!=j['profile_sha256']:raise ValueError('Frozen XML changed')
        admitted=admission()
        if any(admitted[k]!=freeze['admission'][k] for k in ('host','boot_id','cpu','threads')):raise RuntimeError('Frozen host/boot admission changed; prepare a separate attempt')
        save(d/'admission.json',admitted);effective=dict(j['environment']);donor=None;blocked=None
        if j['source_donor_job_id']:
            sd=Path(jobs[j['source_donor_job_id']]['root']);seed=sd/'seed.bin';comp=sd/'seed.bin.json'
            try:
                source_job=jobs[j['source_donor_job_id']];execution=read(sd/'execution.json');meta=read(comp)
                if execution['status']!='complete' or execution['owned_process_group_cleaned'] is not True or type(execution['returncode']) is not int or execution['returncode']!=0 or execution['timed_out'] is not False or execution['inputs_unchanged'] is not True or execution['identity_error'] is not None:raise ValueError('Donor execution failed')
                eligible=meta['eligibility']
                if meta['schema']!='orbit-poc-native-nuisance-warm-state-v1' or meta['export_status']!='exported' or any(eligible.get(k) is not v for k,v in [('fresh_undamped',True),('nuisance_converged',True),('nuisance_floor_limited',False)]) or eligible.get('rank_status')!='full':raise ValueError('Donor not strictly eligible')
                count=meta['counts']['coordinates']
                if type(count) is not int or not 0<count<=1000000 or any(meta['invariants'].get(k) is not True for k in ('target_cold_ionosphere_unchanged','target_clock_prior_anchors_unchanged')):raise ValueError('Invalid donor coordinate or invariant certificate')
                if any(not re.fullmatch('[0-9a-f]{64}',meta.get(k,'')) for k in ('chart_sha256','cold_origin_sha256')):raise ValueError('Invalid donor chart hashes')
                if source_job['treatment']!='cold_export' or meta['imported']['used'] is not False or meta['imported']['path']!='' or meta['imported']['sha256']!='':raise ValueError('Experiment donor must be the declared cold export')
                if meta['mode']!=j['mode'] or meta['mode']!=source_job['mode'] or meta['context_sha256']!=j['context_sha256'] or meta['context_sha256']!=source_job['context_sha256'] or meta['source_prefix']!=str(sd/'qr'):raise ValueError('Donor chart context differs')
                if execution['job_id']!=source_job['id'] or execution['freeze']!=launch_pin or execution['config_sha256']!=source_job['profile_sha256']:raise ValueError('Donor execution attribution differs')
                for artifact in execution['output_inventory']:
                    rel=Path(artifact['path'])
                    if rel.is_absolute() or '..' in rel.parts:raise ValueError('Donor artifact path escapes')
                    verify({**artifact,'path':str(sd/rel)})
                profile=read(sd/'qr.profile.json');generation=meta['source_generation']
                if not re.fullmatch(re.escape(str(sd/'qr'))+r'\.[1-9][0-9]*',generation) or int(generation.rsplit('.',1)[1])!=profile['iterations']+1:raise ValueError('Stale donor generation')
                if profile['nuisance_converged'] is not True or profile['nuisance_floor_limited'] is not False or profile['threshold_m']!=1e-8 or profile['required_consecutive_small_updates']!=2 or len(profile['history'])<2 or any(not 0<=x['maximum_update_m']<1e-8 for x in profile['history'][-2:]):raise ValueError('Donor failed strict nuisance gate')
                diag=read(generation+'.diagnostics.json')
                if diag['rank_status']!='full' or diag['lambda']!=0 or diag['rank']!=diag['retained_parameters']:raise ValueError('Donor lacks fresh undamped full rank')
                if digest(seed)!=meta['payload_sha256']:raise ValueError('Donor payload identity changed')
                donor={'root':str(sd),'payload':pin(seed),'companion':pin(comp)};effective['ORBIT_POC_NUISANCE_WARM_INPUT_SHA256']=digest(seed)
            except (OSError,ValueError,KeyError) as e:blocked=type(e).__name__+': '+str(e)
        cmd=None;binding_record=None
        start=datetime.datetime.now(datetime.timezone.utc).isoformat();mono=time.monotonic()
        if blocked:
            result={'status':'blocked','returncode':None,'elapsed_seconds':0.,'owned_process_group_cleaned':True,'reason':blocked};save(d/'supervisor.json',result)
        else:
            launch.validate_environment(effective,d/'config.xml',d)
            save(d/'launch-binding.json',{'schema':'orbit-poc-nuisance-profile-launch-binding-v1','mode':launch.MODE,
                 'freeze':launch_pin,'native':freeze['native'],'config':pin(d/'config.xml'),'guard':freeze['launch_guard'],
                 'job_id':job_id,'root':str(d),'cpu':0,'environment':effective})
            binding_record=pin(d/'launch-binding.json')
            cmd=launch.launch_command(freeze['python']['path'],freeze['launch_guard']['path'],binding_record)
            env={k:v for k,v in os.environ.items() if not k.startswith(('ORBIT_POC_','LD_')) and k not in ('PYTHONPATH','PYTHONHOME')};env.update(effective)
            lim=freeze['limits'];result=run_owned(cmd,python_executable=freeze['python']['path'],cwd=d,env=env,log_path=d/'profile.log',receipt_path=d/'supervisor.json',timeout_seconds=lim['timeout_seconds'],max_process_tree_rss_bytes=lim['max_process_tree_rss_bytes'],min_free_disk_bytes=lim['min_free_disk_bytes'],working_directory=d)
        stable=True;error=None
        try:
            verify(launch_pin);verify_frozen(freeze)
            for p in j['input_inventory']:verify(p)
            if donor:
                verify(donor['payload']);verify(donor['companion'])
            if digest(d/'config.xml')!=j['profile_sha256']:raise ValueError('Config changed')
            if not blocked:
                verify(binding_record)
                launch.checked_launch(binding_record,read(d/'native-launch.json'),expected_environment=effective)
        except Exception as e:stable=False;error=str(e)
        rec={'schema':'orbit-poc-nuisance-warm-profile-execution-v1','status':result['status'] if stable else 'identity_failure','returncode':result.get('returncode'),'timed_out':result['status']=='timeout','owned_process_group_cleaned':result['owned_process_group_cleaned'],
             'command':cmd,'config_sha256':j['profile_sha256'],'native_binary_sha256':freeze['native']['sha256'],'supervisor_sha256':digest(d/'supervisor.json'),'freeze':launch_pin,'preparation':freeze['preparation'],
             'native_launch_mode':launch.MODE,'launch_binding':binding_record,
             **{k:j[k] for k in ['group','point','treatment','mode','context_sha256','input_inventory']},'job_id':job_id,'effective_environment':effective,'source_donor':donor,
             'elapsed_seconds':result['elapsed_seconds'],'controller_elapsed_seconds':time.monotonic()-mono,'started_at':start,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'inputs_unchanged':stable,'identity_error':error,'blocked_reason':blocked}
        rec['output_inventory']=[{**pin(p),'path':str(p.relative_to(d))} for p in sorted(d.rglob('*')) if p.is_file()]
        save(d/'execution.json',rec);outcomes.append({'job_id':job_id,'status':rec['status']});print(json.dumps(outcomes[-1]),flush=True)
        if not stable or not result['owned_process_group_cleaned']:break
    save(result_path,{'schema':'orbit-poc-nuisance-warm-profile-runs-v1','freeze':launch_pin,'outcomes':outcomes,'planned':len(jobs),'completed':len(outcomes),'scientific_acceptance':'Requires separate checker and independent review'})

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    q=sub.add_parser('prepare');q.add_argument('--preparation',type=Path,required=True);q.add_argument('--build-record',type=Path,required=True);q.add_argument('--output',type=Path,required=True)
    q=sub.add_parser('run');q.add_argument('--freeze',type=Path,required=True)
    args=p.parse_args();globals()[args.action](args)
