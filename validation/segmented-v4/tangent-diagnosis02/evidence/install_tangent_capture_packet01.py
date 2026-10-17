from pathlib import Path
import hashlib,tarfile,json
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');D=B/'tangent-capture-01';a=B/'staging/tangent-capture-build01-packet.tar.gz'
assert hashlib.sha256(a.read_bytes()).hexdigest()=='3e5a4500c99c4f823a04f56eb64b46ad186784d78cf83188476d2e2b210cb847';assert not D.exists();D.mkdir()
with tarfile.open(a)as t:
 for x in t.getmembers():assert not Path(x.name).is_absolute()and'..'not in Path(x.name).parts and(x.isfile()or x.isdir())
 t.extractall(D,filter='data')
rows=json.loads((D/'packet-files.json').read_text())
for r in rows:
 p=D/r['relative_path'];assert p.stat().st_size==r['bytes']and hashlib.sha256(p.read_bytes()).hexdigest()==r['sha256']
print(json.dumps({'files':len(rows),'native_runs':0,'root':str(D)}))
