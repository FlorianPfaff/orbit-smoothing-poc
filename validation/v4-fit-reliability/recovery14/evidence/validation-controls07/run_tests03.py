from pathlib import Path
import datetime,hashlib,json,os,subprocess,time
B=Path(__file__).absolute().parent
P=Path('/mnt/c/users/emper/documents/codex/2026-10-13/i-x20/work/numerics-v3.1/python/bin/python')
def pin(p): return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}
def save(p,v):
 with p.open('x') as f: json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
files=[B/n for n in ['reference_gates09.py','reference_recovery.py','reference_runtime09.py','reference_storage09.py','test_reference_gates09.py','test_reference_storage09.py','test_reference_recovery.py','reference_objective_output.py','test_reference_objective_output.py','test_reference_composed_parent.py','run_tests03.py']]
expected=[pin(p) for p in files]
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
command=[str(P),'-s','-B','-m','pytest','-p','no:cacheprovider','-q',*[str(p) for p in files if p.name.startswith('test_')],'--junitxml='+str(B/'tests03.xml')]
plan={'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'boot_id':boot,'files':expected,'python':pin(P),'argv':command,'native_launch':False}
save(B/'tests03-plan.json',plan);start=time.monotonic()
with (B/'tests03.log').open('x') as stream:
 result=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'})
same=expected==[pin(p) for p in files];boot_same=boot==Path('/proc/sys/kernel/random/boot_id').read_text().strip()
save(B/'tests03-result.json',{'returncode':result.returncode,'elapsed_seconds':time.monotonic()-start,'boot_unchanged':boot_same,'boot_id':boot,'files_unchanged':same,'passed':result.returncode==0 and same and boot_same,'plan':pin(B/'tests03-plan.json'),'log':pin(B/'tests03.log'),'junit':pin(B/'tests03.xml')})
print(json.dumps({'returncode':result.returncode,'files_unchanged':same,'boot_unchanged':boot_same}))
