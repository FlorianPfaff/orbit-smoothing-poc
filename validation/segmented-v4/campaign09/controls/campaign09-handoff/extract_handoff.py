#!/usr/bin/env python3
"""Project fixed local campaign records without querying a host or executing controls."""
from collections import Counter
from pathlib import Path
import hashlib,json
C=Path('/mnt/d/orbit-segmented-v4/control');HERE=Path(__file__).resolve().parent
FIRST='leo500-quiet-normal-groops_pulses-24h--dense_corrected'
SNAPSHOTS=[('02','4520c2b960feecf9f773aba6e1fdef8ca9ed037f67bd9f663064516226ce2ff1'),
 ('03','93d2d2b357faf664f8cf176eeecbfdec4407f3c7cf70406cc9f9baed102bb686'),
 ('04','edd6db62a18d189a9dd4ce3aa393b1dbf8b4ec819b1bcae14e3d59d2988e806b'),
 ('05','0300e2e13a7edd1fc6b0b1418d1c43391f790be904655ed3219cc59fef3f5803')]
def pin(p):return {'path':str(p),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def read_checked(p,h):
 assert pin(p)['sha256']==h,str(p)
 return json.loads(p.read_bytes())
def without_content(v):return {k:x for k,x in v.items() if k!='content'}
def save(name,v):
 data=(json.dumps(v,indent=2,sort_keys=True)+'\n').encode();p=HERE/name
 if p.exists():assert p.read_bytes()==data,str(p)
 else:
  with p.open('xb') as f:f.write(data)
rows=[]
for suffix,h in SNAPSHOTS:
 p=C/('campaign09-live'+suffix)/'snapshot.json';v=read_checked(p,h)
 assert v['terminal_count']==v['terminal_prefix']==0 and v['process_visibility_errors']==[]
 assert v['driver_identity_matches'] and v['driver_live'] and len(v['attempts'])==68
 active=[]
 for r in v['attempts']:
  if r['directory_present']:
   a={k:r[k] for k in ['attempt_id','case_id','order','profile','directory_present','state']}
   if 'request' in r:a['request']=without_content(r['request'])
   if 'supervisor' in r:
    s=r['supervisor'];a['supervisor']={**without_content(s),'recorded_state':{k:s['content'][k] for k in ['status','elapsed_seconds','returncode','plan_sha256','peak_process_tree_rss_bytes','owned_process_group_cleaned']}}
   active.append(a)
 owned=[{k:r[k] for k in ['pid','start_ticks','parent','state','affinity','native_workload','command_sha256','selected_environment','executable','executable_identity','namespaces']} for r in v['owned_processes']]
 observer=without_content(v['observer_latest'])
 if 'content' in v['observer_latest']:
  x=v['observer_latest']['content'];observer['recorded_state']={k:x[k] for k in ['observed_at','status','owner','native_conflict_seen','native_conflicts','process_read_errors','sampling_incomplete_seen','plan_sha256']}
 locks=[{'path':r['path'],'device':r['device'],'inode':r['inode'],'holders':[{k:x[k] for k in ['owner_pid','owner_start_ticks','owned_at_snapshot','waiting']} for x in r['kernel_locks']]} for r in v['locks']]
 row={'snapshot':suffix,'source_snapshot':pin(p),'captured_at':v['captured_at'],'host':v['host'],
      'driver_live':v['driver_live'],'driver_identity_matches':v['driver_identity_matches'],
      'pipeline_pin':without_content(v['pipeline']),'pipeline_status':v['pipeline']['content']['status'],
      'planned_fit_attempts':68,'fit_attempts_started':len(active),'fit_attempts_completed':v['terminal_count'],
      'terminal_prefix':v['terminal_prefix'],'active_attempts':active,'owned_processes':owned,
      'native_processes':v['native_processes'],'expected_native_pins':v['expected_native_pins'],
      'locks':locks,'observer_latest':observer,'prelaunch_probe':without_content(v['prelaunch_probe']),
      'process_visibility_errors':v['process_visibility_errors']}
 if suffix!='05':assert active==[] and v['native_processes']==[]
 else:
  assert v['captured_at']=='2026-10-19T01:41:13.968477+00:00' and len(active)==1 and active[0]['attempt_id']==FIRST and active[0]['order']==0
  assert len(v['native_processes'])==1
  n=v['native_processes'][0];assert n['pid']==20782 and n['start_ticks']==135757891 and n['affinity']==[24]
  assert n['executable_identity']=={'bytes':24071920,'device':2048,'inode':217255543}
  assert n['executable']==v['expected_native_pins']['dense']['path']
  assert n['argv'][1].endswith('/'+FIRST+'/point-001-initial/profile.xml')
  assert all(n['selected_environment'][k]=='1' for k in ['OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'])
  assert n['selected_environment']['HOME'].endswith('/validation-07/temporary/fit-private/home')
  assert all(r['holders'] and all(x['owned_at_snapshot'] and not x['waiting'] for x in r['holders']) for r in locks)
  assert observer['recorded_state']['status']=='clear' and observer['recorded_state']['native_conflicts']==[] and not observer['recorded_state']['sampling_incomplete_seen']
 rows.append(row)
save('compact-live02-to05.json',{'schema':'orbit-poc-campaign09-live-transition-projection-v1',
 'scope':'Dated non-atomic read-only observations. Executable identity was observed by path/device/inode/size; no timed native-binary rehash is claimed. Frozen digest attribution and request reconstruction are reviewed separately. Running fits are not completed or accepted statistical results.',
 'snapshots':rows})
T=C/'campaign09-transition-01'
proof=read_checked(T/'prelaunch-probe.json','f57f6cbade02b16b6c703a30a6ff2b34f56a079b343d6c6551ea3bb529486bec')
prefix=read_checked(T/'prefix-before.json','db1e178493fd5f7067f6f3a4df09c3721f667560f362c2c41d106c1de4d782e6')
assert proof['status']=='passed' and proof['benchmark_attempts_launched']==0 and proof['descriptors']==[]
assert len(proof['denial_probes'])==1800 and Counter(r['errno'] for r in proof['denial_probes'])=={2:1800}
assert prefix['status']=='passed' and prefix['expected_attempts']==68 and prefix['terminal_attempts']==prefix['starting_terminal_attempts']==0 and prefix['terminal']==[]
public=proof['public_readonly_checks'];validation=public['validation'];mounts=proof['mount_checks']
save('compact-inner-proof.json',{'schema':'orbit-poc-campaign09-inner-proof-projection-v1',
 'scope':'Actual campaign inner proof, distinct from the earlier smoke03 proof. Full proof and prefix inventory remain external. No covariance or convergence claim.',
 'source_proof':pin(T/'prelaunch-probe.json'),'source_prefix_before':pin(T/'prefix-before.json'),
 'status':proof['status'],'benchmark_attempts_launched_by_probe':proof['benchmark_attempts_launched'],
 'fit_execution_authorized_by_probe':proof['fit_execution_authorized'],'release_ready':proof['release_ready'],
 'host_verified_final_artifacts':proof['host_verified_final_artifacts'],
 'specification_content_sha256':proof['specification_content_sha256'],
 'denial_probe_count':len(proof['denial_probes']),'denial_errno_counts':dict(Counter(str(r['errno']) for r in proof['denial_probes'])),
 'descriptors':proof['descriptors'],'namespaces':proof['namespaces'],
 'mount_checks':{'mount_record_count':len(mounts['mounts']),'ordinary_writable':mounts['ordinary_writable'],'retained_attempts_readonly':mounts['retained_attempts_readonly'],'virtual_mount_scope':mounts['virtual_mount_scope']},
 'public_readonly_checks':{'manifest_hash':public['manifest_hash'],'terminal_prefix':public['terminal_prefix'],'validation':{'status':validation['status'],'scope':validation['scope'],'pipeline':validation['pipeline'],'plan_hash':validation['plan_hash'],'check_names':sorted(validation['checks'])}},
 'prefix_before':{k:prefix[k] for k in ['schema','phase','status','expected_attempts','manifest_hash','terminal_attempts','starting_terminal_attempts','terminal','scientific_success_inferred','scope']}})
