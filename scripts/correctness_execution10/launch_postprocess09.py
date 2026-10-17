from pathlib import Path
import json,hashlib,subprocess,os,signal,time,datetime
old=Path('/mnt/seagate10tb/orbit-v31-correctness-08-florianpfaff');new=Path('/mnt/seagate10tb/orbit-v31-correctness-09-florianpfaff');c=new/'control'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):
 with p.open('x') as f:json.dump(v,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
plan=json.loads((old/'control/candidate07-postprocess-plan.json').read_text());launch=json.loads((c/'candidate09-launch.json').read_text())
freeze=json.loads((c/'candidate09-source-freeze.json').read_text())
plan.update(schema='orbit-poc-correctness-postprocess09-plan-v1',source_commit=freeze['commit'],source_sha256=freeze['source']['sha256'])
plan['helpers']={name.replace('_07.py','_09.py'):sha(c/name.replace('_07.py','_09.py')) for name in plan['helpers']}
plan['postprocessor_sha256']=sha(c/'postprocess_candidate09.py')
for k,name in [('execution','candidate09-execution.json'),('candidate_pins','candidate09-pins.json')]:plan[k]={'path':str(c/name),'sha256':sha(c/name)}
plan['driver_process']=launch['driver_process'];plan['output_root']=str(new/'postprocess-09-01')
p=c/'candidate09-postprocess-plan.json';save(p,plan)
assert sha(c/'postprocess_candidate09.py')==plan['postprocessor_sha256']
argv=[plan['reporting_python']['path'],str(c/'postprocess_candidate09.py'),'--plan',str(p),'--plan-sha256',sha(p)]
signal.signal(signal.SIGHUP,signal.SIG_IGN)
with (c/'candidate09-postprocess.log').open('x') as log:
 child=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
try:
 proc=Path('/proc')/str(child.pid)
 fields=(proc/'stat').read_text().rsplit(')',1)[1].split();ticks=int(fields[19]);deadline=time.monotonic()+5
 while True:
  fields=(proc/'stat').read_text().rsplit(')',1)[1].split()
  if int(fields[19])!=ticks:raise RuntimeError('Postprocessor process identity changed')
  raw=(proc/'cmdline').read_bytes();observed=[v.decode() for v in raw.split(b'\0') if v]
  if observed==argv:break
  if child.poll() is not None:raise RuntimeError('Postprocessor exited before handoff')
  if observed or time.monotonic()>=deadline:raise RuntimeError('Postprocessor command identity mismatch')
  time.sleep(.01)
 receipt={'schema':'orbit-poc-recovery09-postprocess-launch-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'postprocess_process':{'pid':child.pid,'start_ticks':ticks,'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()},'plan':{'path':str(p),'sha256':sha(p)},'argv':argv,'observed_argv':observed,'command_sha256':hashlib.sha256(raw).hexdigest(),'scientific_work':'none: read-only evidence processing after exact driver terminal cleanup'}
 save(c/'candidate09-postprocess-launch.json',receipt)
except BaseException:
 if child.poll() is None:
  child.terminate()
  try:child.wait(timeout=30)
  except subprocess.TimeoutExpired:child.kill();child.wait(timeout=30)
 raise
try:print(json.dumps(receipt),flush=True)
except OSError:pass
