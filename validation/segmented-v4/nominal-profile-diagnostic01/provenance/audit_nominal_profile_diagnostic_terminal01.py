from pathlib import Path
from copy import deepcopy
import datetime, hashlib, importlib.util, json, xml.etree.ElementTree as ET
import numpy as np
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');R=B/'closure-diagnostic-01';C=R/'control';O=R/'run/replay'
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p),'bytes':Path(p).stat().st_size}
def read(p):return json.loads(Path(p).read_bytes())
def check(r):assert sha(r['path'])==r['sha256'];return Path(r['path'])
assert sha(C/'plan.json')=='3c20f3a4c04a3df8bcb68a98ab047f24a87de72a4b2e617ea7508666bf9568dc'
assert sha(C/'pipeline.json')=='0efc34c0b0ecbd32472e9c934c5675e253b5699e7ff5a42c138cbf5c910dad6a'
assert sha(O/'result.json')=='c7e1c7f0c283d9281ccc74f55d938dfb80c2eb243abca14a6f69810da1a23744'
p=read(C/'plan.json');pipeline=read(C/'pipeline.json');result=read(O/'result.json');staging=read(C/'staging.json')
for k in ('execution','driver','worker','controller','native','source_freeze'):check(p[k])
spec=importlib.util.spec_from_file_location('owned_driver',p['driver']['path']);d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
e=d.load_execution(p['execution']['path'])
for name,v in p['inputs'].items():
    assert sha(d.resolved_host_path(v['path'],e))==v['sha256']
    original=staging['input_attribution'][name]['physical_original'];check(original)
    assert original['sha256']==v['sha256']
check(staging['original_failure'])
assert pipeline['status']=='passed_diagnostic' and pipeline['returncode']==0 and pipeline['interrupted_or_timeout'] is False
assert pipeline['plan']['path']==str(C/'plan.json') and pipeline['plan']['sha256']==sha(C/'plan.json')
assert pipeline['fit_attempts']==0 and pipeline['release_evidence'] is False and pipeline['elapsed_seconds']<7200 and pipeline['peak_owned_rss_bytes']<8589934592
assert pipeline['cleanup']['verified'] is True and pipeline['final_cleanup']['verified'] is True and pipeline['final_cleanup']['errors']==[]
assert pipeline['admission']['status']=='admitted' and pipeline['admission']['conflicting_processes']==[]
assert pipeline['admission']['boot_id']==e['host']['boot_id']==Path('/proc/sys/kernel/random/boot_id').read_text().strip()
assert pipeline['admission']['driver_identity']['argv']==['/usr/bin/python3',p['controller']['path'],'--plan',str(C/'plan.json'),'--sha256',sha(C/'plan.json')]
expected_argv=[e['runtime_artifacts']['control_python']['path'],e['paths']['wrapper'],'--execution',p['execution']['path'],'--execution-sha256',p['execution']['sha256'],'--','/usr/bin/taskset','-c','24',e['paths']['python'],p['worker']['path'],'--plan',str(C/'plan.json'),'--sha256',sha(C/'plan.json')]
assert pipeline['argv']==expected_argv
identities={(x['pid'],x['start_ticks']) for c in pipeline['final_cleanup']['commands'] for x in c['identities']}
driver=pipeline['admission']['driver_identity'];identities.add((driver['pid'],driver['start_ticks']))
cleanup=[]
for pid,tick in sorted(identities):
    try:
        f=(Path('/proc')/str(pid)/'stat').read_text().rsplit(')',1)[1].split()
        assert int(f[19])!=tick or f[0]=='Z'
        cleanup.append({'pid':pid,'start_ticks':tick,'current_start_ticks':int(f[19]),'current_state':f[0],'executing':False})
    except FileNotFoundError:cleanup.append({'pid':pid,'start_ticks':tick,'absent':True})
assert result['plan_sha256']==sha(C/'plan.json') and result['native']==p['native']
assert result['status']=='closed' and result['converged'] is True and result['fit_attempts']==0 and result['release_evidence'] is False
assert result['maximum_iterations']==10 and result['position_tolerance_m']==2e-6 and result['velocity_tolerance_m_s']==3e-9
assert len(result['iterations'])==2 and [x['closed'] for x in result['iterations']]==[False,True]
original_init=read(p['inputs']['initialization']['path']);target=np.array(original_init['fixed_initial_state_si'])
assert np.array_equal(target,np.array(result['fixed_initial_state_si']))
prev=np.loadtxt(p['inputs']['initial_text']['path'],skiprows=6);epochs=prev[:,0];previous=prev[:,1:7]
assert len(previous)==34560==result['state_epochs'] and np.array_equal(previous[0],target)
template=ET.parse(p['inputs']['template']['path']).getroot()
def semantic(n):return (n.tag,tuple(sorted(n.attrib.items())),(n.text or '').strip(),tuple(semantic(x) for x in n))
reference=Path(p['inputs']['initial_orbit']['path']);rows=[]
for i,row in enumerate(result['iterations'],1):
    folder=O/f'iteration-{i:02d}';execution=row['execution'];xml=folder/'propagate.xml'
    assert execution['command']==[p['native']['path'],str(xml)] and execution['config_sha256']==sha(xml)
    assert execution['returncode']==0 and execution['timed_out'] is False and execution['blas_openmp_threads']==1 and execution['native_binary_sha256']==p['native']['sha256']
    assert execution['log']==str(folder/'propagate.log')
    t=ET.parse(xml).getroot();programs=[list(x)[0] for x in t.findall('program')];base=[list(x)[0] for x in template.findall('program')]
    assert len(programs)==3
    assert programs[0].findtext('orbitPocDerivativeProfile')=='synthetic_complete_v1' and programs[0].findtext('orbitPocDerivativeDiagnostics')==str(folder/'derivatives.json')
    expected=[{'inputfileOrbit':str(reference),'outputfileVariational':str(folder/'variational.dat')},
              {'inputfileVariational':str(folder/'variational.dat'),'outputfileOrbit':str(folder/'nominal.dat'),'inputfileInitialState':p['inputs']['initial_state']['path']},
              {'inputfile':str(folder/'nominal.dat'),'outputfile':str(folder/'nominal.txt')}]
    for n,original,changes in zip(programs,base,expected):
        for key,value in changes.items():assert n.findtext(key)==value;n.find(key).text=original.findtext(key)
    for key in ('orbitPocDerivativeProfile','orbitPocDerivativeDiagnostics'):programs[0].remove(programs[0].find(key))
    assert semantic(t)==semantic(template)
    states=np.loadtxt(folder/'nominal.txt',skiprows=6);assert np.array_equal(states[:,0],epochs);states=states[:,1:7]
    delta=states-previous;dp=float(np.linalg.norm(delta[:,:3],axis=1).max());dv=float(np.linalg.norm(delta[:,3:],axis=1).max())
    assert dp==row['maximum_position_change_m'] and dv==row['maximum_velocity_change_m_s']
    assert np.array_equal(states[0],target) and row['maximum_initial_state_error_si']==[0.0]*6
    assert row['closed']==(dp<2e-6 and dv<3e-9)
    derivative=read(folder/'derivatives.json');assert derivative==row['derivatives']
    assert derivative['profile']=='synthetic_complete_v1' and derivative['omitted_terms']==[]
    assert derivative['mean_solve_coordinates']=='residual_then_single_absolute_restore_v1' and derivative['reference_kinematics']=='fitted_equinoctial_long_double_low_parts_v1'
    assert derivative['synthetic_force_arithmetic']=='configured_crf_parts_stable_reference_v1'
    rows.append({'iteration':i,'maximum_position_change_m':dp,'maximum_velocity_change_m_s':dv,'fixed_initial_state_exact':True,'only_declared_xml_delta':True,'artifacts':[pin(folder/x) for x in ['propagate.xml','propagate.execution.json','propagate.log','nominal.dat','nominal.txt','variational.dat','derivatives.json']]})
    previous=states;reference=folder/'nominal.dat'
failed=Path(staging['input_attribution']['initialization']['physical_original']['path']).parent
legacy=np.loadtxt(failed/'iteration-10/nominal.txt',skiprows=6)[:,1:7]
diff=previous-legacy
assert not (R/'run/manifest.json').exists() and not (R/'run/attempts').exists()
print(json.dumps({'schema':'orbit-poc-nominal-profile-diagnostic-terminal-independent-review-v1','passed':True,
 'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'plan':pin(C/'plan.json'),'pipeline':pin(C/'pipeline.json'),'result':pin(O/'result.json'),'original_failed_initialization':pin(failed/'initialization.json'),
 'owned_process_cleanup':cleanup,'independently_recomputed_iterations':rows,'final_position_change_m':rows[-1]['maximum_position_change_m'],'final_velocity_change_m_s':rows[-1]['maximum_velocity_change_m_s'],
 'new_closed_minus_failed_legacy_final':{'maximum_position_difference_m':float(np.linalg.norm(diff[:,:3],axis=1).max()),'maximum_velocity_difference_m_s':float(np.linalg.norm(diff[:,3:],axis=1).max()),'scope':'Comparison to a non-closed legacy iterate, not an accuracy or equivalent-solution estimate.'},
 'fit_attempts':0,'release_ready':False,'conclusion':'The same archived48h initial state/reference closes in two iterations when the existing corrected synthetic profile is selected. All thresholds, input bytes and native executable are unchanged; initial state is restored exactly each time. The tested omission is demonstrated to cause this preparation failure; this diagnostic does not identify which individual staged arithmetic/Jacobian change is necessary.',
 'scope':'Read-only independent reconstruction of both saved trajectory changes, exact XML and native attribution, original input preservation and current-owned cleanup. Supports a separately versioned v4 preparation adapter correction; does not constitute a production preparation run or benchmark fit.'},sort_keys=True))
