#!/usr/bin/env python3
"""Extract only historical startup facts from two fixed local snapshots."""
from pathlib import Path
import hashlib,json

C=Path('/mnt/d/orbit-segmented-v4/control');HERE=Path(__file__).resolve().parent
SOURCES=[('independent',C/'campaign09-live-independent01.json','6191ee61fbd88b48dcf2feb0b82a47c557405f84c2c7094065fb12fc1c347837'),
         ('root',C/'campaign09-live01/snapshot.json','17a353afb137e1553cdab1c41e884db844f0be009d66e9c6d909d1e3d4b58521')]
rows=[]
for origin,path,digest in SOURCES:
 raw=path.read_bytes();assert hashlib.sha256(raw).hexdigest()==digest;v=json.loads(raw)
 assert v['driver_live'] and v['driver_identity_matches'] and v['pipeline']['content']['status']=='starting'
 assert v['terminal_count']==v['terminal_prefix']==0 and v['current_nonterminal_attempt_ids']==[]
 assert v['native_processes']==[] and v['prelaunch_probe']['present'] is False
 assert v['process_visibility_errors']==[] and len(v['owned_processes'])==1
 driver=v['owned_processes'][0]
 assert driver['pid']==12589 and driver['start_ticks']==135673405 and driver['affinity']==[32]
 assert driver['selected_environment']['HOME']=='/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/fit-campaign-control-09'
 locks=[]
 for lock in v['locks']:
  locks.append({'path':lock['path'],'device':lock['device'],'inode':lock['inode'],
    'holders':[{k:r[k] for k in ['owned_at_snapshot','owner_pid','owner_start_ticks','waiting']} for r in lock['kernel_locks']]})
 assert sum(bool(r['holders']) for r in locks)==2
 rows.append({'origin':origin,'source_snapshot':{'path':str(path),'sha256':digest,'bytes':len(raw)},
  'captured_at':v['captured_at'],'host':v['host'],'host_control':v['host_control'],
  'driver_identity_matches':v['driver_identity_matches'],'driver_live':v['driver_live'],
  'driver':{k:driver[k] for k in ['pid','start_ticks','parent','state','affinity','command_sha256','selected_environment','native_workload']},
  'locks':locks,'pipeline':v['pipeline'],'prelaunch_probe':v['prelaunch_probe'],
  'planned_attempt_count':len(v['attempts']),'terminal_count':v['terminal_count'],'terminal_prefix':v['terminal_prefix'],
  'current_nonterminal_attempt_ids':v['current_nonterminal_attempt_ids'],'native_process_count':len(v['native_processes']),
  'process_visibility_errors':v['process_visibility_errors']})
result={'schema':'orbit-poc-campaign09-historical-startup-projection-v1',
 'scope':'Two non-atomic startup-only snapshots. Their full attempt/process inventories remain external. Neither snapshot establishes the in-campaign proof, native fit handoff, covariance or convergence.',
 'snapshots':rows}
data=(json.dumps(result,indent=2,sort_keys=True)+'\n').encode();p=HERE/'compact-startup.json'
if p.exists():assert p.read_bytes()==data
else:
 with p.open('xb') as f:f.write(data)
