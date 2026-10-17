from pathlib import Path
import hashlib,json,tarfile
r=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/validation-04')
folders=('terminal-capture-01','terminal-linearization-arrays-01')
for name in folders: assert (r/name/'manifest.json').is_file()
p=r/'terminal-transfer-01.tar'
with tarfile.open(p, 'x') as tar:
    for name in folders: tar.add(r/name,arcname=name)
print(json.dumps({'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}))
