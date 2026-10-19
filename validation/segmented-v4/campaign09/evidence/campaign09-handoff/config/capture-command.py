from pathlib import Path
import base64,hashlib,json
p=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/validation-07/control/segmented-v4.json');s=p.stat();b=p.read_bytes();t=p.stat();h=hashlib.sha256(b).hexdigest()
if h!='33cf305ada15863e2ee04e57390707344ed045a9fc712efc3f5e6e9247656378' or (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)!=(t.st_dev,t.st_ino,t.st_size,t.st_mtime_ns):raise ValueError('Config identity changed')
print(json.dumps({'pin':{'path':str(p),'sha256':h,'bytes':len(b),'device':s.st_dev,'inode':s.st_ino},'data':base64.b64encode(b).decode()}))
