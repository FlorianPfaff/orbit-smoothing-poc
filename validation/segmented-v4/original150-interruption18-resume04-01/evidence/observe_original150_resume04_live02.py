from pathlib import Path
import json,hashlib,datetime,os
C=Path('/mnt/d/orbit-segmented-v4/control');R=Path('/mnt/d/orbit-numerics-v3.1/benchmark-d-volume/recovery-20261016-03');B=R.parent/'benchmark-01'
def pin(p):
 b=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
def proc(pid):
 p=Path('/proc')/str(pid)
 try:
  s=(p/'stat').read_text();f=s[s.rindex(')')+2:].split();return {'pid':pid,'parent':int(f[1]),'start_ticks':int(f[19]),'state':f[0],'affinity':sorted(os.sched_getaffinity(pid)),'argv':[x.decode(errors='replace')for x in(p/'cmdline').read_bytes().split(b'\0')if x]}
 except(FileNotFoundError,ProcessLookupError):return None
l=json.loads((R/'launch.json').read_bytes());boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();root=proc(l['process']['pid']);assert root and boot==l['boot_id']and root['start_ticks']==l['process']['start_ticks']and root['argv']==l['argv']and root['state']not in ['Z','X']
allp={}
for p in Path('/proc').iterdir():
 if p.name.isdigit():
  x=proc(int(p.name))
  if x:allp[x['pid']]=x
owned={root['pid']}
while True:
 nexts={p for p,v in allp.items()if v['parent']in owned}
 if nexts<=owned:break
 owned|=nexts
chain=[allp[p]for p in sorted(owned)if p in allp];recoveries=[x for x in chain if any(a.endswith('/original150_retention_recovery02.py')for a in x['argv'])];assert recoveries and all(x['affinity']==[30]for x in recoveries)
s=json.loads((R/'startup-resume-04.json').read_bytes());assert s['status']=='verified'and len(s['trees'])==9 and all(x['read_only']for x in s['trees']);assert s['configuration']['sha256']=='6ba79d36b15cb574169eae4364ec11a87fe82a2deef9d707e6d0e4a369f364e7'
m=json.loads((B/'manifest.json').read_bytes());nextdir=B/'attempts'/m['attempts'][18]['attempt_id'];statuses={}
for a in m['attempts']:
 p=B/'attempts'/a['attempt_id']/'result.json'
 if p.exists():
  status=json.loads(p.read_bytes())['status'];statuses[status]=statuses.get(status,0)+1
assert sum(statuses.values())==18
out={'schema':'orbit-poc-original150-resume04-live-observation-v2','observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'boot_id':boot,'launch':pin(R/'launch.json'),'startup_receipt':pin(R/'startup-resume-04.json'),'startup_receipt_body':s,'owned_live_chain':chain,'terminal_attempts':18,'planned_attempts':150,'terminal_statuses':statuses,'campaign_adapter_receipt_present':(R/'campaign-adapter04.json').exists(),'next_attempt':m['attempts'][18],'next_request_present':(nextdir/'request.json').exists(),'next_result_present':(nextdir/'result.json').exists(),'phase':'frozen_runtime_verified_campaign_input_verification_running','scope':'Exact nine-tree runtime startup passed. Current owned original recovery helper is live on CPU30. Campaign adapter and attempt19 are not yet present; numerical fit execution is not claimed.'}
assert not out['campaign_adapter_receipt_present']and not out['next_request_present']and not out['next_result_present']
p=C/'original150-resume04-live02.json'
with p.open('x')as f:json.dump(out,f,indent=2);f.write('\n')
print(json.dumps(pin(p)))
