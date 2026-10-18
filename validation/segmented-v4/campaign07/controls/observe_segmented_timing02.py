#!/usr/bin/env python3
"""Read-only shared-host timing evidence; never signal a process or change affinity."""
from pathlib import Path
import argparse,datetime,hashlib,json,math,os,socket,time,signal

SCHEMA='orbit-poc-segmented-timing-observer-plan-v2'
def need(ok,why):
 if not ok:raise ValueError(why)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def save(path,value):
 p=Path(path);t=p.with_name(p.name+'.writing')
 with t.open('w') as f:json.dump(value,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
 t.replace(p)
def cpu_set(text):
 out=set()
 for item in text.strip().split(','):
  if not item:continue
  lo,sep,hi=item.partition('-');a=int(lo);b=int(hi) if sep else a;need(0<=a<=b,'Invalid CPU range');out.update(range(a,b+1))
 return out

def parse_stat(raw,pid):
 x=raw.rsplit(')',1)[1].split()
 return {'pid':pid,'state':x[0],'parent':int(x[1]),'user_ticks':int(x[11]),'system_ticks':int(x[12]),'start_ticks':int(x[19]),'rss_pages':int(x[21]),'last_processor':int(x[36])}
def native_workload(row):
 args=row.get('argv',[])
 if not args or row['state']=='Z':return False
 first=Path(args[0]).name
 if first.startswith(('groops','cc1','f951','lto1','segmented-qr-')) or first in {'ninja','make','cmake','gcc','g++','cc','c++','gfortran'}:return True
 if any(Path(x).name in {'worker-request.json','build_groops.py'} for x in args):return True
 return any(x.startswith(('orbit_poc.numerics.','orbit_poc.comparison.','orbit_poc.segmented.')) or Path(x).name.startswith(('validate_numerics_','run_comparison_','run_calibration_')) for x in args)

def owned_set(rows,owner,known):
 live={p for p,t in known.items() if p in rows and rows[p]['start_ticks']==t}
 if owner['pid'] in rows and rows[owner['pid']]['start_ticks']==owner['start_ticks']:live.add(owner['pid'])
 while True:
  expanded=live|{p for p,v in rows.items() if v['parent'] in live}
  if expanded==live:break
  live=expanded
 return live

def proc_snapshot(proc=Path('/proc')):
 rows={};errors=[]
 for p in proc.iterdir():
  if not p.name.isdigit():continue
  try:
   v=parse_stat((p/'stat').read_text(),int(p.name));v['argv']=[x.decode(errors='replace') for x in (p/'cmdline').read_bytes().split(b'\0') if x]
   try:v['affinity']=sorted(os.sched_getaffinity(v['pid']))
   except ProcessLookupError:continue
   rows[v['pid']]=v
  except (FileNotFoundError,ProcessLookupError):continue
  except (PermissionError,ValueError,OSError) as ex:errors.append({'pid':int(p.name),'error':repr(ex)})
 return rows,errors

def cpu_snapshot(path=Path('/proc/stat')):
 values={};context=None
 for line in path.read_text().splitlines():
  fields=line.split()
  if fields and fields[0].startswith('cpu') and fields[0][3:].isdigit():values[int(fields[0][3:])]=list(map(int,fields[1:]))
  if fields and fields[0]=='ctxt':context=int(fields[1])
 return values,context

def delta_cpu(previous,current):
 need(len(previous)>=8 and len(current)>=8,'Incomplete CPU counters')
 delta=[b-a for a,b in zip(previous[:8],current[:8])]
 need(all(x>=0 for x in delta),'CPU counter regressed')
 total=sum(delta);idle=delta[3]+delta[4]
 return {'ticks':delta,'total_ticks':total,'busy_fraction':None if total==0 else (total-idle)/total,'idle_fraction':None if total==0 else idle/total,'iowait_fraction':None if total==0 else delta[4]/total,'steal_fraction':None if total==0 else delta[7]/total}

def classify(rows,previous,owner,known,targets,max_details):
 owned=owned_set(rows,owner,known);conflicts=[];active=[];native=[]
 for pid,v in rows.items():
  old=previous.get(pid);ticks=None if not old or old['start_ticks']!=v['start_ticks'] else v['user_ticks']+v['system_ticks']-old['user_ticks']-old['system_ticks']
  r={**v,'owned':pid in owned,'cpu_ticks_since_previous_sample':ticks,'last_processor_is_observed_cpu':v['last_processor'] in targets}
  if native_workload(v):
   native.append(r)
   if pid not in owned:conflicts.append(r)
  if ticks is not None and ticks>0:active.append(r)
 active.sort(key=lambda x:(-x['cpu_ticks_since_previous_sample'],x['pid']))
 return {'known_native_workloads':native,'external_known_native_conflicts':conflicts,'active_process_details':active[:max_details],'active_process_details_omitted':max(0,len(active)-max_details),'owned_processes':len(owned),'owned_rss_sum_bytes':sum(max(0,rows[p]['rss_pages'])*os.sysconf('SC_PAGE_SIZE') for p in owned),'known':{p:rows[p]['start_ticks'] for p in owned}}

def validate_plan(p):
 required={'schema','host','owner','fit_cpu','sibling_cpus','observer_cpu','cadence_seconds','maximum_seconds','maximum_active_process_details','output_root','stop_file'}
 need(set(p)==required and p['schema']==SCHEMA,'Unknown or missing observer option')
 need(set(p['host'])=={'hostname','boot_id'} and set(p['owner'])=={'pid','start_ticks'},'Invalid host/owner identity')
 need(all(type(x) is int and x>=0 for x in [p['fit_cpu'],p['observer_cpu'],*p['sibling_cpus']]),'Invalid CPU identifiers')
 need(len(set(p['sibling_cpus']))==len(p['sibling_cpus']) and p['fit_cpu'] not in p['sibling_cpus'],'Duplicate or self sibling')
 need(p['observer_cpu'] not in {p['fit_cpu'],*p['sibling_cpus']},'Observer must run outside measured physical core')
 need(type(p['cadence_seconds']) in (int,float) and math.isfinite(p['cadence_seconds']) and 2<=p['cadence_seconds']<=30,'Invalid cadence')
 need(type(p['maximum_seconds']) is int and 1<=p['maximum_seconds']<=7*86400,'Invalid outer observation bound')
 need(type(p['maximum_active_process_details']) is int and 1<=p['maximum_active_process_details']<=256,'Invalid detail bound')
 need(all(type(p['owner'][k]) is int and p['owner'][k]>0 for k in p['owner']),'Invalid owned process identity')
 out=Path(p['output_root']);stop=Path(p['stop_file']);need(out.is_absolute() and stop.is_absolute() and stop==out/'stop','Unexpected output/stop layout')
 return p

def verify_host(p):
 need(p['host']=={'hostname':socket.gethostname(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()},'Host or boot changed')
 need(set(os.sched_getaffinity(0))=={p['observer_cpu']},'Observer must already be pinned to its separate CPU')
 topology=Path('/sys/devices/system/cpu')/('cpu'+str(p['fit_cpu']))/'topology/thread_siblings_list'
 siblings=cpu_set(topology.read_text());need(siblings=={p['fit_cpu'],*p['sibling_cpus']},'Physical sibling topology differs')
 return {'thread_siblings_list':{'path':str(topology),'value':topology.read_text().strip()},'observer_affinity':sorted(os.sched_getaffinity(0)),'logical_cpu_count':os.cpu_count()}

def optional_text(path):
 try:return {'path':str(path),'text':Path(path).read_text()}
 except OSError as e:return {'path':str(path),'error':repr(e)}

def observe(plan_path,plan_sha):
 plan_path=Path(plan_path);need(sha(plan_path)==plan_sha,'Observer plan changed');p=validate_plan(json.loads(plan_path.read_text()));topology=verify_host(p);out=Path(p['output_root']);need(not out.exists() and not out.is_symlink(),'Preserve observer output');out.mkdir(parents=True)
 journal={'schema':'orbit-poc-segmented-timing-observation-v2','status':'running','plan':{'path':str(plan_path),'sha256':plan_sha},'helper':{'path':str(Path(__file__).resolve()),'sha256':sha(__file__)},'host':p['host'],'owner':p['owner'],'topology':topology,'started_at':stamp(),'measurement_limits':['Cooperative host lock and affinity; no administrator-exclusive core reservation.','Aggregate per-CPU ticks measure activity; process last_processor is only the last observed CPU, not a per-CPU runtime attribution.','Process-level counters/affinity and main-thread last_processor are sampled; no per-thread runtime attribution is claimed.','Active-process details are explicitly bounded; every detected known native conflict is retained.','Observer runs on a separate CPU and shares host memory/I/O; its measured sampling cost is reported.','RSS sum double-counts shared pages and does not replace the frozen per-job8GiB process-tree resource guard.'],'samples':0,'native_conflict_seen':False,'sampling_incomplete_seen':False};save(out/'summary.json',journal)
 previous={};previous_cpu=None;previous_context=None;known={p['owner']['pid']:p['owner']['start_ticks']};start=time.monotonic();process_start=time.process_time();targets={p['fit_cpu'],*p['sibling_cpus']};total_cpu=0.0;total_wall=0.0;next_sample=start
 try:
  with (out/'samples.jsonl').open('x') as stream:
   while True:
    now=time.monotonic()
    if now-start>=p['maximum_seconds']:journal['status']='observation_deadline';break
    if Path(p['stop_file']).exists():journal['status']='stopped_by_owner';break
    sample_start=time.monotonic();cpu_start=time.process_time();verify_host(p);rows,errors=proc_snapshot();cpus,ctxt=cpu_snapshot();need(targets<=set(cpus),'Missing observed CPU counters');owner=rows.get(p['owner']['pid'])
    if owner is None or owner['start_ticks']!=p['owner']['start_ticks']:journal['status']='owner_finished_or_identity_changed';break
    classified=classify(rows,previous,p['owner'],known,targets,p['maximum_active_process_details']);known=classified.pop('known')
    sample={'utc':stamp(),'monotonic_seconds':sample_start,'seconds_since_start':sample_start-start,'cpu_counters':{str(k):cpus[k] for k in sorted(targets)},'cpu_deltas':None if previous_cpu is None else {str(k):delta_cpu(previous_cpu[k],cpus[k]) for k in sorted(targets)},'system_context_switches':ctxt,'system_context_switch_delta':None if previous_context is None else ctxt-previous_context,'process_read_errors':errors,'pressure_cpu':optional_text('/proc/pressure/cpu'),'loadavg':optional_text('/proc/loadavg'),**classified}
    sample['observer_cpu_seconds']=time.process_time()-cpu_start;sample['sampling_wall_seconds']=time.monotonic()-sample_start;total_cpu+=sample['observer_cpu_seconds'];total_wall+=sample['sampling_wall_seconds'];stream.write(json.dumps(sample,sort_keys=True,allow_nan=False)+'\n');stream.flush()
    journal['samples']+=1;journal['native_conflict_seen']|=bool(classified['external_known_native_conflicts']);journal['sampling_incomplete_seen']=journal.get('sampling_incomplete_seen',False) or bool(errors)
    latest={'schema':'orbit-poc-segmented-timing-guard-v2','plan_sha256':plan_sha,'observed_at':sample['utc'],'monotonic_seconds':sample_start,'owner':p['owner'],'native_conflicts':classified['external_known_native_conflicts'],'process_read_errors':errors,'native_conflict_seen':journal['native_conflict_seen'],'sampling_incomplete_seen':journal['sampling_incomplete_seen'],'status':'conflict' if journal['native_conflict_seen'] else ('incomplete' if journal['sampling_incomplete_seen'] else 'clear')};save(out/'latest.json',latest)
    previous=rows;previous_cpu=cpus;previous_context=ctxt;next_sample+=p['cadence_seconds'];time.sleep(max(0,next_sample-time.monotonic()))
 except BaseException as ex:journal['status']='observer_failed';journal['error']=repr(ex);raise
 finally:
  journal.update(ended_at=stamp(),elapsed_seconds=time.monotonic()-start,total_observer_process_cpu_seconds=time.process_time()-process_start,sampling_cpu_seconds=total_cpu,sampling_wall_seconds=total_wall,sampling_measurement_scope='Per-sample collection before JSON serialization; total process CPU includes bookkeeping and writes');save(out/'summary.json',journal)
 return journal

def require_clear(latest,p,plan_sha,now):
 need(latest.get('schema')=='orbit-poc-segmented-timing-guard-v2' and latest.get('plan_sha256')==plan_sha and latest.get('owner')==p['owner'],'Timing guard attribution differs')
 age=now-latest['monotonic_seconds'];need(0<=age<=max(15,3*p['cadence_seconds']),'Timing observer stale or clock regressed')
 need(latest.get('status')=='clear' and latest.get('native_conflict_seen') is False and latest.get('sampling_incomplete_seen') is False and latest.get('native_conflicts')==[] and latest.get('process_read_errors')==[],'Timing native-conflict guard is not clear')
 return True

def interrupted(number,_frame):raise KeyboardInterrupt('Observer interrupted by signal '+str(number))

if __name__=='__main__':
 for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,interrupted)
 ap=argparse.ArgumentParser();ap.add_argument('--plan',required=True);ap.add_argument('--sha256',required=True);a=ap.parse_args();print(json.dumps(observe(a.plan,a.sha256)))
