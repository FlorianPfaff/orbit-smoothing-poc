from pathlib import Path
import base64,hashlib,json,subprocess,time
C=Path('/mnt/d/orbit-segmented-v4/control');P=C/'loader-alias-smoke-packet01';O=C/'loader-alias-smoke-execution01'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
if sha(P/'staging-plan.json')!='1a789ed44feeeab3b5365d3b6a3745689e3eeac72e4dbef1f564fd94053d91ad':raise ValueError('Reviewed staging plan changed')
plan=json.loads((P/'staging-plan.json').read_text());payload={}
for row in plan['files']:
 data=Path(row['local']).read_bytes()
 if hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('Payload changed')
 payload[row['target']]={'data':base64.b64encode(data).decode(),'sha256':row['sha256']}
code=r'''
from pathlib import Path
import base64,fcntl,hashlib,importlib.util,json,os,signal,traceback
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');S=B/'loader-alias-smoke-control-01';out=B/'loader-alias-smoke-execution01'
def need(v,m):
 if not v:raise ValueError(m)
def pin(p):return {'path':str(p),'sha256':hashlib.sha256(Path(p).read_bytes()).hexdigest()}
def check(p,h):need(pin(p)['sha256']==h,'Changed artifact '+str(p))
def read(p):check(p['path'],p['sha256']);return json.loads(Path(p['path']).read_text())
def write(p,v):
 with p.open('x') as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
def verify_old():
 for cap in PLAN['original_captures']:
  x=read(cap);need(x['fit_attempts']==0 and x['attempts_empty'] and x['temporary_empty'] and not x['prelaunch_probe_present'],'Original zero-fit boundary differs')
  for r in x['files']:check(r['path'],r['sha256'])
  for i in x['owned_identities']:
   p=Path('/proc')/str(i['pid'])/'stat'
   if p.exists():
    fields=p.read_text().rsplit(')',1)[1].split();need(int(fields[19])!=i['start_ticks'] or fields[0]=='Z','Old owned process is live')
def empty(mount):
 rows=mount['writable_mounts'];need(len(rows)==3 and {r['kind'] for r in rows}=={'attempts','temporary','lock'},'Original3writables required')
 for r in rows:
  p=Path(r['source']);i=r['identity'];s=p.stat();need(r['source']==r['target'] and not p.is_symlink() and p.resolve()==p and (s.st_dev,s.st_ino)==(i['device'],i['inode']),'Writable identity differs')
  need((p.is_file() and s.st_size==0) if r['kind']=='lock' else (p.is_dir() and not any(p.iterdir())),'Fits/temp must remain empty')
driver=B/'validation-07/control/owned_driver09.py';check(driver,'72ac591a4c0b1d18b67b2739d694be40e271ec09d7b0f9b3dcad4287cb88fdcd');execution=B/'preparation-07/control/execution.json';check(execution,'b6fa593f108beaabc8d2e8a6d6ce2e9e06aba9954b6ed9c1425b96b9fb89f6c3')
s=importlib.util.spec_from_file_location('owned',driver);d=importlib.util.module_from_spec(s);s.loader.exec_module(d);e=d.load_execution(execution)
for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,d.interrupted)
with Path('/mnt/seagate10tb/orbit-v31-correctness-10-florianpfaff/control/candidate09-validation.lock').open('a') as lock,(B/'validation-07/run/.segmented.lock').open('rb') as stat:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(stat,fcntl.LOCK_EX|fcntl.LOCK_NB);admission=d.admission(e);verify_old()
 old=read(PLAN['original_invocation']);new=json.loads(base64.b64decode(PAYLOAD[str(S/'invocation.json')]['data']));need({k:v for k,v in new.items() if k!='wrapper'}=={k:v for k,v in old.items() if k!='wrapper'},'Only wrapper may change')
 need(new['wrapper']=={'path':str(B/'bwrap-cap-01/controls/with_segmented_fit_namespace04.py'),'sha256':'4b3796ca75e731077600b5f8ba15d1697ddb5cfa0d9fcff8c8b6434862748827'},'Wrong wrapper04')
 mount=read(new['mount_plan']);empty(mount);check(new['bubblewrap']['path'],new['bubblewrap']['sha256']);parent=Path(PLAN['wrapper_parent']['path']);st=parent.stat();need(parent.resolve()==parent and not parent.is_symlink() and (st.st_dev,st.st_ino)==(2048,239602682),'Wrapper directory identity changed')
 need({p.name for p in parent.iterdir()}=={'with_segmented_fit_namespace03.py'},'Preserved wrapper directory membership differs');check(PLAN['preserved_wrapper']['path'],PLAN['preserved_wrapper']['sha256'])
 need(not S.exists() and not S.is_symlink() and not out.exists() and not out.is_symlink(),'Fresh smoke namespaces required')
 for path,row in PAYLOAD.items():
  p=Path(path);need(p.parent==S or p==parent/'with_segmented_fit_namespace04.py','Unexpected stage target');need(not p.exists() and not p.is_symlink(),'Preserve existing stage target');need(hashlib.sha256(base64.b64decode(row['data'])).hexdigest()==row['sha256'],'Transport changed')
 S.mkdir();out.mkdir()
 for path,row in PAYLOAD.items():
  with Path(path).open('xb') as f:f.write(base64.b64decode(row['data']))
 for path,row in PAYLOAD.items():check(path,row['sha256'])
 staging={'schema':'orbit-poc-loader-alias-smoke-staged-v1','admission':admission,'control':{'path':str(S),'device':S.stat().st_dev,'inode':S.stat().st_ino},'files':{p:pin(p) for p in PAYLOAD},'staged_at':d.stamp(),'fit_attempts':0};write(out/'staging.json',staging)
 request=PLAN['smoke_plan'];check(request['path'],request['sha256']);argv=['/usr/bin/taskset','-c','32','/usr/bin/python3','-B',str(S/'run_alias_probe01.py'),'--plan',request['path'],'--sha256',request['sha256']]
 env={'PATH':'/usr/bin:/bin','HOME':'/home/florianpfaff','PYTHONDONTWRITEBYTECODE':'1','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','NUMEXPR_NUM_THREADS':'1'}
 receipt={'schema':'orbit-poc-loader-alias-smoke-owned-execution-v1','status':'running','admission':admission,'argv':argv,'environment':env,'cwd':str(S),'staging':pin(out/'staging.json'),'fit_attempts':0,'original_captures':PLAN['original_captures'],'empty_writables_before':True};write(out/'launch.json',receipt);finish={};registry=[]
 def started(pid):write(out/'started.json',{'identity':d.proc(pid),'started_at':d.stamp()})
 def finished(v):finish.update(v)
 try:
  with (out/'probe.log').open('x') as log:rc=d.supervise(argv,cwd=S,env=env,log=log,limit=1800,guard_live=lambda:None,on_started=started,on_finished=finished,registry=registry)
  receipt.update(returncode=rc,**finish)
  lines=(out/'probe.log').read_bytes().splitlines(keepends=True);proofs=[];headers=[]
  for line in lines:
   try:v=json.loads(line)
   except (ValueError,UnicodeError):continue
   if v.get('schema')=='orbit-poc-loader-alias-probe-namespace-exec-v1':headers.append((line,v))
   if v.get('schema')=='orbit-poc-segmented-fit-inner-probe-result-v1':proofs.append((line,v))
  for name,values in [('namespace-exec',headers),('proof',proofs)]:
   if len(values)==1:
    with (out/(name+'.json')).open('xb') as f:f.write(values[0][0])
  need(rc==0 and finish['cleanup']['verified'] and not finish['cleanup']['live_owned_processes'] and not finish['interrupted_or_timeout'],'Actual probe execution failed')
  need(len(headers)==len(proofs)==1,'Exactly one actual namespace receipt/proof required');header=headers[0][1];proof=proofs[0][1]
  need(header['wrapper']==new['wrapper'] and header['mount_plan']==new['mount_plan'] and header['probe_spec']==new['probe_spec'] and header['sealed_options_sha256']=='c40ea3371aaa28675adad96262e090e1fde12033fd6b714b1afd295018a8532d','Actual namespace attribution differs')
  need(proof['status']=='passed' and proof['benchmark_attempts_launched']==0 and proof['fit_execution_authorized'] is False and proof['specification_file_sha256']==new['probe_spec']['sha256'],'Actual public probe did not pass')
  need(proof['host_verified_final_artifacts']=={'allowlist_sha256':'a768ddf14c8ebb7fb11e4752c9787da407f7db77ee618176ae2946ce32c4ed3d','mount_plan_sha256':new['mount_plan']['sha256'],'expected_completed':0} and proof['public_readonly_checks']['terminal_prefix']==[] and proof['public_readonly_checks']['validation']['status']=='passed','Actual public verification attribution differs')
  empty(mount);verify_old()
  for path,row in PAYLOAD.items():check(path,row['sha256'])
  receipt.update(status='passed',proof=pin(out/'proof.json'),namespace_exec=pin(out/'namespace-exec.json'),empty_writables_after=True)
 except BaseException as error:receipt.update(status='failed',error=repr(error),traceback=traceback.format_exc(),**finish)
 finally:
  receipt['finished_at']=d.stamp();receipt['log']=pin(out/'probe.log');write(out/'execution.json',receipt)
 print(json.dumps({'status':receipt['status'],'execution':pin(out/'execution.json'),'receipt':receipt}))
 if receipt['status']!='passed':raise SystemExit(1)
'''
code='PLAN='+repr(plan)+'\nPAYLOAD='+repr(payload)+'\n'+code
O.mkdir();(O/'remote-run.py').write_text(code);start=time.time();r=subprocess.run(['/mnt/c/Windows/System32/OpenSSH/ssh.exe','-o','BatchMode=yes','gpuserver4090','env PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -B -'],input=code,text=True,capture_output=True)
(O/'stdout.json').write_text(r.stdout);(O/'stderr.log').write_text(r.stderr);(O/'process.json').write_text(json.dumps({'returncode':r.returncode,'elapsed_seconds':time.time()-start,'script_sha256':hashlib.sha256(code.encode()).hexdigest()},indent=2)+'\n');print(json.dumps({'returncode':r.returncode,'elapsed_seconds':time.time()-start}))
if r.stdout:
 v=json.loads(r.stdout);print(json.dumps({'status':v['status'],'execution':v['execution']}))
if r.returncode:print(r.stderr);raise SystemExit(r.returncode)
