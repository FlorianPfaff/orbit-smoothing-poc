from pathlib import Path
import tarfile,json,hashlib
b=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');a=b/'staging/tangent-capture-build03-packet.tar.gz';d=b/'tangent-capture-03'
assert hashlib.sha256(a.read_bytes()).hexdigest()=='8351071d906e251e293aa5196926aa01a1a2165c848057201cb4eee3d77634ba'
assert not d.exists();d.mkdir()
with tarfile.open(a) as t:
 for x in t.getmembers():
  p=Path(x.name);assert x.isfile() and not p.is_absolute() and '..' not in p.parts
 t.extractall(d)
f=json.loads((d/'packet-files.json').read_text())
assert {str(x.relative_to(d)) for x in d.rglob('*') if x.is_file()}==set(f)|{'packet-files.json'}
for name,h in f.items():assert hashlib.sha256((d/name).read_bytes()).hexdigest()==h
print(json.dumps({'installed':str(d),'files':len(f),'archive_sha256':hashlib.sha256(a.read_bytes()).hexdigest()}))
