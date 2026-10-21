from pathlib import Path
import json,hashlib,datetime,os,shutil
C=Path('/mnt/d/orbit-segmented-v4/control');R=Path('/mnt/d/orbit-numerics-v3.1/benchmark-d-volume/recovery-20261016-03');B=R.parent/'benchmark-01'
def pin(p):
 b=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
def proc(p):
 q=Path('/proc')/str(p)
 try:
  st=(q/'stat').read_text();f=st[st.rindex(')')+2:].split();argv=[x.decode(errors='replace')for x in(q/'cmdline').read_bytes().split(b'\0')if x]
  return {'pid':p,'parent':int(f[1]),'start_ticks':int(f[19]),'state':f[0],'affinity':sorted(os.sched_getaffinity(p)),'argv':argv}
 except (FileNotFoundError,ProcessLookupError):return None
L=json.loads((R/'launch.json').read_bytes());S=json.loads((R/'supervision.json').read_bytes());boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();root=proc(L['process']['pid'])
assert L['launch_committed']and L['boot_id']==boot and root and root['start_ticks']==L['process']['start_ticks']and root['argv']==L['argv']and root['state']not in ['Z','X']
rows={}
for p in Path('/proc').iterdir():
 if p.name.isdigit():
  v=proc(int(p.name))
  if v:rows[v['pid']]=v
owned={root['pid']}
while True:
 nxt={p for p,v in rows.items()if v['parent']in owned}
 if nxt<=owned:break
 owned|=nxt
live=[rows[p]for p in sorted(owned)if p in rows];verifiers=[x for x in live if any(y.endswith('/verify_numerics_runtime.py')for y in x['argv'])]
assert verifiers and all(x['affinity']==[30]for x in verifiers)
mem={x.split(':')[0]:int(x.split(':')[1].split()[0])*1024 for x in Path('/proc/meminfo').read_text().splitlines()if x.startswith('MemAvailable:')};free=shutil.disk_usage(B).free
assert mem['MemAvailable']>=17179869184 and free>=68719476736
foreign_native=[v for p,v in rows.items()if p not in owned and v['argv'] and Path(v['argv'][0]).name.startswith('groops')];assert not foreign_native
m=json.loads((B/'manifest.json').read_bytes());nextdir=B/'attempts'/m['attempts'][18]['attempt_id'];terminal=sum((B/'attempts'/a['attempt_id']/'result.json').is_file()for a in m['attempts']);assert terminal==18
value={'schema':'orbit-poc-original150-resume04-live-observation-v1','observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'launch':pin(R/'launch.json'),'supervision_snapshot':S,'boot_id':boot,'owned_live_chain':live,'current_resources':{'memory':mem,'free_output_bytes':free,'foreign_native_conflicts':foreign_native},'terminal_attempts':terminal,'planned_attempts':150,'startup_receipt_present':(R/'startup-resume-04.json').is_file(),'campaign_adapter_receipt_present':(R/'campaign-adapter04.json').is_file(),'next_attempt':m['attempts'][18],'next_request_present':(nextdir/'request.json').exists(),'next_result_present':(nextdir/'result.json').exists(),'phase':'unchanged_frozen_runtime_verifier_running','scope':'Actual durable supervisor and exact current host/argv/CPU30 verifier observed. Complete runtime/input verification is pending; attempt19 has not started and campaign numerical execution is not claimed.'}
out=C/'original150-resume04-live01.json'
with out.open('x')as f:json.dump(value,f,indent=2);f.write('\n')
print(json.dumps({'receipt':pin(out),'launch':value['launch'],'owned':[{k:x[k]for k in ['pid','parent','start_ticks','state','affinity']}for x in live],'phase':value['phase']}))
