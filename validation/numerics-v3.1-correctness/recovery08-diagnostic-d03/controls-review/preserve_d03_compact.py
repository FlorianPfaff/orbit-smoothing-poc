"""Read-only bounded snapshot of closed D03; independent analyses are separate."""
from pathlib import Path
import base64,hashlib,json,subprocess
BASE=Path('@LOCAL_DATA_ROOT@/orbit-numerics-v3.1/correctness');OUT=BASE/'remote-diagnostic-row-trace-03';CONTROL=BASE/'control'
REMOTE=r'''
from pathlib import Path
import json,hashlib,base64,datetime,socket
root=Path('@REMOTE_DATA_ROOT@/orbit-v31-diagnostic-row-trace-03-PRIVATE_USER');jp=root/'diagnostic/pipeline.json';initial=jp.read_bytes();journal=json.loads(initial)
assert journal['status']=='completed' and journal['finished_at'] and journal['final_cleanup']['verified'] and not journal['scientific_correctness_resolved']
assert [s['name'] for s in journal['steps']]==['clone','checkout','build','trace-off','trace-on','equivalence']
assert all(s['cleanup_verified'] for s in journal['steps'])
plan_path=root/'control/plan.json';plan_raw=plan_path.read_bytes();plan=json.loads(plan_raw)
assert hashlib.sha256(plan_raw).hexdigest()=='0846eeaddca404116ecc8ee1d8de404aa1e46e00df5517e207d06e55d53b21bd'
selected={}
for part in ('control','staging','diagnostic','binaries'):
 for p in (root/part).rglob('*'):
  rel=p.relative_to(root)
  if any(x in rel.parts for x in ('__pycache__','trace','independent-analysis-01')):continue
  if p.is_file() and p.suffix in ('.py','.h','.md','.json','.xml','.log'):
   assert not p.is_symlink();selected[str(rel)]=p
for key,label in [('source_freeze','source-freeze.json'),('prior_pipeline','original08-pipeline.json'),('prior_postprocess','original08-postprocess.json'),('driver','original-candidate07-driver.py')]:
 pin=plan[key];p=Path(pin['path']);assert hashlib.sha256(p.read_bytes()).hexdigest()==pin['sha256'];selected['referenced/'+label]=p
profile=plan['inputs']['profile'];p=Path(profile['path']);assert hashlib.sha256(p.read_bytes()).hexdigest()==profile['sha256'];selected['referenced/original08-density-point006-profile.xml']=p
rows=[];total=0
for rel,p in sorted(selected.items()):
 assert p.stat().st_size<=16*1024*1024
 raw=p.read_bytes();total+=len(raw);assert total<=64*1024*1024
 rows.append({'relative':rel,'source':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'base64':base64.b64encode(raw).decode()})
assert jp.read_bytes()==initial and plan_path.read_bytes()==plan_raw
for r in rows:assert hashlib.sha256(Path(r['source']).read_bytes()).hexdigest()==r['sha256']
traces=[{'path':str(p),'bytes':p.stat().st_size,'storage':'external_not_transferred','content_hash':'pending_independent_analysis_receipt'} for p in sorted((root/'diagnostic/trace').glob('nuisance-trace-*.tsv'))]
print(json.dumps({'schema':'orbit-poc-d03-compact-preservation-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'hostname':socket.gethostname(),'remote_root':str(root),'pipeline_sha256':hashlib.sha256(initial).hexdigest(),'plan_sha256':hashlib.sha256(plan_raw).hexdigest(),'files':rows,'bytes':total,'native_reference':journal['native'],'trace_inventory':traces,'trace_contents_scanned':False,'scientific_validation_complete':False,'scope':'Exact closed diagnostic files and referenced source/input/control identities only; independent analysis artifacts are preserved separately when terminal. No source tree, native binary or raw rows/traces copied.'}))
'''
if __name__=='__main__':
 assert not OUT.exists();envelope=CONTROL/'d03-compact-transfer-envelope.json'
 with envelope.open('xb') as f:
  proc=subprocess.run(['@WINDOWS_MOUNT@/Windows/System32/OpenSSH/ssh.exe','-o','ConnectTimeout=10','gpuserver4090','/usr/bin/python3','-'],input=REMOTE.encode(),stdout=f,stderr=subprocess.PIPE)
 if proc.returncode:raise RuntimeError(proc.stderr.decode())
 value=json.loads(envelope.read_bytes());OUT.mkdir();records=[]
 for row in value['files']:
  rel=Path(row['relative']);assert not rel.is_absolute() and '..' not in rel.parts
  data=base64.b64decode(row['base64'],validate=True);assert len(data)==row['bytes'] and hashlib.sha256(data).hexdigest()==row['sha256'];p=OUT/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);records.append({k:v for k,v in row.items() if k!='base64'})
 value['files']=records;value['local_root']=str(OUT);value['local_match_verified']=True;p=CONTROL/'d03-compact-transfer-manifest.json';p.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n');print(json.dumps({'files':len(records),'bytes':value['bytes'],'manifest_sha256':hashlib.sha256(p.read_bytes()).hexdigest()}))
