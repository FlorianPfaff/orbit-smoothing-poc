"""Offline attribution of a dated first-fit snapshot; never opens a remote path."""
import ast, hashlib, json
from pathlib import Path
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
C=Path('/mnt/d/orbit-segmented-v4/control')
S=Path('/mnt/d/orbit-segmented-v4/validation-07-packet/source')
B='/mnt/seagate10tb/orbit-segmented-v4-florianpfaff'
def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def canon(d): return hashlib.sha256(json.dumps(d,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def read(p): return json.loads(Path(p).read_text())
def require(ok,msg):
    if not ok: raise ValueError(msg)
def pin(p): return {'path':str(p),'sha256':digest(p)}
def pinned(p,h): require(digest(p)==h,'Changed '+str(p)); return read(p)
inputs={
 'snapshot':(C/'campaign09-live05/snapshot.json','0300e2e13a7edd1fc6b0b1418d1c43391f790be904655ed3219cc59fef3f5803'),
 'manifest':(C/'preparation07-terminal01/run/manifest.json','4877f929be8a9eda5d58ff6b4eb0e0fc8b84ea16934a6fbe63fa5a18418fa5c6'),
 'config_capture':(C/'campaign09-first-attempt-config01/manifest.json','1826768f2ab54b5eddea280503ee9ecd0d94f8d0204b621f03c2051d467b91dc'),
 'attempt_capture':(C/'campaign09-first-attempt01/manifest.json','20589f65d981f68ce00c722778bbe0f67f09d7a3a333b6a1180205d0d0be01a9'),
 'inner_proof_review':(C/'campaign09-inner-proof-independent-review01.json','745d577ba5454e4713a6670617b17d54b33a522b1d03342c17fcfbffce799766'),
}
v={k:pinned(*p) for k,p in inputs.items()}
for k in ('config_capture','attempt_capture'):
    for row in v[k]['files']:
        p=inputs[k][0].parent/row['relative_path']
        require(p.stat().st_size==row['bytes'] and digest(p)==row['sha256'],'Capture content changed')
s=v['snapshot'];m=v['manifest'];config=read(inputs['config_capture'][0].parent/'segmented-v4.json');capt=inputs['attempt_capture'][0].parent
job=read(capt/'request.json');supervisor=read(capt/'supervisor.plan.json')
require(m['manifest_hash']==canon({k:v for k,v in m.items() if k!='manifest_hash'}),'Canonical frozen manifest changed')
require(m['manifest_hash']==s['manifest_hash']==v['attempt_capture']['frozen_manifest']['manifest_hash'],'Manifest attribution')
require(s['manifest']['sha256']==inputs['manifest'][1],'Manifest byte attribution')
require(len(m['attempts'])==len(s['attempts'])==68 and len(m['cases'])==28,'Frozen matrix counts')
for expected,observed in zip(m['attempts'],s['attempts']):
    require(all(observed[k]==val for k,val in expected.items()),'Attempt order/identity changed')
a=m['attempts'][0];case=next(c for c in m['cases'] if c['case_id']==a['case_id']);rt=m['runtimes']['dense']
# Independent literal reconstruction of every request field, following the frozen protocol.
expected={**case['fit_request'],'id':a['attempt_id'],'kind':'fit','split':'segmented_v4','family_id':case['family_id'],
 'segmented_profile':a['profile'],'numerics_profile':'qr_lm_staged_jacobian','numerical_controls':config['controls'],
 'source_hash':rt['source_sha256'],'protocol_hash':m['manifest_hash'],'segmented_manifest_hash':m['manifest_hash'],
 'input_manifest_hash':canon(case['fit_request']['estimation_inputs']),
 'backend':{'groops_executable':rt['native']['path'],'command_timeout_seconds':7200.,'retain_native_diagnostics':True,
 'diagnostic_native':m['runtimes']['segmented']['native'],'segmented_solver':rt.get('segmented_solver'),
 'segmented_solver_executable':(rt.get('segmented_solver') or {}).get('path')},'expected_native_binary_sha256':rt['native']['sha256']}
expected['job_sha256']=canon(expected)
require(job==expected,'Full request differs from independently reconstructed frozen job')
require(job['parameters']=={'interval_seconds':1200.,'sigma_velocity_m_s':1e-4,'frame':'CRF'},'Pulse setting changed')
require(job['case']['seed']==610000 and job['case']['duration_hours']==24 and job['case']['coverage']=='normal' and job['case']['atmosphere']=='quiet','Case mismatch')
require(job['case']['mask']['intervals_seconds']==[],'Mask changed')
# Local frozen source is compared to the already accepted captured backing inventory.
backing_path=C/'direct-sealing06-terminal01/sealed/backing-map.json'
seal_capture=pinned(C/'direct-sealing06-terminal01/manifest.json','c006a9df3247984b14fa478d29578ec317b4a276fcc9894ba626dace7b081315')
rows=seal_capture.get('files',seal_capture.get('captured_files',[]))
map_row=next(r for r in rows if r.get('relative_path')=='sealed/backing-map.json')
require(digest(backing_path)==map_row['sha256'],'Captured backing map changed')
backing=read(backing_path);byname={r['canonical']:r['backing'] for r in backing['files']}
for rel in ['src/orbit_poc/segmented/protocol.py','src/orbit_poc/segmented/supervisor.py','src/orbit_poc/comparison/protocol.py']:
    require(digest(S/rel)==byname[B+'/validation-07/source/'+rel]['sha256'],'Local frozen protocol differs')
module=ast.parse((S/'src/orbit_poc/segmented/protocol.py').read_text())
worker=next(ast.literal_eval(n.value) for n in module.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='WORKER' for t in n.targets))
directory=config['output_dir']+'/attempts/'+a['attempt_id'];source=B+'/validation-07/source'
expected_supervisor={'schema':'orbit-poc-segmented-supervision-plan-v1',
 'argv':[rt['python']['path'],'-s','-c',worker,source,directory+'/request.json',directory+'/worker-result.json',json.dumps(config['resources']['reserved_cpu_ids'])],
 'cwd':source,'log_path':directory+'/worker.log','receipt_path':directory+'/supervisor.json','working_directory':directory,
 'timeout_seconds':7200.,'max_process_tree_rss_bytes':config['resources']['maximum_process_tree_rss_bytes'],
 'min_free_disk_bytes':config['resources']['minimum_free_output_bytes'],
 'helper_sha256':digest(S/'src/orbit_poc/segmented/supervisor.py'),'boot_id':s['host']['boot_id']}
require(supervisor==expected_supervisor,'Full supervisor differs from frozen recipe')
require(config['resources']['reserved_cpu_ids']==[24] and config['resources']['threads']==1 and supervisor['max_process_tree_rss_bytes']==8589934592,'Resource budgets changed')
observed_attempt=s['attempts'][0]
require(observed_attempt['request']['sha256']==digest(capt/'request.json'),'Live request attribution')
require(observed_attempt['supervisor']['content']['plan_sha256']==digest(capt/'supervisor.plan.json'),'Live supervisor attribution')
require(observed_attempt['supervisor']['content']['argv']==supervisor['argv'] and observed_attempt['supervisor']['content']['status']=='running','Live supervisor state')
require(s['current_nonterminal_attempt_ids']==[a['attempt_id']] and s['terminal_count']==s['terminal_prefix']==0 and all(x['state']=='not_started' for x in s['attempts'][1:]),'Started/terminal scope differs')
require(len(s['native_processes'])==1,'Expected exactly one native workload at cutoff')
n=s['native_processes'][0];owned={p['pid']:p for p in s['owned_processes']}
require(n['argv']==[rt['native']['path'],directory+'/point-001-initial/profile.xml'],'Native argv attribution')
require(n['command_sha256']==hashlib.sha256(b'\0'.join(a.encode() for a in n['argv'])+b'\0').hexdigest(),'Native command digest')
require(n['executable']==rt['native']['path'] and n['native_workload'] is True and n['affinity']==[24],'Native path/affinity')
sealed_native=byname[rt['native']['path']]
require(sealed_native['sha256']==rt['native']['sha256'] and all(n['executable_identity'][k]==sealed_native[k] for k in ('device','inode','bytes')),'Native sealed device/inode/size attribution')
require(s['expected_native_pins']['dense']==rt['native'],'Frozen native digest attribution')
chain=[];p=n
while True:
    chain.append({'pid':p['pid'],'start_ticks':p['start_ticks'],'parent':p['parent'],'affinity':p['affinity']})
    if p['pid']==s['launch']['content']['driver_process']['pid']: break
    require(p['parent'] in owned,'Missing owned ancestry');p=owned[p['parent']]
require(s['driver_identity_matches'] is True and s['driver_live'] is True,'Driver not live')
require(n['selected_environment']=={'HOME':B+'/validation-07/temporary/fit-private/home','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1','NUMEXPR_NUM_THREADS':'1'},'Native environment differs')
require(n['namespaces']==owned[19408]['namespaces'],'Native not in checked inner namespace')
require(not s['process_visibility_errors'],'Process visibility errors')
obs=s['observer_latest']['content'];require(obs['status']=='clear' and not obs['native_conflict_seen'] and not obs['sampling_incomplete_seen'] and not obs['process_read_errors'] and not obs['native_conflicts'],'Observer conflict/incomplete')
require(len(s['locks'])==3 and all(len(x['kernel_locks'])==1 and x['kernel_locks'][0]['owned_at_snapshot'] is True and not x['kernel_locks'][0]['waiting'] for x in s['locks']),'Locks not owned')
require(s['prelaunch_probe']['sha256']==v['inner_proof_review']['proof']['sha256'] and s['prefix_before']['sha256']==v['inner_proof_review']['prefix_before']['sha256'],'Actual campaign proof/prefix changed')
x=ET.parse(capt/'point-001-initial/profile.xml')
require(x.findtext('.//supportsIntegerAmbiguities')=='0','Not float ambiguities')
pulses=x.find('.//stochasticPulse/uniformSampling');require(pulses.findtext('sampling')=='1200/86400' and pulses.findtext('offsetSeconds')=='1200','Pulse interval XML')
pulseprior=next(e for e in x.findall('.//constraints') if e.findtext('name')=='constraint.pulses')
require(pulseprior.findtext('sigma')=='100.0' and pulseprior.findtext('bias')=='0' and pulseprior.findtext('relativeToApriori')=='0','Native micrometre/second full pulse prior changed')
require(x.findtext('.//orbitPocNumerics/inputfilePulseReference')==directory+'/point-001-initial/full_pulses_um_s.txt','Full pulse reference attribution')
require(x.findtext('.//timeSeries/uniformSampling/sampling')=='30/86400','GNSS cadence XML')
result={'schema':'orbit-poc-campaign09-first-native-offline-audit-v1','status':'passed','created_at':datetime.now(timezone.utc).isoformat(),
 'cutoff':s['captured_at'],'inputs':{k:pin(p[0]) for k,p in inputs.items()},'script':pin(__file__),
 'frozen_manifest_hash':m['manifest_hash'],'config':pin(inputs['config_capture'][0].parent/'segmented-v4.json'),
 'request':pin(capt/'request.json'),'profile':pin(capt/'point-001-initial/profile.xml'),'supervisor_plan':pin(capt/'supervisor.plan.json'),
 'request_reconstruction':'Exact dictionary equality across every field; independently reconstructed from frozen case, runtime, manifest, and actual config.',
 'supervisor_reconstruction':'Exact dictionary equality including worker source, boot, CPU, timeout, memory and storage limits.',
 'job_sha256':job['job_sha256'],'case_id':a['case_id'],'attempt_id':a['attempt_id'],'method':job['method'],'profile_name':a['profile'],
 'parameters':job['parameters'],'numerical_controls':config['controls'],'resource_limits':config['resources'],
 'native_observed':n,'expected_native_pin':rt['native'],'sealed_native_identity':sealed_native,'owned_ancestry':chain,
 'observer_at_cutoff':obs,'started_attempts':1,'terminal_attempts':0,'planned_attempts':68,
 'native_bytes_rehashed_during_fit':False,'remote_commands_executed':False,'scientific_workload_started_by_audit':False,
 'limits':['The process snapshot is dated and non-atomic; it proves observed execution, not current liveness indefinitely.',
 'The profile XML was captured after the cutoff; request and supervisor hashes match cutoff evidence. Its full byte identity is retained, and key pulse/float/cadence conventions were inspected; XML generation was not rerun.',
 'No convergence, accepted covariance, completed fit, accuracy or release claim follows from this handoff.']}
out=C/'campaign09-first-native-reconstruction02.json'
with out.open('x') as f: json.dump(result,f,sort_keys=True,indent=2);f.write('\n')
print(json.dumps({'status':'passed','result':pin(out),'script':pin(__file__),'request_exact':True,'supervisor_exact':True,'started':1,'terminal':0,'planned':68}))
