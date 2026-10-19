from pathlib import Path
import json,hashlib,fcntl,importlib.util
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');D=B/'validation-07/control/owned_driver09.py';E=B/'preparation-07/control/execution.json';H=B/'fit-campaign-control-09'
def need(v,m):
 if not v:raise ValueError(m)
def pin(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
need(pin(D)['sha256']=='72ac591a4c0b1d18b67b2739d694be40e271ec09d7b0f9b3dcad4287cb88fdcd','Driver changed');need(pin(E)['sha256']=='b6fa593f108beaabc8d2e8a6d6ce2e9e06aba9954b6ed9c1425b96b9fb89f6c3','Execution changed')
s=importlib.util.spec_from_file_location('owned',D);d=importlib.util.module_from_spec(s);s.loader.exec_module(d);e=d.load_execution(E)
with Path('/mnt/seagate10tb/orbit-v31-correctness-10-florianpfaff/control/candidate09-validation.lock').open('a') as lock,(B/'validation-07/run/.segmented.lock').open('rb') as stat:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(stat,fcntl.LOCK_EX|fcntl.LOCK_NB);a=d.admission(e)
 p=B/'campaign08-terminal-01/manifest.json';need(pin(p)['sha256']=='cd831883bd951e2d36deadd1f8cadd0954e9ed5daa5c4e785226868d5785325d','Terminal capture changed');cap=json.loads(p.read_text())
 for i in cap['owned_identities']:
  try:n=d.proc(i['pid'])
  except FileNotFoundError:n=None
  need(n is None or n['start_ticks']!=i['start_ticks'] or n['state']=='Z','Old owned process still live')
 need(not any((B/'validation-07/run/attempts').iterdir()) and not any((B/'validation-07/temporary/fit-private').iterdir()),'Fit dirs notempty')
 need(not H.exists() and not H.is_symlink(),'Preserve existing09');H.mkdir();st=H.stat();print(json.dumps({'schema':'orbit-poc-campaign09-control-identity-v1','created_at':d.stamp(),'admission':a,'control':{'path':str(H),'device':st.st_dev,'inode':st.st_ino},'intervening08_capture':pin(p),'empty':True,'fit_attempts':0,'native_executions':0}))
