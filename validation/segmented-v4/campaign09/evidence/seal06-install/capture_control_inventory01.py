from pathlib import Path
import hashlib,json,subprocess,time
C=Path('/mnt/d/orbit-segmented-v4/control/direct-fit-helper-install12')
code=r'''
from pathlib import Path
import datetime,hashlib,json,os,stat
root=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/fit-seal-control-07');s=root.stat()
if root.is_symlink() or root.resolve()!=root or (s.st_dev,s.st_ino)!=(2048,239600078):raise ValueError('Exact control directory required')
rows=[]
def walk(p):
 s=p.lstat();r={'path':str(p),'device':s.st_dev,'inode':s.st_ino,'mode':stat.S_IMODE(s.st_mode)}
 if stat.S_ISLNK(s.st_mode):r.update(kind='symlink',target=os.readlink(p))
 elif stat.S_ISDIR(s.st_mode):
  children=sorted(p.iterdir());r.update(kind='directory',children=[x.name for x in children]);rows.append(r)
  for x in children:walk(x)
  return
 elif stat.S_ISREG(s.st_mode):
  data=p.read_bytes();t=p.stat()
  if (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)!=(t.st_dev,t.st_ino,t.st_size,t.st_mtime_ns):raise ValueError('Changed capture file')
  r.update(kind='file',bytes=s.st_size,sha256=hashlib.sha256(data).hexdigest())
 else:raise ValueError('Unexpected control entry')
 rows.append(r)
walk(root)
print(json.dumps({'schema':'orbit-poc-preserved-metadata-tree-inventory-v1','captured_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'root':str(root),'device':s.st_dev,'inode':s.st_ino,'entries':rows,'fit_attempts':len(list((root.parent/'validation-07/run/attempts').iterdir())),'temporary_entries':len(list((root.parent/'validation-07/temporary/fit-private').iterdir()))}))
'''
start=time.time();r=subprocess.run(['/mnt/c/Windows/System32/OpenSSH/ssh.exe','-o','BatchMode=yes','gpuserver4090','env PYTHONDONTWRITEBYTECODE=1 /usr/bin/taskset -c 32 /usr/bin/python3 -B -'],input=code,text=True,capture_output=True)
(C/'inventory-capture01.stderr.log').write_text(r.stderr);(C/'inventory-capture01-process.json').write_text(json.dumps({'returncode':r.returncode,'elapsed_seconds':time.time()-start,'script_sha256':hashlib.sha256(code.encode()).hexdigest()},indent=2)+'\n')
if r.returncode:raise RuntimeError(r.stderr)
v=json.loads(r.stdout);p=C/'preserved-control-inventory01.json';p.write_text(json.dumps(v,indent=2,sort_keys=True)+'\n');print(json.dumps({'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'entries':len(v['entries']),'regular_bytes':sum(x.get('bytes',0) for x in v['entries']),'fit_attempts':v['fit_attempts'],'temporary_entries':v['temporary_entries']}))
