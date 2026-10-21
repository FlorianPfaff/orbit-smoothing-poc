from pathlib import Path
import json,hashlib,fcntl,importlib.util,os,datetime
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');c=B/'fit-seal-control-07';out=B/'control-generated-bytecode-01';cache=c/'__pycache__';f=cache/'plan_segmented_fit_namespace01.cpython-310.pyc'
def need(v,m):
 if not v:raise ValueError(m)
def pin(p):
 st=p.stat();return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':st.st_size,'device':st.st_dev,'inode':st.st_ino}
driver=B/'validation-07/control/owned_driver09.py';need(pin(driver)['sha256']=='72ac591a4c0b1d18b67b2739d694be40e271ec09d7b0f9b3dcad4287cb88fdcd','Driver pin')
s=importlib.util.spec_from_file_location('d',driver);d=importlib.util.module_from_spec(s);s.loader.exec_module(d);e=d.load_execution(B/'preparation-07/control/execution.json')
with Path('/mnt/seagate10tb/orbit-v31-correctness-10-florianpfaff/control/candidate09-validation.lock').open('a') as lock,(B/'validation-07/run/.segmented.lock').open('rb') as sl:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(sl,fcntl.LOCK_EX|fcntl.LOCK_NB);admission=d.admission(e)
 need(not out.exists() and cache.is_dir() and not cache.is_symlink() and sorted(p.name for p in cache.iterdir())==[f.name],'Exact fresh cache scope')
 before=pin(f);need(before['sha256']=='be16ed4ac807820b2682342f9c3c2fe4e8c209d83d4dde0cf89fff79d27d2845' and before['bytes']==22856,'Cache changed')
 out.mkdir();cache.rename(out/'preserved-cache');after=pin(out/'preserved-cache'/f.name);need(all(before[k]==after[k] for k in ('sha256','bytes','device','inode')),'Preservation identity changed')
 record={'schema':'orbit-poc-generated-bytecode-preservation-v1','status':'preserved','at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'attribution':'Read-only diagnostic analyze_direct_sealing04_symlinks01.py imported planner without -B; one generated cache restored outside strict sealed control membership. No numerical execution or scientific source changed.','before':before,'after':after,'admission':admission,'control_cache_absent':not cache.exists(),'native_executions':0,'fit_attempts':0}
 (out/'receipt.json').write_text(json.dumps(record,indent=2,sort_keys=True)+'\n');print(json.dumps({'receipt':record,'receipt_pin':pin(out/'receipt.json')}))
