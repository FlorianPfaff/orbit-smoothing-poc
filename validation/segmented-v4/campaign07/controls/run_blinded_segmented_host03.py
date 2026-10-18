#!/usr/bin/env python3
"""Own one blind campaign and continuously check its shared-host admission."""
from pathlib import Path
import argparse,contextlib,fcntl,hashlib,importlib.util,json,os,shutil,signal,socket,sys,time
PINS={'helper','driver','wrapper','invocation','observer','observer_owner','control_python','taskset','config','validation_audit','shifted_audit','preparation_controller'}
KEYS=PINS|{'schema','host','global_lock','control_root','maximum_seconds','minimum_free_bytes','fit_cpu','sibling_cpus','observer_cpu','cadence_seconds'}
SIGNALS=(signal.SIGINT,signal.SIGTERM,signal.SIGHUP)
def need(ok,why):
 if not ok:raise RuntimeError(why)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def checked(p):
 need(isinstance(p,dict) and set(p)=={'path','sha256'} and Path(p['path']).is_absolute() and sha(p['path'])==p['sha256'],'Changed exact host artifact')
def read(p):checked(p);return json.loads(Path(p['path']).read_text())
def pin(p):return {'path':str(p),'sha256':sha(p)}
def canonical(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def same_pin(a,b):return isinstance(a,dict) and isinstance(b,dict) and all(a.get(k)==b.get(k) for k in ('path','sha256'))
def module(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
@contextlib.contextmanager
def signals(handler):
 previous={n:signal.getsignal(n) for n in SIGNALS}
 try:
  for n in SIGNALS:signal.signal(n,handler)
  yield
 finally:
  for n,h in previous.items():signal.signal(n,h)
def interrupted(n,_):raise KeyboardInterrupt('Host controller interrupted by signal '+str(n))
def load_plan(path,digest):
 need(sha(path)==digest,'Host plan changed');p=json.loads(Path(path).read_text());need(set(p)==KEYS and p['schema']=='orbit-poc-segmented-blind-host-plan-v1','Wrong host plan')
 for k in PINS:checked(p[k])
 need(p['helper']['sha256']==sha(__file__),'Host controller changed')
 need(p['fit_cpu']==24 and p['sibling_cpus']==[88] and p['observer_cpu']==32 and p['cadence_seconds']==2,'Frozen fit/observer allocation differs')
 need(p['maximum_seconds']==604800 and p['minimum_free_bytes']==34359738368,'Outer bound/free-space policy differs')
 need(set(p['host'])=={'hostname','boot_id'} and all(Path(p[k]).is_absolute() for k in ('global_lock','control_root')),'Invalid host/control paths')
 cfg=read(p['config']);resources=cfg['resources'];need(resources['reserved_cpu_ids']==[24] and resources['threads']==1 and resources['maximum_process_tree_rss_bytes']==8589934592 and resources['minimum_free_output_bytes']==p['minimum_free_bytes'],'Frozen numerical resources differ')
 v=read(p['validation_audit']);s=read(p['shifted_audit'])
 for audit,schema in [(v,'orbit-poc-segmented-validation-terminal-independent-review-v1'),(s,'orbit-poc-shifted-cut-terminal-independent-review-v1')]:
  need(audit['schema']==schema and audit['consistency_passed'] is True and audit['scientific_status']=='passed_scoped_checks' and audit['cleanup_verified'] is True,'Required independent audit not a scoped clean pass')
  ident=audit['identity'];need(ident['comparison_source_sha256']==cfg['segmented_runtime']['source_sha256']==cfg['dense_runtime']['source_sha256'] and ident['native_sha256']==cfg['segmented_runtime']['native']['sha256'] and ident['solver_sha256']==cfg['segmented_runtime']['segmented_solver']['sha256'],'Audit source/native/solver identity differs')
  ap=audit['artifacts']['config'];need(ap['path']==p['config']['path'] and ap['sha256']==p['config']['sha256'],'Audited config differs')
 prep=read(p['preparation_controller']);need(prep['schema']=='orbit-poc-segmented-preparation-owned-run-v1' and prep['status']=='prepared' and prep['benchmark_attempts']==0 and prep['final_cleanup']['verified'] is True and prep['final_cleanup']['errors']==[],'Preparation is not complete and clean')
 pp=prep['plan'];checked({k:pp[k] for k in ('path','sha256')});prepplan=json.loads(Path(pp['path']).read_text());need(prepplan['config']==p['config'] and prepplan['global_lock']==p['global_lock'],'Preparation config/serial lock differs')
 need(len(prep['checks'])==2 and [x['phase'] for x in prep['checks']]==['before','after'],'Preparation checks differ')
 after=read(prep['checks'][1]['result']);verify_preparation_result(after,p)
 return p

def verify_preparation_result(after,p):
 cfg=read(p['config']);audit=read(p['validation_audit'])
 need(after['schema']=='orbit-poc-segmented-preparation-state-check-v1' and after['phase']=='after' and after['status']=='passed' and after['config']==p['config'],'Preparation after-check schema/phase/config differs')
 need(after['source_sha256']==cfg['segmented_runtime']['source_sha256'] and after['validation']['status']=='passed' and same_pin(after['validation']['pipeline'],audit['artifacts']['cli_pipeline']),'Preparation source/validation differs from audited gates')
 need(all(after['prepared'][k]==v for k,v in {'cases':28,'attempts':68,'benchmark_fit_count':0}.items()),'Actual prepared inventory differs')
 checked(after['prepared']['manifest'])
 return after

def bind_prepared_context(p,allow,spec):
 prep=read(p['preparation_controller']);after=verify_preparation_result(read(prep['checks'][1]['result']),p)
 need(allow['source_plan']['manifest']==after['prepared']['manifest'],'Invoked allowlist was not built from the actual checked preparation manifest')
 manifest=read(after['prepared']['manifest'])
 need(manifest['manifest_hash']==allow['manifest_hash']==spec['manifest_hash'],'Preparation/allowlist/probe manifest identities differ')
 need(spec['config']==p['config'] and spec['source_sha256']==after['source_sha256'],'Probe config/source differs from preparation')
 return {'manifest':after['prepared']['manifest'],'manifest_hash':manifest['manifest_hash'],'source_sha256':after['source_sha256'],'validation_pipeline':after['validation']['pipeline'],'specification_content_sha256':canonical(spec),'canonical_temporary':spec['writable']['temporary']}

def prepare_invocation(p):
 invocation=read(p['invocation']);need(invocation['wrapper']==p['wrapper'] and invocation['config']==p['config'],'Invocation wrapper/config differs')
 w=module('reviewed_blind_wrapper',p['wrapper']['path']);w.host_pin(invocation['fresh_planner']);fresh=w.module('reviewed_fresh_planner',invocation['fresh_planner']['path']);resume=None
 if invocation['resume_planner'] is not None:w.host_pin(invocation['resume_planner']);resume=w.module('reviewed_resume_planner',invocation['resume_planner']['path'])
 mount=read(invocation['mount_plan']);initial=mount if mount['schema']=='orbit-poc-segmented-fit-mount-plan-v1' else fresh.read(mount['inputs']['inputs']['initial_mount_plan'])
 links={x['path']:x['target'] for x in initial['canonical_symlinks']};name=fresh.links_resolve(invocation['probe_helper']['path'],links);bp=initial['verified_file_backings'][name];need(bp['sha256']==invocation['probe_helper']['sha256'] and sha(bp['path'])==bp['sha256'],'Probe backing differs');probe=w.module('reviewed_probe',bp['path'])
 prepared=w.prepare(invocation,fresh,resume,probe)
 allow=fresh.read(initial['inputs']['allowlist']);name=fresh.links_resolve(invocation['probe_spec']['path'],links);sp=initial['verified_file_backings'][name];need(sp['sha256']==invocation['probe_spec']['sha256'] and sha(sp['path'])==sp['sha256'],'Probe specification backing differs');spec=json.loads(Path(sp['path']).read_text());prepared['attribution']=bind_prepared_context(p,allow,spec)
 writes={x['kind']:x for x in initial['writable_mounts']};need(set(writes)=={'attempts','temporary','lock'},'Writable scope differs')
 backing={'attempts':writes['attempts']['source'],'temporary':writes['temporary']['source']};identities={k:writes[k]['identity'] for k in backing}
 if mount['schema']=='orbit-poc-segmented-fit-resume-mount-plan-v1':identities['temporary']=mount['scratch']['selected_backing'];backing['temporary']=identities['temporary']['path']
 return prepared,backing,identities,invocation

class HostGuard:
 def __init__(self,p,observer,owner,backing,identities):self.p=p;self.observer=observer;self.owner=owner;self.backing=backing;self.identities=identities;self.known={owner['pid']:owner['start_ticks']};self.samples=0;self.minimum_free=None
 def check(self):
  p=self.p;o=self.observer;need(p['host']=={'hostname':socket.gethostname(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()},'Host/boot changed');need(set(os.sched_getaffinity(0))=={32},'Host controller must remain on observerCPU32');need(o.cpu_set(Path('/sys/devices/system/cpu/cpu24/topology/thread_siblings_list').read_text())=={24,88},'CPU topology changed');need({24,88,32}<=o.cpu_set(Path('/sys/devices/system/cpu/online').read_text()),'Required CPUs went offline')
  rows,errors=o.proc_snapshot();need(not errors,'Host process visibility incomplete');owner=rows.get(self.owner['pid']);need(owner is not None and owner['start_ticks']==self.owner['start_ticks'],'Host owner changed');v=o.classify(rows,{},self.owner,self.known,{24,88},1);self.known=v['known'];need(not v['external_known_native_conflicts'],'External known native workload appeared')
  spaces={}
  for k,path in self.backing.items():
   s=Path(path).stat();identity=self.identities[k];need(not Path(path).is_symlink() and s.st_dev==identity['device'] and s.st_ino==identity['inode'],'Writable backing identity changed');free=shutil.disk_usage(path).free;need(free>=p['minimum_free_bytes'],'Actual backing free space below fixed reserve');spaces[k]=free
  self.samples+=1;value=min(spaces.values());self.minimum_free=value if self.minimum_free is None else min(self.minimum_free,value)
  return {'observed_at':o.stamp(),'known_native_conflicts':[],'visibility_errors':[],'backing_free_bytes':spaces,'minimum_observed_backing_free_bytes':self.minimum_free,'checks':self.samples,'affinity':[32],'fit_cpu':24,'sibling_cpus':[88],'reservation':'Shared host; cooperative lock and affinity. No exclusive-core reservation claimed.'}

def inspect_inner(result,prepared,p,temporary):
 need(result['schema']=='orbit-poc-segmented-blind-inner-campaign-result-v2' and result['config']==p['config'] and result['starting_terminal_prefix']==prepared['prefix'] and result['expected_attempts']==68 and result['allowlist_sha256']==prepared['allowlist_sha256'] and result['mount_plan_sha256']==prepared['mount_plan_sha256'],'Inner campaign attribution differs')
 need(result['source_sha256']==prepared['attribution']['source_sha256'],'Inner source differs');need(result['status'] in {'complete','partial','interrupted','controller_failed'},'Unknown inner status')
 if result['status']=='complete':need(result['terminal_attempts']==68 and result['public_returncode']==0 and result['public_result'].get('execution_complete') is True and result['public_result'].get('terminal_attempts')==68,'Complete inner inventory differs')
 if result['status']=='partial':need(type(result['terminal_attempts']) is int and prepared['prefix']<=result['terminal_attempts']<68,'Partial count differs')
 directory=Path(temporary)/'campaign-control';seen=set()
 for row in result['evidence']:
  name=Path(row['path']).name;need(row['path']==str(Path(prepared['attribution']['canonical_temporary'])/'campaign-control'/name),'Inner evidence canonical parent differs');need(name not in seen and name!='result.json','Duplicate or self-referential inner evidence');seen.add(name);file=directory/name;need(file.is_file() and not file.is_symlink() and sha(file)==row['sha256'] and file.stat().st_size==row['bytes'],'Inner evidence changed')
 need({'prelaunch-probe.json','prefix-before.json','post-run-probe.json'}<=seen,'Inner pre/post evidence missing')
 attr=prepared['attribution'];expected={'allowlist_sha256':prepared['allowlist_sha256'],'mount_plan_sha256':prepared['mount_plan_sha256'],'expected_completed':prepared['prefix']}
 for name in ('prelaunch-probe.json','post-run-probe.json'):
  proof=json.loads((directory/name).read_text());need(proof.get('schema')=='orbit-poc-segmented-fit-inner-probe-result-v1' and proof.get('status')=='passed','Namespace proof absent or failed');need(proof['host_verified_final_artifacts']==expected and proof['specification_content_sha256']==attr['specification_content_sha256'],'Namespace proof final identities differ');pub=proof['public_readonly_checks'];need(pub['manifest_hash']==attr['manifest_hash'] and pub['validation']['status']=='passed' and same_pin(pub['validation']['pipeline'],attr['validation_pipeline']),'Namespace proof uses another manifest/validation')
 before=json.loads((directory/'prefix-before.json').read_text());need(before['status']=='passed' and before['phase']=='before' and before['terminal_attempts']==prepared['prefix'],'Starting prefix proof differs')
 verify_prefix_identity(before,attr)
 if result['status']=='complete':
  need('prefix-after.json' in seen,'Completed prefix proof missing');after=json.loads((directory/'prefix-after.json').read_text());need(after['status']=='passed' and after['phase']=='after' and after['terminal_attempts']==68,'Completed prefix proof differs');verify_prefix_identity(after,attr)
 return result['status']

def verify_prefix_identity(value,attr):
 need(value['schema']=='orbit-poc-segmented-fit-state-check-v2' and value['manifest_hash']==attr['manifest_hash'] and value['validation']['status']=='passed' and same_pin(value['validation']['pipeline'],attr['validation_pipeline']),'Prefix source/manifest/audited-validation context differs')

def preserve_inner_evidence(temporary,d):
 """Inventory available terminal/interruption evidence without promoting it."""
 root=Path(temporary)/'campaign-control'
 if not root.exists():return {'present':False,'status_promoted':False,'files':[]}
 need(root.is_dir() and not root.is_symlink(),'Inner evidence root is not an ordinary directory')
 rows=[]
 for path in sorted(root.iterdir()):
  need(path.is_file() and not path.is_symlink(),'Unexpected inner evidence member')
  rows.append(d.artifact(path))
 return {'present':True,'status_promoted':False,'files':rows}

def live_guard(child,latest,observer,plan,plan_sha,guard,now):
 need(child.poll() is None,'Timing observer exited during campaign');observer.require_clear(latest,plan,plan_sha,now);return guard.check()

def observer_complete(cleanup,summary):
 need(cleanup['verified'] is True and cleanup['returncode']==0 and cleanup['stop_errors']==[],'Observer stop failed')
 need(summary['status']=='stopped_by_owner' and summary['native_conflict_seen'] is False and summary['sampling_incomplete_seen'] is False,'Observer recorded a persistent violation or failure')
 return True

def main(argv=None):
 ap=argparse.ArgumentParser();ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--sha256',required=True);a=ap.parse_args(argv);p=load_plan(a.plan,a.sha256);need(sha(Path(sys.executable).resolve())==p['control_python']['sha256'],'Control interpreter changed');control=Path(p['control_root']);need(control.is_dir() and not control.is_symlink() and not (control/'pipeline.json').exists(),'Fresh host control journal required');registry=[];observer_child=None;journal={};backing=None
 d=module('frozen_owned_driver',p['driver']['path']);observer=module('reviewed_timing_observer',p['observer']['path']);owner_module=module('reviewed_owned_observer',p['observer_owner']['path'])
 def save():d.save(control/'pipeline.json',journal)
 with Path(p['global_lock']).open('a') as lock,(control/'controller.lock').open('a') as local,signals(interrupted):
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(local,fcntl.LOCK_EX|fcntl.LOCK_NB);start=time.monotonic();cpu_start=time.process_time()
  journal={'schema':'orbit-poc-segmented-blind-host-run-v3','status':'starting','plan':d.artifact(a.plan),'started_at':d.stamp(),'shared_host_timing':True,'exclusive_core_claim':False,'scientific_success_inferred':False,'timing_scope':'Outer verification, observation and postchecks recorded separately. Public per-fit time retains all original work including dense rank certification.'};save()
  try:
   prepared,backing,identities,invocation=prepare_invocation(p);identity=owner_module.identity(os.getpid());owner={k:identity[k] for k in ('pid','start_ticks')};guard=HostGuard(p,observer,owner,backing,identities);journal['admission']=guard.check();journal['starting_terminal_prefix']=prepared['prefix']
   op={'schema':observer.SCHEMA,'host':p['host'],'owner':owner,'fit_cpu':24,'sibling_cpus':[88],'observer_cpu':32,'cadence_seconds':2,'maximum_seconds':604800,'maximum_active_process_details':64,'output_root':str(control/'observer'),'stop_file':str(control/'observer/stop')};observer.validate_plan(op);d.save(control/'observer-plan.json',op);oph=sha(control/'observer-plan.json');journal['observer_plan']=d.artifact(control/'observer-plan.json');save()
   env={'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1','HOME':str(control)}
   with (control/'observer.log').open('x') as observerlog:
    observer_child=owner_module.OwnedObserver([p['taskset']['path'],'-c','32',p['control_python']['path'],'-B',p['observer']['path'],'--plan',str(control/'observer-plan.json'),'--sha256',oph],cwd=control,env=env,log=observerlog);journal['observer_identity']=observer_child.initial;save()
    latest=control/'observer/latest.json';deadline=time.monotonic()+30
    while not latest.exists():
     need(observer_child.poll() is None,'Observer exited before readiness');guard.check();need(time.monotonic()<deadline,'Observer readiness timeout');time.sleep(.1)
    def live():
     journal['last_host_guard']=live_guard(observer_child,json.loads(latest.read_text()),observer,op,oph,guard,time.monotonic())
    live();journal['startup_seconds']=time.monotonic()-start;journal['status']='running';save();command=[p['control_python']['path'],'-B',p['wrapper']['path'],'--invocation',p['invocation']['path'],'--sha256',p['invocation']['sha256']];journal['argv']=command;work={};journal['workload']=work;save()
    def started(pid):work['process']=d.proc(pid);save()
    def finished(value):work.update(value);save()
    with (control/'workload.log').open('x') as log:code=d.supervise(command,cwd=control,env=env,log=log,limit=p['maximum_seconds'],guard_live=live,on_started=started,on_finished=finished,registry=registry,poll_seconds=2)
    work['returncode']=code;live();result=Path(backing['temporary'])/'campaign-control/result.json';journal['inner_result']=d.artifact(result);value=json.loads(result.read_text());status=inspect_inner(value,prepared,p,backing['temporary']);journal['status']=status if (code==0 and status=='complete') or (code==2 and status=='partial') else 'controller_failed';journal['terminal_attempts']=value.get('terminal_attempts');save()
   for k in PINS:checked(p[k])
  except BaseException as ex:journal.update(status='interrupted' if isinstance(ex,KeyboardInterrupt) else 'controller_failed',error=repr(ex))
  finally:
   with signals(signal.SIG_IGN):
    errors=[]
    for child in registry:
     try:child.cleanup(force=child.child.poll() is None)
     except BaseException as ex:errors.append(repr(ex))
    if backing is not None:
     try:journal['preserved_inner_evidence']=preserve_inner_evidence(backing['temporary'],d)
     except BaseException as ex:journal['inner_evidence_inventory_error']=repr(ex);errors.append(repr(ex))
    if observer_child is not None:
     try:
      cleanup=observer_child.stop(control/'observer/stop');journal['observer_cleanup']=cleanup;summary=json.loads((control/'observer/summary.json').read_text());journal['observer_summary']=d.artifact(control/'observer/summary.json');observer_complete(cleanup,summary)
     except BaseException as ex:errors.append(repr(ex))
    journal['final_cleanup']={'verified':not errors,'errors':errors,'commands':[x.last_cleanup for x in registry]};journal['finished_at']=d.stamp();journal['outer_elapsed_seconds']=time.monotonic()-start;journal['outer_process_cpu_seconds']=time.process_time()-cpu_start
    if errors:journal['status']='controller_failed'
    save()
 return 0 if journal['status']=='complete' else 2 if journal['status']=='partial' else 1
if __name__=='__main__':raise SystemExit(main())
