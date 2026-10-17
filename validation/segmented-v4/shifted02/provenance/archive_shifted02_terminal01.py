from pathlib import Path
import hashlib,json,tarfile
r=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/shifted-diagnostic-02')
m=r/'terminal-capture-01/manifest.json'
assert hashlib.sha256(m.read_bytes()).hexdigest()=='2fcbbeb40d456fb852eda01aac0098ef748938de16eae8bfe12aaf90d4c14f79'
p=r/'terminal-transfer-01.tar.gz'
with p.open('xb') as stream:
    with tarfile.open(fileobj=stream,mode='w:gz') as tar:
        tar.add(r/'terminal-capture-01',arcname='terminal-capture-01')
print(json.dumps({'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}))
