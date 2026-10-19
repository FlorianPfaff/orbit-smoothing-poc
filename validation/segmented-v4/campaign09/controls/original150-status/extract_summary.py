#!/usr/bin/env python3
"""Extract a compact dated status from a fixed local snapshot; no host calls."""
from collections import Counter
from pathlib import Path
import hashlib, json

HERE=Path(__file__).resolve().parent
SOURCE=Path('/mnt/d/orbit-segmented-v4/control/original150-current-status-20261019T005011Z.json')
EXPECTED='b9dca1633c81c86fa66de9fa87868688fc6a6db10b3941f0ef3db2b92d9138de'
raw=SOURCE.read_bytes()
assert hashlib.sha256(raw).hexdigest()==EXPECTED and len(raw)==76440
v=json.loads(raw)
assert v['terminal_attempts']==sum(v['status_counts'].values())==len(v['terminals'])==57
states=dict(sorted(Counter(r['state'] for r in v['live_control_and_descendants']).items()))
assert states=={'D':1,'S':4,'Z':22}
active=[]
for row in v['started_without_terminal']:
 active.append({k:row[k] for k in ['order_one_based','attempt_id','profile','result_present']})
 active[-1]['matching_processes']=[{k:r[k] for k in ['pid','parent','state','start_ticks','processor','cpu_allowed_list']} for r in row['matching_processes']]
result={'schema':'orbit-poc-original150-dated-compact-status-v1',
 'source_snapshot':{'path':str(SOURCE),'sha256':EXPECTED,'bytes':len(raw)},
 'observed_at':v['observed_at'],'planned_attempts':v['planned_attempts'],
 'terminal_attempts':v['terminal_attempts'],'archived_status_counts':v['status_counts'],
 'started_without_terminal':active,'observed_control_and_descendant_entries':len(v['live_control_and_descendants']),
 'observed_control_and_descendant_states':states,
 'process_count_scope':'The source field live_control_and_descendants includes 22 zombie entries; 27 is the observed entry count, not the live-process count.',
 'scientific_status_scope':'Complete retains the original archived classification. This is not a corrected-v3.1 or v4 strict convergence audit, nor an overall campaign completion claim.',
 'source_scope':v['scope']}
data=(json.dumps(result,indent=2,sort_keys=True)+'\n').encode()
target=HERE/'compact-status.json'
if target.exists():assert target.read_bytes()==data
else:
 with target.open('xb') as f:f.write(data)
