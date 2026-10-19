"""Narrow offline process/status attribution; no terminal scientific audit."""
from pathlib import Path
import hashlib,json
from datetime import datetime,timezone
C=Path('/mnt/d/orbit-segmented-v4/control')
def h(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def r(p):return json.loads(p.read_bytes())
def pin(p):return {'path':str(p),'sha256':h(p)}
def need(ok,msg):
 if not ok:raise ValueError(msg)
sp=C/'campaign09-live06/snapshot.json';need(h(sp)=='2f728104b34d1d483337db4e10d08f7b91cfc8a8d9ef813eaad335dd28371cb5','Snapshot changed');s=r(sp)
mp=C/'preparation07-terminal01/run/manifest.json';need(h(mp)=='4877f929be8a9eda5d58ff6b4eb0e0fc8b84ea16934a6fbe63fa5a18418fa5c6','Frozen manifest changed');m=r(mp)
need(s['manifest']['sha256']==h(mp) and s['manifest_hash']==m['manifest_hash'],'Manifest attribution')
need(len(s['attempts'])==len(m['attempts'])==68,'Matrix size')
for actual,frozen in zip(s['attempts'],m['attempts']):need(all(actual[k]==v for k,v in frozen.items()),'Frozen attempt order/identity changed')
a,b=s['attempts'][:2]
need(a['attempt_id']=='leo500-quiet-normal-groops_pulses-24h--dense_corrected' and a['status']=='timeout' and a['state']=='terminal_record_present','First reported terminal classification')
need(b['attempt_id']=='leo500-quiet-normal-groops_pulses-24h--segmented_1h' and b['state']=='started_without_terminal_record','Second active attempt')
need(all(x['state']=='not_started' and not x['directory_present'] for x in s['attempts'][2:]),'Later attempt unexpectedly started')
need(s['terminal_count']==s['terminal_prefix']==1 and s['terminal_status_counts']=={'timeout':1} and s['current_nonterminal_attempt_ids']==[b['attempt_id']],'Status projection counts')
need(b['supervisor']['content']['status']=='running' and b['supervisor']['content']['returncode'] is None,'Supervisor not running')
need(s['driver_identity_matches'] and s['driver_live'] and not s['process_visibility_errors'],'Driver/visibility')
need(len(s['native_processes'])==1,'Native workload count')
n=s['native_processes'][0];rt=m['runtimes']['segmented']['native']
need(s['expected_native_pins']['segmented']==rt and n['executable']==rt['path'] and n['argv'][0]==rt['path'],'Segmented native pin')
need(n['argv'][1]=='/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/validation-07/run/attempts/'+b['attempt_id']+'/point-002-repeat/profile.xml','Active XML attribution')
need(n['command_sha256']==hashlib.sha256(b'\0'.join(x.encode() for x in n['argv'])+b'\0').hexdigest(),'Native command digest')
bp=C/'direct-sealing06-terminal01/sealed/backing-map.json';cp=C/'direct-sealing06-terminal01/manifest.json';need(h(cp)=='c006a9df3247984b14fa478d29578ec317b4a276fcc9894ba626dace7b081315','Seal capture changed');cap=r(cp);rows=cap.get('files',cap.get('captured_files',[]));br=next(x for x in rows if x['relative_path']=='sealed/backing-map.json');need(h(bp)==br['sha256'],'Backing map changed')
identity=next(x['backing'] for x in r(bp)['files'] if x['canonical']==rt['path']);need(identity['sha256']==rt['sha256'] and all(n['executable_identity'][k]==identity[k] for k in ['device','inode','bytes']),'Native observed identity differs')
need(n['affinity']==[24] and n['native_workload'],'Native CPU')
need(n['selected_environment']=={'HOME':'/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/validation-07/temporary/fit-private/home','MKL_NUM_THREADS':'1','NUMEXPR_NUM_THREADS':'1','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'},'Numerical environment')
owned={x['pid']:x for x in s['owned_processes']};chain=[];node=n
while True:
 chain.append({'pid':node['pid'],'start_ticks':node['start_ticks'],'parent':node['parent'],'affinity':node['affinity']})
 if node['pid']==s['launch']['content']['driver_process']['pid']:break
 need(node['parent'] in owned,'Owned ancestry gap');node=owned[node['parent']]
need(n['namespaces']==owned[19408]['namespaces'],'Native outside checked inner namespace')
need(len(s['locks'])==3 and all(len(x['kernel_locks'])==1 and x['kernel_locks'][0]['owned_at_snapshot'] and not x['kernel_locks'][0]['waiting'] for x in s['locks']),'Lock observation')
o=s['observer_latest']['content'];need(o['status']=='clear' and not o['native_conflict_seen'] and not o['sampling_incomplete_seen'] and not o['native_conflicts'] and not o['process_read_errors'],'Observer conflict or incomplete')
oldpub=Path('/mnt/d/orbit-segmented-v4/source/validation/segmented-v4/campaign09/publication-manifest.json');need(h(oldpub)=='bdfd4b11837398bea057d7d41a650da69182cf8a7d8792135685b9a3238fa287','Old report changed')
summary={'schema':'orbit-poc-campaign09-follow-on-status-v1','cutoff':s['captured_at'],'source_snapshot':pin(sp),'frozen_manifest':pin(mp),'manifest_hash':m['manifest_hash'],'planned_attempts':68,'started_attempts':2,'terminal_attempts':1,'reported_terminal_status_counts':s['terminal_status_counts'],'active_attempts':1,'not_started_attempts':66,'reported_successful_completions':0,'first_attempt':{k:a[k] for k in ['attempt_id','order','profile','state','status','record','result']},'active_attempt':{'attempt_id':b['attempt_id'],'order':b['order'],'profile':b['profile'],'request':b['request'],'supervisor_receipt':{k:v for k,v in b['supervisor'].items() if k!='content'},'supervisor_status':'running','supervisor_elapsed_seconds':b['supervisor']['content']['elapsed_seconds'],'observed_peak_process_tree_rss_bytes':b['supervisor']['content']['peak_process_tree_rss_bytes'],'native_process':n,'expected_native_pin':rt},'controller_live':True,'observer_latest':o,'release_ready':False,'limitations':['The dense timeout is the reported terminal classification. Its complete result, cleanup, numerical diagnostics and scientific validity are not independently audited here.','The second process was present in D (uninterruptible sleep) state at one non-atomic snapshot; this alone does not establish a hang or convergence.','Native executable bytes and growing logs were not rehashed during fitting. Identity uses recorded path/device/inode/size against the previously sealed inventory.','The original campaign09 report retains its earlier 01:41:13 UTC cutoff. This separate follow-on status advances only the observed process/terminal counts.','No success, covariance acceptance, speed or scientific comparison claim follows from this status.']}
out=C/'campaign09-status06-summary01.json'
with out.open('x') as f:json.dump(summary,f,sort_keys=True,indent=2);f.write('\n')
review={'schema':'orbit-poc-campaign09-follow-on-status-independent-review-v1','status':'accepted_dated_process_status_projection','created_at':datetime.now(timezone.utc).isoformat(),'cutoff':s['captured_at'],'script':pin(Path(__file__)),'summary':pin(out),'snapshot':pin(sp),'frozen_manifest':pin(mp),'original_publication_unchanged':pin(oldpub),'first_two_frozen_ids_verified':True,'all_68_ordered_ids_verified':True,'native_observed_identity':n['executable_identity'],'expected_native_pin':rt,'owned_ancestry':chain,'observer_clear':True,'planned_attempts':68,'started_attempts':2,'terminal_attempts':1,'active_attempts':1,'reported_timeouts':1,'reported_successful_completions':0,'scientific_audit_performed':False,'remote_operations':False,'release_ready':False,'scope':'Only exact snapshot projection, frozen attempt ordering, active native process identity, resource environment and owned ancestry. Reported timeout not independently reclassified.'}
rp=C/'campaign09-status06-independent-review01.json'
with rp.open('x') as f:json.dump(review,f,sort_keys=True,indent=2);f.write('\n')
print(json.dumps({'review':pin(rp),'summary':pin(out),'script':pin(Path(__file__))}))
