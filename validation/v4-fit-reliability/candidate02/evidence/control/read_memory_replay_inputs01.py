from pathlib import Path
import hashlib,json
r=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/validation-07/run')
b=(r/'manifest.json').read_bytes();assert hashlib.sha256(b).hexdigest()=='4877f929be8a9eda5d58ff6b4eb0e0fc8b84ea16934a6fbe63fa5a18418fa5c6'
p=r/'attempts/leo500-quiet-normal-groops_log_drag_ou-72h--dense_corrected/point-001-initial'
files=[p/'closure-01/propagate.xml',p/'fixed_force.txt',p/'physical_initial.txt']
print(json.dumps([{'path':str(f),'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'text':f.read_text()} for f in files]))
