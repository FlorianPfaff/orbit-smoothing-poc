from pathlib import Path
import json,hashlib,importlib.util,datetime
R=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/shifted-diagnostic-01')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def artifact(p):b=Path(p).read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b),'text':b.decode()}
assert sha(R/'control/plan.json')=='7e8a00946a84a5fceb29e75dc802b13710d70e31ce7faddf24966358272ee031'
p=json.loads((R/'control/plan.json').read_text());assert sha(p['runner']['path'])==p['runner']['sha256'];spec=importlib.util.spec_from_file_location('runner',p['runner']['path']);runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner);p=runner.load_plan(R/'control/plan.json','7e8a00946a84a5fceb29e75dc802b13710d70e31ce7faddf24966358272ee031')
spec=importlib.util.spec_from_file_location('d',p['driver']['path']);d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d);e=d.load_execution(p['execution']['path']);f=json.loads(Path(p['source_freeze']['path']).read_text());assert d.source_receipt(Path(e['paths']['source']))==f['source']
for pin in e['runtime_artifacts'].values():assert sha(d.resolved_host_path(pin['path'],e))==pin['sha256']
admission=d.admission(e,[])
absent={k:not Path(e['paths'][k]).exists() and not Path(e['paths'][k]).is_symlink() for k in ('native_source','build','binaries','run','temporary')};assert all(absent.values())
files=[R/'staging/runtime-smoke-01'/n for n in ['process.json','execution.json','run/runtime-log_drag_ou-before.json']]
values={str(p):artifact(p) for p in files};journal=json.loads(values[str(files[0])]['text']);assert journal['status']=='passed' and journal['returncode']==0 and journal['final_cleanup']['verified'] and not journal['final_cleanup']['errors'];assert all(c['verified'] and not c['live_owned_processes'] for c in journal['final_cleanup']['commands'])
live=[]
for c in journal['final_cleanup']['commands']:
 for x in c['identities']:
  try: now=d.proc(x['pid'])
  except FileNotFoundError: now=None
  if now and now['start_ticks']==x['start_ticks'] and now['state']!='Z':live.append(now)
assert not live
print(json.dumps({'observed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'files':values,'admission':admission,'source_sha256':f['source']['sha256'],'source_file_count':len(f['source']['files']),'runtime_pin_count':len(e['runtime_artifacts']),'production_outputs_absent':absent,'live_exact_smoke_identities':live},sort_keys=True))
