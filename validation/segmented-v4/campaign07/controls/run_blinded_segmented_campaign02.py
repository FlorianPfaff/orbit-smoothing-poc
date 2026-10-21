#!/usr/bin/env python3
"""One public run inside a persistent blind namespace, with pre/post evidence."""
from pathlib import Path
import argparse,contextlib,hashlib,importlib.util,json,time,signal

KEYS={'schema','helper','config','probe_helper','probe_spec','state_checker'}
def need(ok,why):
 if not ok:raise RuntimeError(why)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def checked(p):
 need(isinstance(p,dict) and set(p)=={'path','sha256'} and Path(p['path']).is_absolute() and sha(p['path'])==p['sha256'],'Inner pinned artifact changed')
def module(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def save(p,v):
 with Path(p).open('x') as f:json.dump(v,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
def inspect_plan(p,completed):
 need(set(p)==KEYS and p['schema']=='orbit-poc-segmented-blind-inner-campaign-v1','Unknown inner campaign options')
 for k in KEYS-{'schema'}:checked(p[k])
 need(p['helper']['sha256']==sha(__file__),'Inner controller changed')
 need(type(completed) is int and 0<=completed<68,'All68 complete is a no-op outside this controller')
 spec=json.loads(Path(p['probe_spec']['path']).read_text());need(spec['config']==p['config'],'Probe configuration differs')
 return spec

SIGNALS=(signal.SIGINT,signal.SIGTERM,signal.SIGHUP)
def interrupted(number,_frame):raise KeyboardInterrupt('Owned inner controller interrupted by signal '+str(number))
@contextlib.contextmanager
def signal_scope(handler):
 previous={n:signal.getsignal(n) for n in SIGNALS}
 try:
  for n in SIGNALS:signal.signal(n,handler)
  yield
 finally:
  for n,h in previous.items():signal.signal(n,h)

def execute(p,spec,completed,allowlist_sha,mount_sha,probe,checker,cli,config,protocol,validation):
 # Native per-fit run_owned temporarily installs its own reviewed handlers and
 # restores these between fits. Never replace a handler while that call runs.
 with signal_scope(interrupted):
  return execute_guarded(p,spec,completed,allowlist_sha,mount_sha,probe,checker,cli,config,protocol,validation)

def execute_guarded(p,spec,completed,allowlist_sha,mount_sha,probe,checker,cli,config,protocol,validation):
 for value in (allowlist_sha,mount_sha):need(len(value)==64 and all(c in '0123456789abcdef' for c in value),'Invalid attributed outer identity')
 temporary=Path(spec['writable']['temporary']);out=temporary/'campaign-control';need(not out.exists() and not out.is_symlink(),'Preserve prior inner controller output');out.mkdir()
 project=Path(spec['source_root']);result={'schema':'orbit-poc-segmented-blind-inner-campaign-result-v2','status':'starting','config':p['config'],'source_sha256':spec['source_sha256'],'allowlist_sha256':allowlist_sha,'mount_plan_sha256':mount_sha,'starting_terminal_prefix':completed,'expected_attempts':68,'scientific_success_inferred':False,'timing_scope':'Public-run wall time includes its internal verification and dense certification. Per-fit timings remain exactly the frozen public supervisor measurements; separate startup/post probes are excluded.'}
 try:
  pre=probe.probe(spec,allowlist_sha256=allowlist_sha,mount_plan_sha256=mount_sha,expected_readonly_prefix=completed)
  need(pre.get('status')=='passed','Blind namespace probes failed');save(out/'prelaunch-probe.json',pre)
  for child in ('home','cache'):
   q=temporary/child;need(not q.is_symlink(),'Private HOME/cache cannot be symlinks');q.mkdir(exist_ok=True)
  before=checker.inspect(config,spec['source_sha256'],completed,'before',protocol,validation,project);save(out/'prefix-before.json',before)
  start=time.monotonic()
  try:
   with (out/'public-run.stdout.json').open('x') as stream:
    with contextlib.redirect_stdout(stream):code=cli.main(['segmented','run','--config',p['config']['path']])
  finally:result['public_run_wall_seconds']=time.monotonic()-start
  result['public_returncode']=code
  try:public=json.loads((out/'public-run.stdout.json').read_text())
  except (ValueError,OSError) as ex:raise RuntimeError('Public CLI did not provide its structured terminal summary') from ex
  result['public_result']=public
  if code==0 and public.get('status')=='complete' and public.get('execution_complete') is True and public.get('terminal_attempts')==68:
   after=checker.inspect(config,spec['source_sha256'],completed,'after',protocol,validation,project);save(out/'prefix-after.json',after);result['terminal_attempts']=68;result['status']='complete'
  elif public.get('status')=='partial':
   count=public.get('terminal_attempts');need(type(count) is int and completed<=count<68,'Invalid public partial count');result.update(status='partial',terminal_attempts=count,scope='Actual terminal prefix retained; no outcome is replaced or promoted. Explicit resume requires a separate full checkpoint/output/cleanup audit.')
  else:result['status']='controller_failed'
 except BaseException as ex:result.update(status='interrupted' if isinstance(ex,KeyboardInterrupt) else 'controller_failed',error=repr(ex))
 finally:
  with signal_scope(signal.SIG_IGN):
   try:
    post=probe.probe(spec,allowlist_sha256=allowlist_sha,mount_plan_sha256=mount_sha,expected_readonly_prefix=completed);save(out/'post-run-probe.json',post);need(post.get('status')=='passed','Post-run isolation proof failed')
   except BaseException as ex:result.update(status='controller_failed',post_probe_error=repr(ex))
   result['evidence']=[{'path':str(x),'sha256':sha(x),'bytes':x.stat().st_size} for x in sorted(out.iterdir()) if x.is_file()];save(out/'result.json',result)
 return result

def main(argv=None):
 ap=argparse.ArgumentParser();ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--sha256',required=True);ap.add_argument('--allowlist-sha256',required=True);ap.add_argument('--mount-plan-sha256',required=True);ap.add_argument('--expected-completed',type=int,required=True);a=ap.parse_args(argv)
 need(sha(a.plan)==a.sha256,'Inner plan changed');p=json.loads(a.plan.read_text());spec=inspect_plan(p,a.expected_completed)
 probe=module('pinned_inner_namespace_probe',p['probe_helper']['path']);checker=module('pinned_campaign_prefix_checker',p['state_checker']['path'])
 from orbit_poc import cli
 from orbit_poc.segmented import protocol,validation
 from orbit_poc.segmented.config import load_config
 result=execute(p,spec,a.expected_completed,a.allowlist_sha256,a.mount_plan_sha256,probe,checker,cli,load_config(p['config']['path']),protocol,validation)
 print(json.dumps(result,sort_keys=True,allow_nan=False));return 0 if result['status']=='complete' else 2 if result['status']=='partial' else 1
if __name__=='__main__':raise SystemExit(main())
