from pathlib import Path
import datetime,hashlib,json,os,xml.etree.ElementTree as ET
import numpy as np
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');C=B/'preparation-02/control05';R=B/'preparation-02/backings/run';CAN=B/'validation-03/run';BAD='9f71eb67221fe67a092ea4566e05bce837b47c5c4e6a2d917909ced474aa03c4';GOOD='129f82a9d3590663cf57650eb1a2341bd247332e00b2ce087cb83470186ec68c'
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p),'bytes':Path(p).stat().st_size}
def resolve(p):
 p=Path(p)
 try:return R/p.relative_to(CAN)
 except ValueError:return p
def checked(r):
 p=resolve(r['path']);assert sha(p)==r['sha256'],r;return p
def read(p):return json.loads(Path(p).read_text())
pipeline=C/'pipeline.json';assert sha(pipeline)=='ec50547ac0a02d6bf80705350735809e4794e64e564cdf29d25bcc66508c422e';p=read(pipeline)
assert p['status']=='failed_or_blocked' and p['benchmark_attempts']==0 and p['release_ready'] is False
assert p['final_cleanup']['verified'] is True and p['final_cleanup']['errors']==[]
assert p['preparation']['returncode']==1 and p['preparation']['interrupted_or_timeout'] is False
assert [(x['phase'],x['returncode']) for x in p['checks']]==[('before',0),('after',1)]
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();assert boot==p['admission']['boot_id']=='95156dd4-0d4c-499d-a214-8883a2d650fa'
identities={(x['pid'],x['start_ticks']) for cmd in p['final_cleanup']['commands'] for x in cmd['identities']};identities.add((p['admission']['driver_identity']['pid'],p['admission']['driver_identity']['start_ticks']))
cleanup=[]
for pid,tick in sorted(identities):
 try:
  f=(Path('/proc')/str(pid)/'stat').read_text().rsplit(')',1)[1].split();actual=int(f[19]);state=f[0]
  assert actual!=tick or state=='Z',(pid,tick,state);cleanup.append({'pid':pid,'start_ticks':tick,'current_start_ticks':actual,'current_state':state,'executing':False})
 except FileNotFoundError:cleanup.append({'pid':pid,'start_ticks':tick,'absent':True})
job=R/'preparation-jobs'/('prefix-'+BAD);request=job/'request.json';assert sha(request)=='fa646eee50d30d6db54a51a40411e1bb81e6ca3b72bee6ea29425e2c6bc9e39d';q=read(request)
assert q['case']['case_id']=='leo500-quiet-normal-groops_pulses-48h' and q['case']['case']['duration_hours']==48 and q['case']['case']['seed']==610000
assert q['case']['parameters']=={'frame':'CRF','interval_seconds':1200.0,'sigma_velocity_m_s':0.0001}
result=read(job/'execution.json');supervision=read(job/'supervisor.json');h=result['harness_execution']
assert result['status']=='failed' and result['converged'] is result['covariance_valid'] is False
assert h['owned_process_group_cleaned'] is True and h['returncode']==1 and h['status']=='failed' and h['elapsed_seconds']<7200 and h['peak_process_tree_rss_bytes']<8589934592
checked(h['log']);checked(h['supervisor_receipt']);assert supervision['cleanup']==h['cleanup'] and supervision['cleanup']['verified'] is True and supervision['cleanup']['remaining']==[] and supervision['cleanup']['empty_tree_certificate']=='kernel_ECHILD'
assert not (job/'checkpoint.json').exists() and not (job/'worker-result.json').exists()
assert 'Nominal-force trajectory failed to close within the iteration limit' in (job/'worker.log').read_text()
status=read(R/'preparation-status.json');assert status['status']=='blocked' and status['expected_attempts']==68
assert not (R/'manifest.json').exists() and not (R/'attempts').exists()
sealed=[]
for name in ('leo500-quiet-610000-continuous72h','prefix-'+GOOD):
 d=R/'preparation-jobs'/name;i=read(d/'checkpoint.json');v=read(checked(i['result']));checked(i['output_inventory']);assert v['status']=='prepared' and v['harness_execution']['owned_process_group_cleaned'] is True
 sealed.append({'component':name,'checkpoint':pin(d/'checkpoint.json'),'result':i['result'],'output_inventory':i['output_inventory'],'scope':'Checkpoint attribution and referenced metadata verified; output payload inventory was not rehashed by this diagnostic.'})
metrics={}
for key,hours in ((GOOD,24),(BAD,48)):
 root=R/'preparation/prefixes'/key/'nominal-initialization';ip=root/'initialization.json';v=read(ip);assert v['maximum_iterations']==10 and v['position_tolerance_m']==2e-6 and v['velocity_tolerance_m_s']==3e-9
 assert v['native_binary_sha256']=='a66949456ad67b816d09f2f14df792c68c2685f5304139499e4d90092fd75b22'
 assert v['helper_sha256']=='0019b9df924b30f7c1ded518533db1e1a9dc2f1dcf1fc8571d6fbe9797bab0fd6655' or v['helper_sha256']=='0019b9df924b30f7c1ded518533db1e1a9dc2f1fc8571d6fbe9797bab0fd6655'
 target=np.array(v['fixed_initial_state_si']);a=np.loadtxt(root/'initial/nominal.txt',skiprows=6);previous=a[:,1:7];epochs=a[:,0];rows=[];allpins=[pin(root/'initial/nominal.txt')]
 assert len(a)==v['state_epochs']==hours*720
 for recorded in v['iterations']:
  k=recorded['iteration'];f=root/f'iteration-{k:02d}/nominal.txt';a=np.loadtxt(f,skiprows=6);assert np.array_equal(a[:,0],epochs);states=a[:,1:7];delta=states-previous
  dp=np.linalg.norm(delta[:,:3],axis=1);dv=np.linalg.norm(delta[:,3:],axis=1);mp=float(dp.max());mv=float(dv.max())
  assert mp==recorded['maximum_position_change_m'] and mv==recorded['maximum_velocity_change_m_s']
  radial=states[:,:3]/np.linalg.norm(states[:,:3],axis=1)[:,None];normal=np.cross(states[:,:3],states[:,3:]);normal/=np.linalg.norm(normal,axis=1)[:,None];along=np.cross(normal,radial);rac=np.column_stack([np.sum(delta[:,:3]*x,axis=1) for x in (radial,along,normal)])
  start_delta=states[0]-target;first=epochs<epochs[0]+1;second=~first
  row={**recorded,'recomputed_from_saved_text':True,'position_argmax_index':int(dp.argmax()),'position_argmax_elapsed_s':5*int(dp.argmax()),'first_day_maximum_position_m':float(dp[first].max()),'second_day_maximum_position_m':float(dp[second].max()) if np.any(second) else None,'maximum_initial_state_error_si':start_delta.tolist(),'rac_maximum_absolute_position_change_m':np.max(np.abs(rac),axis=0).tolist(),'rac_rms_position_change_m':np.sqrt(np.mean(rac*rac,axis=0)).tolist()};rows.append(row);allpins.append(pin(f));previous=states
 for ex in v['executions']:
  assert ex['returncode']==0 and ex['timed_out'] is False and ex['blas_openmp_threads']==1 and ex['native_binary_sha256']==v['native_binary_sha256'];assert sha(resolve(ex['command'][1]))==ex['config_sha256']
 cfg=ET.parse(checked(v['source_configuration'])).getroot();program=cfg.find('.//PreprocessingVariationalEquation');fields={x.tag:x.text for x in program if 'orbitPoc' in x.tag}
 metrics[str(hours)]={'initialization':pin(ip),'status':v['status'],'converged':v['converged'],'position_tolerance_m':v['position_tolerance_m'],'velocity_tolerance_m_s':v['velocity_tolerance_m_s'],'fixed_initial_state_si':v['fixed_initial_state_si'],'native_calls':len(v['executions']),'all_native_calls_successful':True,'state_epochs':v['state_epochs'],'iterations':rows,'state_export_pins':allpins,'configured_explicit_orbitPoc_fields':fields,'physical_force_hash':v['physical_force_hash'],'closure_is_pre_fit_initialization':True}
assert metrics['24']['converged'] is True and metrics['48']['converged'] is False
print(json.dumps({'schema':'orbit-poc-preparation-numerical-failure-independent-review-v1','passed':True,'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'pipeline':pin(pipeline),'request':pin(request),'execution':pin(job/'execution.json'),'supervisor':pin(job/'supervisor.json'),'worker_log':pin(job/'worker.log'),'status':pin(R/'preparation-status.json'),'boot_id':boot,'owned_process_cleanup':cleanup,'sealed_prior_components':sealed,'closure':metrics,'measured_failure':'48-hour pre-fit fixed-initial-state nominal closure exhausted ten iterations without satisfying unchanged 2 micrometre / 3e-9 m/s criteria; all native propagations completed normally.','not_measured':['No LM objective or posterior covariance exists for this preparation failure.','The nonmonotone late corrections do not by themselves identify the arithmetic operation causing the residual floor.','No repeated-identical-input or higher-precision native diagnostics were launched.'],'fit_attempts':0,'scope':'Read-only terminal attribution and independent recomputation from archived trajectories. Failed component and earlier checkpoints remain unchanged; no threshold relaxation, replacement case or workload launch.'},sort_keys=True))
