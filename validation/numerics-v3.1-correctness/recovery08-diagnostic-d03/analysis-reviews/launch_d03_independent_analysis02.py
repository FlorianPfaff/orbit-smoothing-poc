#!/usr/bin/env python3
"""Stage and run only the frozen, read-only Decimal diagnostic after terminal proof."""
import argparse, base64, hashlib, json, subprocess, time
from pathlib import Path
BASE=Path('@LOCAL_DATA_ROOT@/orbit-numerics-v3.1/correctness')
REMOTE='@REMOTE_DATA_ROOT@/orbit-v31-diagnostic-row-trace-03-PRIVATE_USER'
SSH='@WINDOWS_MOUNT@/Windows/System32/OpenSSH/ssh.exe'
PIN='6117760a808f37ea786637bbe707df63f156882385d92fff9798f5bb95277b59'
PLAN='0846eeaddca404116ecc8ee1d8de404aa1e46e00df5517e207d06e55d53b21bd'
p=argparse.ArgumentParser();p.add_argument('--equivalence-sha256',required=True);a=p.parse_args()
files={}
for name in ('analyze_nuisance_trace.py','test_analyze_nuisance_trace.py','README.md','validation.json'):
    raw=(BASE/'control/row-trace-d03-analysis-01'/name).read_bytes()
    files[name]={'sha256':hashlib.sha256(raw).hexdigest(),'base64':base64.b64encode(raw).decode()}
assert files['analyze_nuisance_trace.py']['sha256']==PIN
payload={'root':REMOTE,'files':files,'plan_sha256':PLAN,'equivalence_sha256':a.equivalence_sha256,'analyzer_sha256':PIN}
bootstrap=r'''
import base64, datetime, hashlib, json, os, resource, signal, subprocess, sys, time, traceback
from pathlib import Path
sys.dont_write_bytecode=True
p=PAYLOAD
root=Path(p['root']); out=root/'staging/independent-analysis-02'
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def art(path):return {'path':str(path),'sha256':sha(path),'bytes':Path(path).stat().st_size}
def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
assert sha(root/'control/plan.json')==p['plan_sha256']
pipe=json.loads((root/'diagnostic/pipeline.json').read_text())
assert pipe['status']=='completed' and pipe['final_cleanup']['verified'] and pipe['finished_at']
assert len(pipe['final_cleanup']['commands'])==len(pipe['steps'])
assert all(s['verified'] and not s['live_owned_processes'] for s in pipe['final_cleanup']['commands'])
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()=='95156dd4-0d4c-499d-a214-8883a2d650fa'
for group in pipe['final_cleanup']['commands']:
 for identity in group['identities']:
  try: fields=Path(f"/proc/{identity['pid']}/stat").read_text().rsplit(')',1)[1].split()
  except FileNotFoundError: continue
  assert int(fields[19])!=identity['start_ticks'] or fields[0]=='Z'
assert pipe['native']['sha256']=='3a113ae1a88954a33f81f6e251ecffb98a757058821568965aae11658be8e251'
assert sha(pipe['native']['path'])==pipe['native']['sha256']
assert sha(root/'diagnostic/equivalence.json')==p['equivalence_sha256']
eq=json.loads((root/'diagnostic/equivalence.json').read_text())
assert eq['passed'] is True and len(eq['checks'])==52
assert 32 in os.sched_getaffinity(0)
runtime=Path('@REMOTE_HOME@/codex-runs/orbit-poc-20261013/env/bin/python')
assert sha(runtime)=='6759dcc6aa5a3fe3377349092f92f6700f1f79017294c1d0085009eb8802cb1e'
version=subprocess.run([str(runtime),'--version'],capture_output=True,text=True,check=True).stdout.strip()
assert version=='Python 3.11.15'
out.mkdir(exist_ok=False)
for name,data in p['files'].items():
 raw=base64.b64decode(data['base64']);assert hashlib.sha256(raw).hexdigest()==data['sha256']
 (out/name).write_bytes(raw)
assert sha(out/'analyze_nuisance_trace.py')==p['analyzer_sha256']
traces=sorted((root/'diagnostic/trace').glob('nuisance-trace-*.tsv'));assert traces
before=[{'path':str(f),'bytes':f.stat().st_size,'mtime_ns':f.stat().st_mtime_ns} for f in traces]
cmd=['/usr/bin/taskset','-c','32',str(runtime),str(out/'analyze_nuisance_trace.py'),'--trace-directory',str(root/'diagnostic/trace'),'--equivalence',str(root/'diagnostic/equivalence.json'),'--factor',str(root/'diagnostic/trace-on/qr.4.factor.json'),'--line-search',str(root/'diagnostic/trace-on/qr.4.nuisance_line_search.json'),'--output',str(out/'result.json')]
receipt={'schema':'orbit-poc-d03-independent-analysis-invocation-v1','status':'running','started_at':stamp(),'command':cmd,'runtime':{**art(runtime),'version':version},'cpu':32,'wall_limit_seconds':1800,'address_space_limit_bytes':64*1024**3,'native_processes_run':False,'scientific_validation_complete':False,'covariance_authorized':False,'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'provenance':{name:art(root/name) for name in ('control/plan.json','control/diagnostic-execution.json','diagnostic/pipeline.json','diagnostic/equivalence.json')},'staged_files':{name:art(out/name) for name in p['files']},'trace_stats_before':before}
def save():
 tmp=out/'receipt.tmp';tmp.write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n');tmp.replace(out/'receipt.json')
def limit():resource.setrlimit(resource.RLIMIT_AS,(64*1024**3,64*1024**3))
start=time.monotonic();save();child=None
try:
 with (out/'stdout.log').open('xb') as stdout,(out/'stderr.log').open('xb') as stderr:
  child=subprocess.Popen(cmd,cwd=out,stdout=stdout,stderr=stderr,start_new_session=True,preexec_fn=limit,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'})
  receipt['pid']=child.pid;receipt['start_ticks']=int(Path(f'/proc/{child.pid}/stat').read_text().rsplit(')',1)[1].split()[19]);save()
  try:code=child.wait(timeout=1800);receipt.update(returncode=code,status='completed' if code==0 else 'failed',timed_out=False)
  except subprocess.TimeoutExpired:
   os.killpg(child.pid,signal.SIGKILL);child.wait();receipt.update(returncode=child.returncode,status='timeout',timed_out=True)
except BaseException as error:
 receipt.update(status='invocation_error',error=repr(error),traceback=traceback.format_exc())
 if child is not None and child.poll() is None:os.killpg(child.pid,signal.SIGKILL);child.wait()
finally:
 receipt.update(finished_at=stamp(),elapsed_seconds=time.monotonic()-start,peak_child_rss_kib=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
 receipt['trace_stats_after']=[{'path':str(f),'bytes':f.stat().st_size,'mtime_ns':f.stat().st_mtime_ns} for f in traces]
 receipt['trace_stats_unchanged']=receipt['trace_stats_after']==before
 receipt['terminal_evidence_unchanged']=all(sha(v['path'])==v['sha256'] for v in receipt['provenance'].values())
 receipt['artifacts']={f.name:art(f) for f in out.iterdir() if f.name not in {'receipt.json','receipt.tmp'} and f.is_file()}
 receipt['owned_child_reaped']=child is None or child.poll() is not None
 save()
print(json.dumps({'status':receipt['status'],'receipt':art(out/'receipt.json'),'result':receipt['artifacts'].get('result.json'),'elapsed_seconds':receipt['elapsed_seconds'],'peak_child_rss_kib':receipt['peak_child_rss_kib']}))
'''.replace('PAYLOAD',repr(payload),1)
local=BASE/'control/d03-analysis-invocation-02.json'
assert not local.exists()
start=time.monotonic()
r=subprocess.run([SSH,'gpuserver4090','python3 -'],input=bootstrap,text=True,capture_output=True)
record={'command':[SSH,'gpuserver4090','python3 -'],'elapsed_seconds':time.monotonic()-start,'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr,'bootstrap_sha256':hashlib.sha256(bootstrap.encode()).hexdigest(),'analyzer_sha256':PIN,'expected_equivalence_sha256':a.equivalence_sha256}
local.write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
print(json.dumps({'invocation':str(local),'sha256':hashlib.sha256(local.read_bytes()).hexdigest(),**record}))
raise SystemExit(r.returncode)
