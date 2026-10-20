#!/usr/bin/env python3
"""Read-only, frozen fixed-trajectory nuisance checks; no orbit covariance authority.

Normal: cold warm repeat --output result.json. The repeat must be the separately
closed cold repeat of the SAME source/target point. --inert compares disabled
and cold-export profiles exactly. --cold-repeat only measures the cold floor.
Every successful input is a completed owned run bound to a frozen job and the
preparation inventory. Failed/missing inputs produce an explicit failed report.
"""
from __future__ import annotations
import argparse
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import sys
import xml.etree.ElementTree as ET
import numpy as np
from scipy.linalg import solve_triangular
sys.path.insert(0,str(Path(__file__).resolve().parent))
import nuisance_profile_launch as launch

HEX = re.compile(r'[0-9a-f]{64}')
WARM = 'ORBIT_POC_NUISANCE_WARM'
MODES = {'receiver_clock_signal_float_v1', 'receiver_clock_v1'}
GEN = re.compile(r'qr\.(\d+)\.factor\.json')
REQUIRED = ('factor.json','diagnostics.json','profile.json','parameters.tsv','bias_coordinates.tsv',
            'nuisance_coordinates.tsv','delta.tsv','singular_values.txt','rows.tsv','R.bin','rhs.bin')
TIMING = {'child_user_seconds','child_system_seconds','peak_child_rss_bytes'}


def require(test, message):
    if not test: raise ValueError(message)


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()


def strict_json(path):
    def pairs(items):
        out={}
        for k,v in items:
            require(k not in out, 'Duplicate JSON key');out[k]=v
        return out
    def bad(value): raise ValueError('Nonfinite JSON '+value)
    def number(value):
        result=float(value);require(math.isfinite(result),'Nonfinite JSON');return result
    return json.loads(Path(path).read_text(),object_pairs_hook=pairs,parse_constant=bad,parse_float=number)


def pin(record, *, root=None, allow_symlink=False):
    p=Path(record['path'])
    if root is not None:
        require(not p.is_absolute() and '..' not in p.parts, 'Inventory path must be relative')
        p=root/p
    target=p.resolve(strict=True)
    require(p.is_absolute() and p.is_file() and (allow_symlink or (not p.is_symlink() and target==p)),
            'Missing/nonregular/symlink pinned file: '+str(p))
    require(HEX.fullmatch(record['sha256']) is not None, 'Invalid file digest')
    stat=p.stat();require(stat.st_size==record['bytes'],'Pinned byte count changed: '+str(p))
    require(digest(p)==record['sha256'],'Pinned content changed: '+str(p))
    identity=lambda s:(s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    require(p.resolve(strict=True)==target and identity(p.stat())==identity(stat),'Pinned file changed during read: '+str(p))
    return p


def pin_tree(value):
    """Verify explicit pin records; plain historical path strings are not pins."""
    if isinstance(value,dict):
        if {'path','sha256','bytes'} <= value.keys(): pin(value,allow_symlink=True)
        for item in value.values(): pin_tree(item)
    elif isinstance(value,list):
        for item in value: pin_tree(item)


def inventory(records, *, root=None):
    result={}
    for record in records:
        key=record['path'];require(key not in result,'Duplicate inventory entry')
        result[key]=pin(record,root=root)
    require(bool(result),'Empty artifact inventory')
    return result


def matrix(path):
    data=Path(path).read_bytes();require(len(data)>=16,'Truncated matrix')
    shape=struct.unpack('<QQ',data[:16]);require(len(data)==16+8*shape[0]*shape[1],'Invalid matrix shape')
    values=np.frombuffer(data[16:],dtype='<f8');require(np.isfinite(values).all(),'Nonfinite matrix')
    return values.reshape(shape)


def rows(path):
    if not path.exists() and path.with_suffix(path.suffix+'.gz').exists():
        stream=gzip.open(path.with_suffix(path.suffix+'.gz'),'rt')
    else: stream=path.open()
    with stream: result=list(csv.DictReader(stream,delimiter='\t'))
    require(bool(result),'Empty table '+str(path));return result


def measurements(path):
    """Epoch index is the join key: exported times contain fitted clock offsets."""
    root=ET.parse(path).getroot();result={};epochs=root.findall('.//epoch')
    require(bool(epochs),'Missing native residual epochs')
    for epoch_id,e in enumerate(epochs):
        def vector(name):
            n=e.find(name);require(n is not None,'Missing residual vector '+name)
            cells=[(x.text or '').strip() for x in n.findall('cell')]
            require(int(n.findtext('count'))==len(cells),'Residual vector count mismatch');return cells
        types=vector('type');satellites=vector('satellite');values=np.array([float(x) for x in vector('observation')])
        require(len(types)>=8 and len(values)==len(types)*len(satellites),'Unexpected residual layout')
        require([t[:1] for t in types[:5]]==['A','E','A','E','I'],'Unexpected geometry/TEC header')
        require(not np.isinf(values).any(),'Infinite residual diagnostic vector')
        for j,satellite in enumerate(satellites):
            require(np.isfinite(values[j*len(types):j*len(types)+5]).all(),'Nonfinite residual geometry/TEC header')
            require('G' in satellite,'Only frozen GPS fixtures are supported')
            for k in range(5,len(types),3):
                require(len(types[k:k+3])==3 and len(set(types[k:k+3]))==1 and types[k][:1] in ('C','L'),
                        'Unexpected measurement triple')
                triple=values[j*len(types)+k:j*len(types)+k+3];residual,redundancy,sigma=triple
                key=(epoch_id,satellite,types[k]);require(key not in result,'Duplicate prediction identity')
                # GROOPS initializes unavailable satellite/type slots to three
                # NaNs. Preserve this absent-slot support explicitly. Redundancy
                # alone may be NaN because profiling does not compute leverage.
                if np.isnan(triple).all():result[key]=(None,None);continue
                require(np.isfinite([residual,sigma]).all() and sigma>0,'Invalid prediction residual/weight')
                result[key]=(float(residual),float(sigma))
    require(any(k[-1].startswith('C') and v[0] is not None for k,v in result.items()) and any(k[-1].startswith('L') and v[0] is not None for k,v in result.items()),
            'Both code and phase predictions required')
    return result


def prepared_point(preparation,group,name):
    matches=[g for g in preparation['groups'] if g['name']==group];require(len(matches)==1,'Unknown prepared group')
    points=[p for p in matches[0]['points'] if p['name']==name];require(len(points)==1,'Unknown prepared point')
    return matches[0],points[0]


def template_signature(path, input_hashes, *, repeat=False, append_residual=False):
    root=ET.parse(path).getroot()
    if append_residual:
        proc=root.find('.//GnssProcessing');require(proc is not None,'Missing GNSS processing')
        step=ET.SubElement(proc,'processingStep');res=ET.SubElement(step,'writeResiduals')
        ET.SubElement(ET.SubElement(res,'selectReceivers'),'all')
        ET.SubElement(res,'outputfileResiduals').text='<OUTPUT>'
    for e in root.iter():
        e.tail=None
        if list(e):e.text=None;continue
        text=(e.text or '').strip()
        if e.tag.startswith('outputfile') or e.attrib.get('label') in ('tmpDir','groopsDataDir'):
            e.text='<OUTPUT>'
        elif e.tag.startswith('inputfile') or (e.tag=='filename' and e.attrib.get('label')=='orbitPocCanonicalAttitude'):
            if not text:continue
            if repeat and e.tag in ('inputfileVariational','inputfileNumericsReferenceParameters'):
                e.text='<SEPARATELY_CLOSED_'+e.tag+'>'
            else:
                paths=[text.replace('{prn}',f'G{i:02}') for i in range(1,33)] if '{prn}' in text else [text]
                require(all(p in input_hashes for p in paths),'Uninventoried XML input')
                e.text=json.dumps([input_hashes[p] for p in paths])
        else:e.text=text
        e.tail=None
    return ET.tostring(root)


def checked_receipts(root):
    root=Path(root).absolute();require(root.resolve()==root,'Runroot symlink forbidden')
    ex=strict_json(root/'execution.json')
    require(ex['schema']=='orbit-poc-nuisance-warm-profile-execution-v1','Unknown execution schema')
    freeze_path=pin(ex['freeze']);freeze=strict_json(freeze_path)
    require(freeze['schema']=='orbit-poc-nuisance-warm-profile-freeze-v1','Unknown freeze schema')
    require(freeze.get('native_launch_mode')==launch.MODE,'Required prelaunch numerics mode missing')
    for key in ('preparation','native','runner','supervisor','build_record','checker','python','launch_guard'):
        pin(freeze[key],allow_symlink=key in ('native','python'))
    require(freeze['checker']['sha256']==digest(__file__),'Checker differs from frozen implementation')
    require(freeze['launch_guard']['sha256']==digest(launch.__file__),'Launch helper differs from frozen guard')
    for record in freeze['source_files']:pin(record)
    build=strict_json(freeze['build_record']['path']);pin_tree(build)
    require(build['native']==freeze['native'] and build['execution']['status']=='complete' and build['inputs_and_originals_unchanged'] is True,'Build identity/status mismatch')
    for rel,sha in build['patched_source'].items():
        require(digest(Path(build['source_root'])/rel)==sha,'Patched native source changed')
    require(freeze['thresholds']=={'strict_nuisance_update_m':1e-8,'required_consecutive_small_updates':2,'code_prediction_m':.003,'phase_prediction_m':.00003,'diagnostic_covariance_relative':1e-8},'Frozen correctness thresholds changed')
    require(ex['preparation']==freeze['preparation'],'Execution preparation changed')
    prep=strict_json(pin(ex['preparation']))
    require(prep['schema']=='orbit-poc-nuisance-warm-profile-preparation-v1','Unknown preparation schema')
    found=[j for j in freeze['jobs'] if j['id']==ex['job_id']];require(len(found)==1,'Unknown/duplicate frozen job')
    job=found[0];require(Path(job['root'])==root,'Wrong frozen runroot')
    for key in ('group','point','treatment','mode','context_sha256'):
        require(ex[key]==job[key],'Execution/frozen '+key+' mismatch')
    require(job['treatment'] in ('disabled','cold_export','warm'),'Unknown treatment')
    require(job['mode'] in MODES and HEX.fullmatch(job['context_sha256']) is not None,'Invalid mode/context')
    require(ex['input_inventory']==job['input_inventory'],'Execution input inventory changed')
    inputs=inventory(job['input_inventory']);input_hashes={r['path']:r['sha256'] for r in job['input_inventory']}
    group,point=prepared_point(prep,job['group'],job['point'])
    pin(point['profile_template'])
    copies={r['copy']:r for r in prep['copies']};require(len(copies)==len(prep['copies']),'Duplicate prepared copy')
    original={r['path']:r for r in prep['copies']}
    expected=set(point['input_paths'])|{original[r['path']]['copy'] for r in point['physical'].values()}
    require(set(inputs)==expected,'Frozen inputs do not exactly cover prepared point and physical coordinates')
    for name in expected:
        record=copies[name]
        require(record['copy_sha256']==record['sha256']==input_hashes[name],'Input disagrees with preparation')
    physical={name:rec['sha256'] for name,rec in point['physical'].items()}
    require(set(physical)=={'physical_initial.txt','fixed_force.txt'},'Missing physical coordinate identity')
    for rec in point['physical'].values():require(original[rec['path']]['sha256']==rec['sha256'],'Physical copy identity mismatch')
    require(ex.get('inputs_unchanged') is True and ex.get('identity_error') is None and ex.get('blocked_reason') is None,'Execution input identity not verified or blocked')
    require(ex['status']=='complete' and ex['returncode']==0 and type(ex['returncode']) is int
            and ex['timed_out'] is False and ex['owned_process_group_cleaned'] is True,'Run not cleanly complete')
    require(type(ex['elapsed_seconds']) in (int,float) and math.isfinite(ex['elapsed_seconds']) and ex['elapsed_seconds']>0,'Invalid completed elapsed time')
    require(ex['config_sha256']==job['profile_sha256']==digest(root/'config.xml'),'Configuration changed')
    require(ex['native_binary_sha256']==freeze['native']['sha256'],'Wrong native binary')
    expected_environment=dict(job['environment'])
    if job['treatment']=='warm':expected_environment[WARM+'_INPUT_SHA256']=ex['source_donor']['payload']['sha256']
    require(ex['effective_environment']==expected_environment,'Effective controls differ from freeze')
    launch.validate_environment(expected_environment,root/'config.xml',root)
    env=ex['effective_environment'];require(all(env.get(k)=='1' for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS')),'Numerical threads changed')
    require(env.get('ORBIT_POC_NUMERICS_KEEP_INTERMEDIATE_FACTORS')=='1','All profile factors must be retained')
    warm_keys={k:v for k,v in env.items() if k.startswith(WARM)}
    expected_env={WARM+'_STARTS':'0'}
    if job['treatment']!='disabled':
        expected_env={WARM+'_STARTS':'1',WARM+'_MODE':job['mode'],WARM+'_CONTEXT_SHA256':job['context_sha256'],WARM+'_OUTPUT':str(root/'seed.bin')}
        if job['treatment']=='warm':
            d=ex['source_donor'];expected_env.update({WARM+'_INPUT':d['payload']['path'],WARM+'_INPUT_SHA256':d['payload']['sha256']})
    require(warm_keys==expected_env,'Warm controls differ from assigned treatment')
    if job['treatment']!='warm':require(ex['source_donor'] is None and job['source_donor_job_id'] is None,'Cold run contains donor')
    require(ex.get('native_launch_mode')==launch.MODE,'Execution prelaunch mode differs')
    binding_record=ex['launch_binding'];pin(binding_record)
    launch_receipt=strict_json(root/'native-launch.json')
    binding=launch.checked_launch(binding_record,launch_receipt,expected_environment=expected_environment)
    require(binding['freeze']==ex['freeze'] and binding['native']==freeze['native'] and binding['guard']==freeze['launch_guard']
            and binding['job_id']==job['id'] and binding['config']['sha256']==job['profile_sha256'],'Native launch attribution differs')
    command=launch.launch_command(freeze['python']['path'],freeze['launch_guard']['path'],binding_record)
    require(ex['command']==command,'Command differs from frozen native/config/CPU')
    supervisor=strict_json(root/'supervisor.json')
    require(ex['supervisor_sha256']==digest(root/'supervisor.json'),'Supervisor receipt changed')
    require(supervisor['status']=='complete' and type(supervisor['returncode']) is int and supervisor['returncode']==0
            and supervisor['owned_process_group_cleaned'] is True and supervisor['cleanup']['verified'] is True,
            'Supervisor does not certify clean completion')
    require(supervisor['argv']==command,'Supervisor executed another command')
    plan=strict_json(root/'supervisor.plan.json')
    require(supervisor['schema']=='orbit-poc-segmented-supervision-v1' and plan['schema']=='orbit-poc-segmented-supervision-plan-v1', 'Wrong supervisor schema')
    require(supervisor['plan_sha256']==digest(root/'supervisor.plan.json') and
            supervisor['helper_sha256']==plan['helper_sha256']==freeze['supervisor']['sha256'] and
            supervisor['boot_id']==plan['boot_id'],'Supervisor plan/helper/boot mismatch')
    require(supervisor['cleanup']['empty_tree_certificate']=='kernel_ECHILD' and not supervisor['cleanup']['remaining'],'No kernel empty-tree certificate')
    require(plan['argv']==command and plan['cwd']==plan['working_directory']==str(root) and
            plan['receipt_path']==str(root/'supervisor.json') and plan['log_path']==str(root/'profile.log'),'Supervisor plan attribution mismatch')
    require(all(plan[k]==freeze['limits'][k] for k in ('timeout_seconds','max_process_tree_rss_bytes','min_free_disk_bytes')),'Supervisor limits changed')
    artifacts=inventory(ex['output_inventory'],root=root)
    actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and p!=root/'execution.json'}
    require(set(artifacts)==actual,'Output inventory missing/extra files')
    require('config.xml' in artifacts and 'supervisor.json' in artifacts,'Incomplete receipt inventory')
    datum=launch.datum_evidence(root)
    # Freeze pins the exact run XML. Structural identity to the prepared XML is
    # checked separately; appended residual-export programs may differ only in output paths.
    template=template_signature(point['profile_template']['path'],input_hashes)
    config=template_signature(root/'config.xml',input_hashes)
    require(config==template_signature(point['profile_template']['path'],input_hashes,append_residual=True),'Run config changes prepared scientific settings')
    for e in ET.parse(root/'config.xml').getroot().iter():
        if (e.tag.startswith('outputfile') or e.attrib.get('label')=='tmpDir') and (e.text or '').strip():
            require(Path(e.text.strip()).is_relative_to(root),'Run output escapes isolated directory')
    return dict(root=root,execution=ex,freeze=freeze,job=job,preparation=prep,point=point,group=group,
                physical=physical,input_hashes=input_hashes,artifacts=artifacts,template=template,config=config,
                native_datum_evidence=datum)


def inspect(root, *, donor=True):
    out=checked_receipts(root);root=out['root'];profile=strict_json(root/'qr.profile.json')
    require(profile['nuisance_converged'] is True and profile['nuisance_floor_limited'] is False,
            'Strict nuisance convergence required; floor-limited is not success')
    require(profile['threshold_m']==1e-8 and profile['required_consecutive_small_updates']==2,'Changed nuisance threshold')
    require(profile['fixed_weights'] is True and profile['dynamic_updates'] is False,'Profile changed physical dynamics/weights')
    count=profile['iterations'];history=profile['history']
    require(type(count) is int and count>=2 and len(history)==count,'Wrong nuisance history length')
    require(profile['maximum_update_m']==history[-1]['maximum_update_m'],'Stale profile summary')
    require(all(math.isfinite(r['maximum_update_m']) and r['maximum_update_m']>=0 for r in history),'Invalid nuisance update')
    require(all(r['maximum_update_m']<1e-8 for r in history[-2:]),'Strict update criterion not satisfied')
    factors={int(GEN.fullmatch(p.name).group(1)):p for p in root.glob('qr.*.factor.json') if GEN.fullmatch(p.name)}
    require(set(factors)==set(range(1,count+2)),'Missing/noncontiguous/stale factor generations')
    for i in factors:
        for suffix in REQUIRED:
            p=root/f'qr.{i}.{suffix}'
            require(p.exists() or (suffix=='rows.tsv' and p.with_suffix('.tsv.gz').exists()),'Missing factor artifact '+str(p))
    stem=root/f'qr.{count+1}';info=strict_json(str(stem)+'.factor.json');diag=strict_json(str(stem)+'.diagnostics.json');cost=strict_json(str(stem)+'.profile.json')
    n=len(info['scales']);scales=np.asarray(info['scales'],dtype=float);dynamic=np.asarray(info['dynamic'])
    require(diag['rank_status']=='full' and diag['lambda']==0 and diag['rank']==diag['retained_parameters']==n,
            'Fresh undamped full rank required')
    require(info['rows']==info['columns']==n and np.isfinite(scales).all() and (scales>0).all(),'Invalid factor dimensions/scales')
    require(dynamic.dtype==np.bool_ and dynamic.shape==(n,) and dynamic.any(),'Invalid dynamic coordinates')
    singular=np.atleast_1d(np.loadtxt(str(stem)+'.singular_values.txt'))
    require(singular.shape==(n,) and np.isfinite(singular).all() and np.all(np.diff(singular)<=0),'Invalid singular values')
    threshold=np.finfo(float).eps*max(diag['reduced_rows'],n)*singular[0]
    require(np.isclose(diag['rank_threshold'],threshold,rtol=8*np.finfo(float).eps,atol=0)
            and singular[-1]>10*threshold,'Unresolved/deficient rank certificate')
    require(diag['sigma_min']==singular[-1] and diag['sigma_max']==singular[0],'Rank extrema mismatch')
    R=matrix(str(stem)+'.R.bin');rhs=matrix(str(stem)+'.rhs.bin')
    require(R.shape==(n,n) and rhs.shape==(n,1) and np.count_nonzero(np.tril(R,-1))==0,'Invalid triangular factor')
    # Native columns are multiplied by inverse column norms: x = scales*z.
    inverse=scales[:,None]*solve_triangular(R,np.eye(n),lower=False)
    covariance=inverse@inverse.T;correction=scales*solve_triangular(R,rhs[:,0],lower=False)
    require(np.isfinite(covariance).all() and (np.diag(covariance)>0).all(),'Invalid diagnostic covariance')
    params=rows(Path(str(stem)+'.parameters.tsv'));params=[{k:v for k,v in r.items() if k!='scale'} for r in params]
    rowdata=rows(Path(str(stem)+'.rows.tsv'))
    require(len(rowdata)==diag['source_rows'],'Row count mismatch')
    require([int(r['row']) for r in rowdata]==list(range(len(rowdata))),'Noncontiguous original row ledger')
    support=[{k:v for k,v in r.items() if k!='rhs'} for r in rowdata]
    require(all(math.isfinite(float(r['rhs'])) for r in rowdata),'Nonfinite row target')
    residual=list((root/'diagnostic').glob('residuals.*.xml'));require(len(residual)==1,'Expected one residual receiver')
    predictions=measurements(residual[0]);objective=cost['direct_cost']
    require(type(objective) in (float,int) and math.isfinite(objective) and objective>=0,'Invalid actual objective')
    require(info['objective_residual_basis']=='original_weighted_rows_v1','Wrong objective residual basis')
    require(cost['rhs2']>=0 and math.isfinite(cost['rhs2']),'Invalid objective energy')
    require(abs(2*objective-cost['rhs2'])<=32*np.finfo(float).eps*max(1,abs(2*objective)),
            'Actual objective omits residual energy')
    prior={name:{'rows':sum(r['source']==name for r in rowdata),
                       'rhs_squared':math.fsum(float(r['rhs'])**2 for r in rowdata if r['source']==name)}
           for name in ('code_bias_full_constraint','tec_bias_full_constraint')}
    if out['group']['nuisance_prior_variant']:
        require(all(v['rows']>0 and v['rhs_squared']>0 for v in prior.values()),'Nonzero code/TEC full-prior fixture not exercised')
        xml=ET.parse(root/'config.xml').getroot()
        require(all(xml.findtext('.//parametrization/'+tag+'/sigmaZeroMeanConstraint')=='1' for tag in ('codeBiases','tecBiases')),
                'Nonzero prior fixture configuration changed')
    out.update(profile=profile,iterations=count,parameters=params,rows=(diag['source_rows'],diag['reduced_rows'],info['original_objective_rows']),
               support=support,retained_global_indices=info['retained_global_indices'],dynamic=dynamic,covariance=covariance,
               correction=correction,predictions=predictions,objective=objective,stem=stem,prior_evidence=prior)
    treatment=out['job']['treatment'];companion=None
    if treatment=='disabled':require(not (root/'seed.bin').exists() and not (root/'seed.bin.json').exists(),'Disabled run exported seed')
    else:
        companion=strict_json(root/'seed.bin.json')
        require(companion['schema']=='orbit-poc-native-nuisance-warm-state-v1','Wrong seed schema')
        require(companion['mode']==out['job']['mode'] and companion['context_sha256']==out['job']['context_sha256'],'Wrong seed mode/context')
        require(companion['export_status']=='exported' and companion['payload_sha256']==digest(root/'seed.bin'),'Wrong seed export hash/status')
        require(all(type(companion['eligibility'].get(k)) is bool for k in ('nuisance_converged','nuisance_floor_limited','fresh_undamped')),'Seed eligibility flags must be booleans')
        require(companion['eligibility']=={'nuisance_converged':True,'nuisance_floor_limited':False,'fresh_undamped':True,'rank_status':'full'},'Ineligible donor export')
        require(companion['source_prefix']==str(root/'qr') and companion['source_generation']==str(stem),'Stale/misattributed seed generation')
        require(all(isinstance(companion[k],str) and HEX.fullmatch(companion[k]) for k in ('chart_sha256','cold_origin_sha256')),'Invalid seed identity')
        require(type(companion['counts']['coordinates']) is int and companion['counts']['coordinates']>0,'Empty seed chart')
        require(all(type(companion['invariants'].get(k)) is bool for k in ('target_cold_ionosphere_unchanged','target_clock_prior_anchors_unchanged')),'Seed invariant flags must be booleans')
        require(type(companion['imported'].get('used')) is bool,'Seed imported flag must be boolean')
        require(companion['invariants']=={'target_cold_ionosphere_unchanged':True,'target_clock_prior_anchors_unchanged':True},'Changed ionosphere/prior anchors')
        if treatment=='cold_export':require(companion['imported']=={'used':False,'path':'','sha256':''},'Cold export imported warm seed')
        else:
            require(donor,'Recursive warm donor forbidden');source=out['execution']['source_donor'];dr=Path(source['root'])
            frozen=[j for j in out['freeze']['jobs'] if j['id']==out['job']['source_donor_job_id']]
            require(len(frozen)==1 and Path(frozen[0]['root'])==dr,'Unfrozen donor')
            require(source['payload']['path']==str(dr/'seed.bin') and source['companion']['path']==str(dr/'seed.bin.json'),'Wrong donor paths')
            pin(source['payload']);pin(source['companion']);d=inspect(dr,donor=False)
            require(d['job']['treatment']=='cold_export' and d['execution']['freeze']==out['execution']['freeze'],'Donor is not frozen cold export')
            require(d['job']['group']==out['job']['group'] and d['job']['mode']==out['job']['mode'],'Donor group/mode mismatch')
            require(companion['imported']=={'used':True,'path':source['payload']['path'],'sha256':source['payload']['sha256']},'Wrong imported seed identity')
            for key in ('context_sha256','chart_sha256','cold_origin_sha256','counts'):
                require(companion[key]==d['companion'][key],'Donor/target chart or cold origin mismatch')
            out['donor']={'root':str(dr),'iterations':d['iterations'],'payload_sha256':source['payload']['sha256']}
    out['companion']=companion
    return out


def same_problem(a,b,*,repeat=False):
    require(a['execution']['freeze']==b['execution']['freeze'],'Different execution freezes')
    require(a['job']['group']==b['job']['group'],'Different scientific groups')
    require(a['physical']==b['physical'],'Different physical parameter values')
    require(a['parameters']==b['parameters'] and a['rows']==b['rows'] and a['support']==b['support']
            and a['retained_global_indices']==b['retained_global_indices'] and np.array_equal(a['dynamic'],b['dynamic']),
            'Changed row/parameter support')
    require(a['predictions'].keys()==b['predictions'].keys(),'Changed prediction support')
    require(all(a['predictions'][k][1]==b['predictions'][k][1] for k in a['predictions']),'Changed measurement weights')
    for kind in ('template','config'):
        ap=a['point']['profile_template']['path'] if kind=='template' else a['root']/'config.xml'
        bp=b['point']['profile_template']['path'] if kind=='template' else b['root']/'config.xml'
        require(template_signature(ap,a['input_hashes'],repeat=repeat)==template_signature(bp,b['input_hashes'],repeat=repeat),
                'Changed physics/settings/input content')


def cold_floor(cold,repeat):
    require(cold['job']['treatment']=='cold_export' and repeat['job']['treatment']=='cold_export','Floor requires cold exports')
    require(cold['job']['point'] in ('source','target') and repeat['job']['point']==cold['job']['point']+'_repeat',
            'Floor must use matching independently closed cold repeat')
    require(cold['root']!=repeat['root'],'Cold floor requires independent execution')
    same_problem(cold,repeat,repeat=True)
    return max(10*abs(cold['objective']-repeat['objective']),8*np.finfo(float).eps*abs(cold['objective']))


def compare(cold,warm,repeat):
    floor=cold_floor(cold,repeat)
    require(warm['job']['treatment']=='warm' and warm['job']['point']==cold['job']['point'],'Warm target differs from cold point')
    same_problem(cold,warm)
    if cold['job']['mode']==warm['job']['mode']:
        require(cold['companion']['chart_sha256']==warm['companion']['chart_sha256'] and
                cold['companion']['cold_origin_sha256']==warm['companion']['cold_origin_sha256'],'Target cold chart/origin mismatch')
    pred={kind:max(abs(cold['predictions'][k][0]-warm['predictions'][k][0]) for k in cold['predictions'] if k[-1].startswith(code) and cold['predictions'][k][0] is not None)
          for kind,code in [('code','C'),('phase','L')]}
    c=cold['covariance'];w=warm['covariance'];sd=np.sqrt(np.diag(c));norm=np.outer(sd,sd)
    relative=float(np.linalg.norm((w-c)/norm)/np.linalg.norm(c/norm));mask=cold['dynamic'];ix=np.ix_(mask,mask)
    dynamic_relative=float(np.linalg.norm((w[ix]-c[ix])/norm[ix])/np.linalg.norm(c[ix]/norm[ix]))
    checks={'strict_support_and_weights':True,'objective_within_cold_floor':abs(warm['objective']-cold['objective'])<=floor,
            'code_prediction_below_one_percent_noise':pred['code']<.003,'phase_prediction_below_one_percent_noise':pred['phase']<.00003,
            'unit_normalized_retained_covariance_relative_below_1e8':relative<1e-8,
            'unit_normalized_dynamic_covariance_relative_below_1e8':dynamic_relative<1e-8}
    return {'passed':all(checks.values()),'checks':checks,'cold_iterations':cold['iterations'],'warm_iterations':warm['iterations'],
            'objective_difference':abs(warm['objective']-cold['objective']),'cold_objective_floor':floor,
            'objective_floor_policy':'max(10*abs(same-point independently closed cold repeat difference),8*eps*abs(cold objective)); source/warm never supply target floor',
            'prediction_slots':len(cold['predictions']),'absent_prediction_slots':sum(v[0] is None for v in cold['predictions'].values()),
            'diagnostic_redundancy_policy':'Unused native all-NaN triples remain explicit absent support; NaN redundancy is ignored only when physical residual and sigma are valid',
            'maximum_prediction_difference_m':pred,'relative_retained_covariance_difference':relative,
            'relative_dynamic_covariance_difference':dynamic_relative,
            'dynamic_correction_difference_posterior_sd_diagnostic':float(np.max(np.abs(cold['correction'][mask]-warm['correction'][mask])/sd[mask])),
            'covariance_scope':'Diagnostic undamped local linearization marginal blocks only; no accepted orbit covariance',
            'same_linearization_map_gate':'Not applied to distinct nuisance linearizations; native QR correctness suite is separate',
            'nonzero_prior_evidence':{'cold':cold['prior_evidence'],'warm':warm['prior_evidence'],'repeat':repeat['prior_evidence']}}


def scientific_artifacts(run):
    out={}
    for name,path in run['artifacts'].items():
        qr=path.name.startswith('qr.') and (path.name.endswith(('.tsv','.bin','.singular_values.txt','.rows.tsv.gz')) or
            path.name.endswith(('.profile.json','.factor.json','.diagnostics.json','.nuisance_line_search.json')))
        if not qr and not name.startswith('diagnostic/'):continue
        key=name[:-3] if name.endswith('.rows.tsv.gz') else name
        data=gzip.decompress(path.read_bytes()) if name.endswith('.rows.tsv.gz') else path.read_bytes()
        if name.endswith('.json'):
            value=strict_json(path)
            if name.endswith('.nuisance_line_search.json'):
                for trial in value.get('trials',[]):
                    for field in TIMING:trial.pop(field,None)
            # Only filesystem bookkeeping is normalized; numerical fields remain exact.
            if name.endswith('.factor.json') and value.get('spool_directory')==str(run['root']/'scratch'):
                value['spool_directory']='<RUN>/scratch'
            data=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        require(key not in out or out[key]==data,'Conflicting compressed scientific artifact');out[key]=data
    require(bool(out),'Missing scientific artifacts');return out


def inert(disabled,enabled):
    require(disabled['job']['treatment']=='disabled' and enabled['job']['treatment']=='cold_export','Inert check requires disabled/cold_export')
    require(disabled['job']['point']==enabled['job']['point'],'Inert check needs identical prepared point')
    same_problem(disabled,enabled);a=scientific_artifacts(disabled);b=scientific_artifacts(enabled)
    require(a.keys()==b.keys(),'Missing/unmatched inert scientific artifacts')
    changed=[k for k in a if a[k]!=b[k]]
    return {'passed':not changed,'inert_scientific_exact':not changed,'compared_artifacts':len(a),'changed_artifacts':changed,
            'mode':enabled['job']['mode'],'normalization':'JSON key order; three declared trial CPU/RSS fields; exact scratch bookkeeping path only'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('cold',type=Path);p.add_argument('warm',type=Path)
    p.add_argument('repeat',type=Path,nargs='?');p.add_argument('--output',type=Path,required=True)
    modes=p.add_mutually_exclusive_group();modes.add_argument('--inert',action='store_true');modes.add_argument('--cold-repeat',action='store_true')
    args=p.parse_args();require(not args.output.exists(),'Output already exists')
    result={'schema':'orbit-poc-nuisance-warm-fixed-profile-check-v1','release_authority':False,'accepted_orbit_covariance':False,
            'checker_sha256':digest(__file__),'roots':[str(x) for x in (args.cold,args.warm,args.repeat) if x is not None]}
    try:
        a,b=inspect(args.cold),inspect(args.warm)
        result['execution_receipts']=[{'root':str(run['root']),'sha256':digest(run['root']/'execution.json'),'freeze':run['execution']['freeze'],'classification':'strict_nuisance_convergence'} for run in (a,b)]
        if args.inert:require(args.repeat is None,'Inert check takes two runs');result.update(inert(a,b))
        elif args.cold_repeat:
            require(args.repeat is None,'Cold repeat takes two runs');result.update(passed=True,cold_objective_floor=cold_floor(a,b),scope='Cold repeat floor only; no warm equivalence')
        else:
            require(args.repeat is not None,'Independent cold repeat required');r=inspect(args.repeat)
            result['execution_receipts'].append({'root':str(r['root']),'sha256':digest(r['root']/'execution.json'),'freeze':r['execution']['freeze'],'classification':'strict_nuisance_convergence'})
            result.update(compare(a,b,r))
    except Exception as error:result.update(passed=False,error=type(error).__name__+': '+str(error))
    with args.output.open('x') as stream:json.dump(result,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
    print(json.dumps({'passed':result['passed'],'output':str(args.output)}))
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
