from pathlib import Path
import json,hashlib,subprocess
C=Path('/mnt/d/orbit-segmented-v4/control');source=C/'preparation04-numerical-failure-readback01.json';d=json.loads(source.read_text())
rows=[]
for f in d['files']:
 if 'text' in f and hashlib.sha256(f['text'].encode()).hexdigest()!=f['sha256']:
  rows.append({k:f[k]for k in ('path','sha256','bytes')})
assert len(rows)==4 and all(Path(x['path']).name in {'initialize.log','propagate.log'}for x in rows)
code='''from pathlib import Path\nimport json,hashlib,base64,datetime\nrows=ROWS\nout=[]\nfor row in rows:\n p=Path(row['path']);assert p.is_file() and not p.is_symlink();b=p.read_bytes();assert len(b)==row['bytes'] and hashlib.sha256(b).hexdigest()==row['sha256'];out.append(dict(row,base64=base64.b64encode(b).decode()))\nprint(json.dumps({'schema':'orbit-poc-preparation04-native-log-raw-readback-v1','observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'records':out,'scope':'Read-only transfer of exactly four predeclared small native log files; no numerical execution or additional data scan.'},indent=2))\n'''.replace('ROWS',repr(rows))
res=subprocess.run(['/mnt/c/Windows/System32/OpenSSH/ssh.exe','-o','BatchMode=yes','gpuserver4090','python3','-'],input=code.encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
for name,b in [('preparation04-numerical-failure-raw-logs01.json',res.stdout),('preparation04-numerical-failure-raw-logs01.stderr.log',res.stderr)]:
 with (C/name).open('xb')as f:f.write(b)
assert res.returncode==0,res.stderr.decode()
o=json.loads(res.stdout);assert len(o['records'])==4
import base64
for old,new in zip(rows,o['records']):
 assert all(new[k]==v for k,v in old.items());b=base64.b64decode(new['base64'],validate=True);assert len(b)==old['bytes']and hashlib.sha256(b).hexdigest()==old['sha256']
print(json.dumps({'path':str(C/'preparation04-numerical-failure-raw-logs01.json'),'sha256':hashlib.sha256(res.stdout).hexdigest(),'bytes':len(res.stdout),'original_records':len(rows)},indent=2))
