from pathlib import Path
import json,hashlib,os,socket,datetime
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');O=B/'loader-alias-smoke-execution03'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(ok,message):
 if not ok:raise ValueError(message)
require(socket.gethostname()=='workstation1' and Path('/proc/sys/kernel/random/boot_id').read_text().strip()=='95156dd4-0d4c-499d-a214-8883a2d650fa','Host identity changed')
e=json.loads((O/'execution.json').read_text());require(e['status']=='passed' and e['cleanup']['verified'] and not e['cleanup']['live_owned_processes'] and e['fit_attempts']==0,'Terminal boundary differs')
require(sha(O/'execution.json')=='f52310ac46fa5e6cd6b4e991ff23c597c3e458bf87dc24b3c6a7499447213e4c','Actual execution pin changed')
rows=[]
for i in [e['admission']['driver_identity'], *e['cleanup']['identities']]:
 p=Path('/proc')/str(i['pid'])/'stat';v=None
 if p.exists():
  f=p.read_text().rsplit(')',1)[1].split();v={'start_ticks':int(f[19]),'state':f[0]}
  require(v['start_ticks']!=i['start_ticks'] or v['state']=='Z','Owned identity remains live')
 rows.append({'expected':i,'current':v})
empty={}
for p,inode in ((B/'validation-07/run/attempts',239600079),(B/'validation-07/temporary/fit-private',239600080)):
 s=p.stat();require(p.is_dir() and not p.is_symlink() and p.resolve()==p and not any(p.iterdir()) and (s.st_dev,s.st_ino)==(2048,inode),'Original writable directory changed');empty[str(p)]={'device':s.st_dev,'inode':s.st_ino,'empty':True}
locktext=Path('/proc/locks').read_text();locks=[]
for p,inode in ((Path('/mnt/seagate10tb/orbit-v31-correctness-10-florianpfaff/control/candidate09-validation.lock'),217252784),(B/'validation-07/run/.segmented.lock',239479247)):
 s=p.stat();require((s.st_dev,s.st_ino)==(2048,inode) and s.st_size==0,'Lock identity changed');wanted=f'{os.major(s.st_dev):02x}:{os.minor(s.st_dev):02x}:{s.st_ino}';holders=[line for line in locktext.splitlines() if wanted in line.split()];require(not holders,'Lock remains held');locks.append({'path':str(p),'device':s.st_dev,'inode':s.st_ino,'holders':holders})
artifacts={}
for name in ('execution','proof','bootstrap','namespace-exec'):
 p=O/(name+'.json')
 if p.exists():artifacts[name]={'path':str(p),'sha256':sha(p)}
for name in ('proof','bootstrap','namespace_exec'):
 if name in e:require(e[name]==artifacts[name.replace('_','-')],'Execution artifact attribution changed')
print(json.dumps({'schema':'orbit-poc-private-dev-smoke-terminal-independent-readback-v1','captured_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'host':socket.gethostname(),'artifacts':artifacts,'execution_status':e['status'],'returncode':e['returncode'],'identities':rows,'empty_writables':empty,'locks':locks,'native_or_fit_executed_by_audit':False},indent=2))
