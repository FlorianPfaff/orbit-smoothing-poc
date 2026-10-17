from pathlib import Path
import json,hashlib
r=Path("/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/shifted-diagnostic-01")
files={}
for name in ["execution.json","plan.json","pins.json","staging.json"]:
 p=r/"control"/name;b=p.read_bytes();files[str(p)]={"sha256":hashlib.sha256(b).hexdigest(),"bytes":len(b),"text":b.decode()}
print(json.dumps(files))
