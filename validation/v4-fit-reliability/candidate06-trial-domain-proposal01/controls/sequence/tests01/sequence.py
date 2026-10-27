"""Audited serial candidate06 correctness then cold fits; original controllers own execution."""
from pathlib import Path
import argparse, datetime, hashlib, importlib.util, json, os, signal, stat, subprocess, sys, time

ROOT = Path(__file__).absolute().parent
BASE = ROOT.parent
GATE = BASE/'density-trial-controls01/reference_recovery.py'
GATE_RUNNER = GATE.with_name('reference_gates09.py')
COLD = BASE/'density-trial-cold-controls01/one_hour_controls.py'
CONTRACTS = COLD.with_name('contracts.py')
SOURCE = Path('/mnt/d/orbit-v41-density-trial-candidate06/source')
SNAPSHOT = SOURCE.parent/'source-snapshot.json'
GATE_OUT = BASE/'candidate06-correctness01'
COLD_OUT = BASE/'candidate06-cold01'
STAGES = ('native-tests','correction-tests','synthetic-refinement-log_drag_ou','synthetic-refinement-pulses','flight-refinement','eccentric-24h-refinement','objective-log_drag_ou','objective-pulses','nuisance-replay','nuisance-replay-candidate1-point012')

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def read(p):return json.loads(Path(p).read_text())
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for block in iter(lambda:f.read(1048576),b''):h.update(block)
 return h.hexdigest()
def require(ok,reason):
 if not ok:raise ValueError(reason)
def pin(p):return {'path':str(Path(p).absolute()),'sha256':sha(p)}
def verify(p):require(sha(p['path'])==p['sha256'],'Pinned identity differs: '+p['path'])
def save(p,v):
 with Path(p).open('x') as f:json.dump(v,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
def load(p,name):
 verify(p);spec=importlib.util.spec_from_file_location(name,p['path']);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;exec(compile(Path(p['path']).read_bytes(),p['path'],'exec'),m.__dict__);return m

def checked(path,digest):
 verify({'path':str(path),'sha256':digest});p=read(path)
 require(p['schema']=='candidate06-correctness-cold-sequence-v1','Unknown sequence')
 require(p['boot_id']==Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'Previous boot; preserve interrupted attempt')
 expected={'driver':Path(__file__).absolute(),'gate_controller':GATE,'gate_runner':GATE_RUNNER,'cold_controller':COLD,'cold_contracts':CONTRACTS,'candidate_snapshot':SNAPSHOT,'gate_freeze':GATE_OUT/'freeze.json','cold_freeze':COLD_OUT/'freeze.json'}
 for key,value in expected.items():require(p[key]['path']==str(value),'Unexpected '+key)
 for key in (*expected,'source_review','gate_review','cold_review','python'):verify(p[key])
 for x in p['helper_pins']:verify(x)
 require(p['gate_stages']==list(STAGES) and p['cold_stages']==['cold-pulses','cold-density'],'Required stage inventory changed')
 require(sha(sys.executable)==p['python']['sha256'],'Sequence needs pinned interpreter')
 review=read(p['source_review']['path']);require(review['approved'] and review['candidate_source_snapshot_sha256']==p['candidate_snapshot']['sha256'],'Candidate source review differs')
 return p

def controls(p):
 gate=load(p['gate_controller'],'candidate06_sequence_reference')
 load(p['cold_contracts'],'contracts')
 cold=load(p['cold_controller'],'candidate06_sequence_cold')
 return gate,cold

def gate_audit(p):
 """Certify original strict stage receipts before authorizing any cold-fit call."""
 f=read(p['gate_freeze']['path']);verify(f['plan']);plan=read(f['plan']['path']);r=read(GATE_OUT/'result.json');d=read(GATE_OUT/'detached-result.json')
 require(d['status']=='complete' and d['returncode']==0 and d['error'] is None and not d['signals_received'],'Correctness controller did not finish strictly')
 require(d['freeze_sha256']==p['gate_freeze']['sha256'] and d['review_sha256']==p['gate_review']['sha256'],'Correctness attribution differs')
 require(r['all_ten_strict_passed'] and r['error'] is None and r['planned_stages']==list(STAGES),'Not all ten correctness gates passed')
 require([x['stage'] for x in r['stages']]==list(STAGES),'Missing or reordered gate outcome')
 evidence=[]
 for row,job in zip(r['stages'],plan['jobs']):
  require(row['stage']==job['stage'] and row['status']=='passed' and row['cleanup_verified'] and row['input_identity_after']=='verified','A required gate failed')
  for key in ('execution','strict_result'):verify(row[key])
  s=read(row['execution']['path']);q=read(row['strict_result']['path']);clean=s.get('cleanup',{})
  require(s['status']=='complete' and s['returncode']==0 and s['owned_process_group_cleaned'] and clean.get('verified') is True and clean.get('empty_tree_certificate')=='kernel_ECHILD' and clean.get('remaining')==[],'Gate cleanup/execution failed')
  require(q['status']=='passed' and q['stage']==job['stage'] and q['argv']==job['argv'] and q['returncode']==0,'Gate strict receipt differs')
  if row['stage'] in ('native-tests','correction-tests'):
   require(q['evidence']['tests']==(106 if row['stage']=='native-tests' else 51),'Native test count differs')
  evidence.append({'stage':row['stage'],'strict':row['strict_result'],'supervisor':row['execution']})
 return {'passed':True,'gate_result':pin(GATE_OUT/'result.json'),'detached_result':pin(GATE_OUT/'detached-result.json'),'evidence':evidence,'scope':'Strict saved original gate parsers, frozen commands, input identity and verified owned cleanup; no replacement of terminal scientific review.'}

def fresh():
 require(not any((ROOT/n).exists() for n in ('launch.json','started.json','result.json','detached.log')),'Preserve existing sequence attempt')
 for root in (GATE_OUT,COLD_OUT):
  require(root.resolve()==root and root.is_dir(),'Missing canonical prepared output')
  require(not any((root/n).exists() for n in ('detached-started.json','detached-result.json','run-started.json','run.lock','launch.json','result.json')),'Preserve old phase attempt: '+str(root))

def review_check(p,digest,audit,audit_sha):
 verify({'path':str(audit),'sha256':audit_sha});a=read(audit)
 require(a.get('schema')=='candidate06-sequence-launch-review-v1' and a.get('approved') is True and a.get('plan_sha256')==digest and a.get('driver_sha256')==p['driver']['sha256'] and a.get('strict_gates_before_cold') is True,'No exact sequence approval')

def run(path,digest,audit,audit_sha):
 phase='startup';code=1;error=None;started=time.monotonic();signals=[];handlers={}
 def interrupted(number,frame):signals.append(number);raise KeyboardInterrupt('Sequence interrupted')
 for number in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):handlers[number]=signal.signal(number,interrupted)
 try:
  save(ROOT/'started.json',{'at':now(),'pid':os.getpid(),'plan_sha256':digest,'audit_sha256':audit_sha,'phase_execution':'Sequential calls to pinned existing controller execute functions in this same detached process; their original subreaper supervisors own every numerical worker.'})
  p=checked(path,digest);review_check(p,digest,audit,audit_sha);gate,cold=controls(p);phase='correctness'
  code=gate.execute(Path(p['gate_freeze']['path']),p['gate_freeze']['sha256'],Path(p['gate_review']['path']),p['gate_review']['sha256'])
  if code!=0:raise RuntimeError('Correctness execution failed; cold fits not launched')
  checked(path,digest);approved=gate_audit(p);save(ROOT/'correctness-terminal-audit.json',approved)
  phase='cold_fits'
  code=cold.execute(Path(p['cold_freeze']['path']),p['cold_freeze']['sha256'],Path(p['cold_review']['path']),p['cold_review']['sha256'])
  checked(path,digest)
  result=read(COLD_OUT/'result.json');require(result['planned_stages']==p['cold_stages'],'Cold inventory differs')
  require([x['stage'] for x in result['stages']]==p['cold_stages'],'Cold stage missing')
  if code!=0 or result['status']!='passed':raise RuntimeError('One or both cold full fits did not pass; preserved results require review')
  phase='finished';code=0
 except BaseException as exc:code=1;error=repr(exc)
 finally:
  for number,handler in handlers.items():signal.signal(number,handler)
  interrupted_phase=any((q/'detached-result.json').is_file() and read(q/'detached-result.json').get('status')=='interrupted' for q in (GATE_OUT,COLD_OUT))
  save(ROOT/'result.json',{'status':'interrupted' if signals or interrupted_phase else 'complete' if code==0 else 'failed','returncode':code,'phase':phase,'error':error,'signals_received':signals,'elapsed_seconds':time.monotonic()-started,'plan_sha256':digest,'audit_sha256':audit_sha,'correctness_result':str(GATE_OUT/'result.json'),'cold_result':str(COLD_OUT/'result.json'),'release_authority':False,'old_results_reused':False})
 return code

def launch(path,digest,audit,audit_sha):
 p=checked(path,digest);review_check(p,digest,audit,audit_sha);fresh();gate,cold=controls(p)
 # Original launch reviews and complete runtime identities are rechecked in each execute call.
 adm=gate.admission(cpu=4);require(adm['available_memory_bytes']>=16*1024**3,'Insufficient memory headroom')
 argv=[p['python']['path'],'-s','-B',str(Path(__file__).absolute()),'_run','--plan',str(path),'--sha256',digest,'--audit',str(audit),'--audit-sha256',audit_sha]
 with (ROOT/'detached.log').open('x') as log:
  child=subprocess.Popen(argv,cwd=ROOT,env=gate.inherited_environment(gate.runner_api().base_env()),stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
 fields=Path(f'/proc/{child.pid}/stat').read_text().rsplit(')',1)[1].split()
 record={'pid':child.pid,'start_ticks':int(fields[19]),'boot_id':p['boot_id'],'at':now(),'argv':argv,'plan_sha256':digest,'audit_sha256':audit_sha,'admission':adm,'phase_controllers_share_this_pid':True,'old_results_reused':False};save(ROOT/'launch.json',record);return record

def main():
 a=argparse.ArgumentParser();a.add_argument('operation',choices=('launch','_run'));a.add_argument('--plan',type=Path,required=True);a.add_argument('--sha256',required=True);a.add_argument('--audit',type=Path,required=True);a.add_argument('--audit-sha256',required=True);v=a.parse_args()
 if v.operation=='launch':print(json.dumps(launch(v.plan,v.sha256,v.audit,v.audit_sha256)));return 0
 return run(v.plan,v.sha256,v.audit,v.audit_sha256)
if __name__=='__main__':raise SystemExit(main())
