from pathlib import Path
import json,importlib.util
I=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/native-complete-inputs-01');sp=importlib.util.spec_from_file_location('u',I/'build_native_source_delta01.py');u=importlib.util.module_from_spec(sp);sp.loader.exec_module(u)
rows=json.loads((I/'link-inventory.json').read_text())['inputs'];different=[]
for row in rows:
 now=u.file_identity(row['path'])
 if now!=row:different.append({'declared':row,'actual':now,'fields':[k for k in row if row[k]!=now[k]]})
print(json.dumps({'count':len(rows),'different':different},indent=2))
