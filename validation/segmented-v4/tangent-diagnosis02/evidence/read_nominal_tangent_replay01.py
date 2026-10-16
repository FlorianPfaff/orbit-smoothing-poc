from pathlib import Path
import json,hashlib,datetime
D=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/tangent-replay-01');r={'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'files':{}}
for rel in ('control/pipeline.json','control/native-replay.log','run/replay/result.json','run/replay/single-evaluation/propagate.execution.json','run/replay/single-evaluation/propagate.log','run/replay/single-evaluation/propagate.xml'):
 p=D/rel
 if p.is_file():
  raw=p.read_bytes();r['files'][rel]={'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'value':json.loads(raw)if p.suffix=='.json'else raw.decode()}
print(json.dumps(r))
