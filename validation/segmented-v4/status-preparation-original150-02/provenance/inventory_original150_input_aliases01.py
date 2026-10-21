#!/usr/bin/env python3
from pathlib import Path
import hashlib,json,os,datetime
C=Path('/mnt/d/orbit-segmented-v4/control');D=Path('/mnt/d/orbit-numerics-v3.1/benchmark-d-volume/benchmark-01/attempts/retained-pulse-weak-300001--qr_lm_staged_jacobian');M=Path('/mnt/d/orbit-numerics-v3.1-mirror/remote-root')
def pin(p):b=Path(p).read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
j=json.loads((D/'request.json').read_text());n=next(x for x in j['estimation_inputs'] if x['path'].endswith('/native_preparation.json'));p=M/n['path'].lstrip('/');assert pin(p)['sha256']==n['sha256'];v=json.loads(p.read_text()); date=v['date'];base='point-001-initial/native/data/';expected={}
for kind in ['attitude','clock','orbit','signalBias']:
 members=[x for x in v['native_artifacts'] if '/data/'+date+'/'+kind+'/' in x['path']];parents={str(Path(x['path']).parent) for x in members};assert len(parents)==1 and members
 expected[base+date+'/'+kind]={'target':parents.pop(),'authority':'native_artifacts directory parent','original_artifact_count':len(members)}
for key in ['receiver','receiver_orbit','receiver_attitude','attitude']:
 target=v['native_paths'][key];assert target in {x['path'] for x in v['native_artifacts']};expected[base+date+'/gracefo/'+Path(target).name]={'target':target,'authority':'native_paths.'+key+' and native_artifacts','original_artifact_count':1}
accuracy=next(x for x in j['estimation_inputs'] if x['path'].endswith('/data/synthetic_accuracy.xml'));expected[base+'synthetic_accuracy.xml']={'target':accuracy['path'],'authority':'request.estimation_inputs','original_artifact_count':1}
actual={str(x.relative_to(D)):os.readlink(x) for x in D.rglob('*') if x.is_symlink()};assert len(expected)==len(actual)==9 and actual=={k:x['target'] for k,x in expected.items()}
rows=[]
for rel,item in sorted(expected.items()):s=(D/rel).lstat();rows.append({'relative':rel,**item,'lstat_size':s.st_size,'lstat_mtime_ns':s.st_mtime_ns})
o={'schema':'orbit-poc-original150-existing-input-alias-inventory-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'attempt_directory':str(D),'request':pin(D/'request.json'),'native_preparation':{'canonical_path':n['path'],'backing':pin(p),'expected_sha256':n['sha256']},'entries':rows,'alias_count':9,'scope':'Exact pre-existing native input links, derived from checksum-bound original request/native preparation metadata. Readlink and lstat only; no link targets traversed or input payloads rehashed. Appended receipt/result/index and their ancestors remain symlink-free.','helper':pin(__file__),'prior_failure':pin(C/'original150-append-input-alias-independent-failure01.json')}
out=C/'original150-input-aliases01.json'
with out.open('x') as f:json.dump(o,f,sort_keys=True,indent=2);f.write('\n')
print(pin(out))
