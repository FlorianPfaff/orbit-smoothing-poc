#!/usr/bin/env python3
from pathlib import Path
import base64,hashlib,json,subprocess,time
C=Path('/mnt/d/orbit-segmented-v4/control/direct-fit-helper-install11')
plan_data=(C/'install-plan.json').read_bytes()
archive_data=(C/'helpers-and-request.tar').read_bytes()
def sha(b):return hashlib.sha256(b).hexdigest()
if sha(plan_data)!='c537918f909012c86b54e92e7f409ed1a1b35270f8c156fed935603505d635e6':raise ValueError('Plan changed')
if sha(archive_data)!='bc0a2171b60a626c4eb38ab44099edfa21b8d595fbd2613180fc5f43b3ec30f3':raise ValueError('Archive changed')
code=r'''
from pathlib import Path
import base64,fcntl,hashlib,importlib.util,io,json,os,tarfile,traceback
def need(ok,msg):
 if not ok:raise ValueError(msg)
def sha(b):return hashlib.sha256(b).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p.read_bytes())}
def check(x):
 p=Path(x['path']);need(p.is_file() and sha(p.read_bytes())==x['sha256'],'Pinned file changed: '+str(p));return p
def write(p,data):
 with p.open('xb') as f:f.write(data)
 os.chmod(p,0o644)
def dump(v):return (json.dumps(v,indent=2,sort_keys=True)+'\n').encode()
PLAN_DATA=base64.b64decode(PLAN_B64);ARCHIVE_DATA=base64.b64decode(ARCHIVE_B64)
need(sha(PLAN_DATA)=='c537918f909012c86b54e92e7f409ed1a1b35270f8c156fed935603505d635e6','Plan bytes')
need(sha(ARCHIVE_DATA)=='bc0a2171b60a626c4eb38ab44099edfa21b8d595fbd2613180fc5f43b3ec30f3','Archive bytes')
p=json.loads(PLAN_DATA)
need(p['schema']=='orbit-poc-direct-fit-helper-install-plan-v1','Plan schema')
for key in ('driver','execution','stage_result','preparation_controller','prior_install_receipt','preserved_failed_execution','preserved_failed_execution04'):check(p[key])
spec=importlib.util.spec_from_file_location('owned',check(p['driver']));d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
e=d.load_execution(check(p['execution']))
root=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/direct-fit-helper-inputs-11')
def check_partial():
 for partial in p['preserved_partial_outputs']:
  q=Path(partial['path']);st=q.stat()
  need(q.is_dir() and not q.is_symlink() and (st.st_dev,st.st_ino)==(partial['device'],partial['inode']),'Partial output directory changed')
  for r in partial['directories']:
   d=Path(r['path']);ds=d.stat();need(d.is_dir() and not d.is_symlink() and (ds.st_dev,ds.st_ino)==(r['device'],r['inode']),'Partial directory identity changed')
   need(sorted(x.name for x in d.iterdir())==r['children'],'Partial output membership changed')
  for r in partial['files']:check(r)
check_partial()
control=Path(p['control']['path']);stage=json.loads(check(p['stage_result']).read_text())
support=stage['system_support'];check(support)
need(stage['status']=='staged_metadata' and stage['fit_attempts']==0 and stage['native_executions']==0,'Stage not clean')
need(stage['control']==p['control'],'Control identity mismatch')
need(json.loads(check(p['preparation_controller']).read_text())['status']=='prepared','Prep not complete')
need(str(control.resolve())==str(control),'Control alias')
need(control.stat().st_dev==p['control']['device'] and control.stat().st_ino==p['control']['inode'],'Control replaced')
need(not root.exists() and not root.is_symlink(),'Fresh install input root required')
need(set(q.name for q in control.iterdir())=={'result.json','system-support.json',*[Path(r['path']).name for r in p['preserved_partial_outputs']],*[Path(r['path']).name for r in p['preserved_control_artifacts']]},'Unexpected control contents')
payload={}
with tarfile.open(fileobj=io.BytesIO(ARCHIVE_DATA),mode='r:') as tar:
 members=tar.getmembers();rows={r['name']:r for r in p['files']}
 need(len(members)==len(rows)==5 and len({m.name for m in members})==5,'Archive cardinality')
 need(set(rows)=={m.name for m in members},'Archive membership')
 for m in members:
  r=rows[m.name]
  need(m.isfile() and '/' not in m.name and m.name not in ('.','..') and m.size==r['bytes'] and m.mode==r['mode'],'Unsafe archive entry')
  data=tar.extractfile(m).read();need(sha(data)==r['sha256'],'Archive member hash')
  target=control/m.name;need(str(target)==r['target'] and not target.exists() and not target.is_symlink(),'Nonfresh target')
  payload[m.name]=data
with Path(p['shared_lock']).open('a') as lock,check(stage['statistical_lock']).open('rb') as statlock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(statlock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 admission=d.admission(e)
 need(control.stat().st_dev==p['control']['device'] and control.stat().st_ino==p['control']['inode'],'Control changed after admission')
 for key in ('driver','execution','stage_result','preparation_controller','prior_install_receipt','preserved_failed_execution','preserved_failed_execution04'):check(p[key])
 check(support)
 for preserved in p['preserved_control_artifacts']:check(preserved)
 check_partial()
 need(set(q.name for q in control.iterdir())=={'result.json','system-support.json',*[Path(r['path']).name for r in p['preserved_partial_outputs']],*[Path(r['path']).name for r in p['preserved_control_artifacts']]},'Control changed before install')
 root.mkdir()
 result={'schema':'orbit-poc-direct-fit-helper-install-result-v1','status':'running','plan':{'path':str(root/'install-plan.json'),'sha256':sha(PLAN_DATA)},'archive':{'path':str(root/'helpers-and-request.tar'),'sha256':sha(ARCHIVE_DATA)},'control':p['control'],'admission':admission,'installed':[],'native_executions':0,'fit_attempts':0,'fit_execution_authorized':False}
 try:
  write(root/'install-plan.json',PLAN_DATA);write(root/'helpers-and-request.tar',ARCHIVE_DATA)
  for r in p['files']:
   target=control/r['name'];write(target,payload[r['name']])
   need(pin(target)['sha256']==r['sha256'],'Installed bytes changed')
   result['installed'].append({**pin(target),'bytes':target.stat().st_size,'mode':target.stat().st_mode&0o777})
  for key in ('driver','execution','stage_result','preparation_controller','prior_install_receipt','preserved_failed_execution','preserved_failed_execution04'):check(p[key])
  check(support)
  for preserved in p['preserved_control_artifacts']:check(preserved)
  check_partial()
  need(set(q.name for q in control.iterdir())=={'result.json','system-support.json',*[Path(r['path']).name for r in p['preserved_partial_outputs']],*payload.keys(),*[Path(r['path']).name for r in p['preserved_control_artifacts']]},'Unexpected post-install contents')
  for k in ('attempts','temporary'):
   q=Path(stage[k]['path']);s=q.stat();need((s.st_dev,s.st_ino)==(stage[k]['device'],stage[k]['inode']) and not any(q.iterdir()),'Fit directory changed')
  result.update(status='installed_metadata',preserved_stage_result=p['stage_result'],preserved_system_support=support)
 except BaseException as error:
  result.update(status='failed',error=repr(error),traceback=traceback.format_exc())
  write(root/'install-result.json',dump(result));raise
 write(root/'install-result.json',dump(result))
 print(json.dumps({'result':result,'result_pin':pin(root/'install-result.json')}))
'''
code='PLAN_B64='+repr(base64.b64encode(plan_data).decode())+'\nARCHIVE_B64='+repr(base64.b64encode(archive_data).decode())+'\n'+code
(C/'remote-install02.py').write_text(code)
start=time.time()
r=subprocess.run(['/mnt/c/Windows/System32/OpenSSH/ssh.exe','-o','BatchMode=yes','gpuserver4090','env PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -'],input=code,text=True,capture_output=True)
(C/'install02.stdout.json').write_text(r.stdout);(C/'install02.stderr.log').write_text(r.stderr)
process={'returncode':r.returncode,'wall_seconds':time.time()-start,'script_sha256':sha(code.encode()),'native_executions':0,'fit_attempts':0}
(C/'install02-process.json').write_text(json.dumps(process,indent=2)+'\n')
print(json.dumps(process))
if r.returncode:print(r.stderr);raise SystemExit(r.returncode)
result=json.loads(r.stdout)
(C/'install02-result.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(json.dumps({'status':result['result']['status'],'files':len(result['result']['installed']),'result_pin':result['result_pin']}))
