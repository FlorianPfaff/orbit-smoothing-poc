from pathlib import Path
import json,hashlib,subprocess,base64,datetime
C=Path('/mnt/d/orbit-segmented-v4/control');capture=C/'native-complete-build02-terminal-capture01.json';raw=capture.read_bytes();assert hashlib.sha256(raw).hexdigest()=='0faae52c6b349fef10f5d63aef3bbea3d393962e2a1f66e4aba36debea4b6243';d=json.loads(raw);records=[x for x in d['external']if not x['path'].endswith('/candidate-dependency-inventory.stdout')];assert len(records)==5 and sum(x['bytes']for x in records)==2051997
program="""from pathlib import Path
import json,hashlib,base64,datetime
records="""+repr(records)+"""
rows=[]
for r in records:
 p=Path(r['path']);assert p.is_file()and not p.is_symlink();b=p.read_bytes();assert len(b)==r['bytes']and hashlib.sha256(b).hexdigest()==r['sha256'];rows.append(dict(r,base64=base64.b64encode(b).decode()))
print(json.dumps({'schema':'orbit-poc-five-compile-records-transfer-v1','observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'files':rows,'scope':'Read-only exact five existing frozen compact compilation records; no generation, audit or object/source traversal.'},indent=2))
"""
out=C/'native-complete-build02-compile-records01.json';err=C/'native-complete-build02-compile-records01.stderr';assert not out.exists()and not err.exists()
with out.open('xb')as o,err.open('xb')as e:p=subprocess.run(['ssh','gpuserver4090','python3','-'],input=program.encode(),stdout=o,stderr=e)
assert p.returncode==0,p.returncode;received=json.loads(out.read_bytes());assert [{k:r[k]for k in ['path','sha256','bytes']}for r in received['files']]==records
root=C/'native-complete-build02-compile-records01';root.mkdir()
for r in received['files']:
 b=base64.b64decode(r['base64'],validate=True);assert len(b)==r['bytes']and hashlib.sha256(b).hexdigest()==r['sha256'];rel=Path(r['path']).relative_to(d['root']);assert '..'not in rel.parts;p=root/rel;p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('xb')as f:f.write(b)
print(json.dumps({'capture':{'path':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'bytes':out.stat().st_size},'files':5,'original_bytes':sum(x['bytes']for x in records),'extraction':str(root)}))
