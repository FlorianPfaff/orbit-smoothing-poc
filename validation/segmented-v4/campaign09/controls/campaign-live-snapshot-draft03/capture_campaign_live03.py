#!/usr/bin/env python3
"""Read-only one-shot campaign capture. No signals, locks, affinity changes or services."""
from pathlib import Path
import argparse,collections,datetime,hashlib,importlib.util,json,os,socket

ENV_KEYS={'HOME','OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'}
OBSERVER_SHA='31707b24977fe7d8884c402dcf478253ae99e7d56fecfb22b692312f92a1405e'
MANIFEST_SHA='4877f929be8a9eda5d58ff6b4eb0e0fc8b84ea16934a6fbe63fa5a18418fa5c6'
MANIFEST_HASH='63f3010564c6da76c0f92a007ed1fbe057d610d44cccb6b5e4f509afafbf2251'
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff')
CONTROL=B/'fit-campaign-control-09'
RUN=B/'validation-07/run'
TEMP=B/'validation-07/temporary/fit-private'

def need(v,why):
 if not v:raise ValueError(why)
def sha(b):return hashlib.sha256(b).hexdigest()
def json_file(p,required=False,maximum=12*1024**2):
 p=Path(p)
 try:
  need(p.is_file() and not p.is_symlink(),'Nonregular receipt: '+str(p))
  need(p.stat().st_size<=maximum,'Receipt exceeds capture bound: '+str(p))
  raw=p.read_bytes();need(len(raw)<=maximum,'Receipt grew beyond capture bound')
  return {'path':str(p),'sha256':sha(raw),'bytes':len(raw),'content':json.loads(raw)}
 except FileNotFoundError:
  if required:raise
  return {'path':str(p),'present':False}
 except ValueError as error:
  if not p.exists() and not required:return {'path':str(p),'present':False}
  raise error
def pin_only(receipt):return {k:v for k,v in receipt.items() if k!='content'}
def filtered_environment(raw):
 return {k:v for part in raw.split(b'\0') if b'=' in part for key,value in [part.split(b'=',1)]
         for k,v in [(key.decode(errors='replace'),value.decode(errors='replace'))] if k in ENV_KEYS}
def lock_records(raw,device,inode):
 rows=[]
 for line in raw.splitlines():
  words=line.split()
  for i,word in enumerate(words):
   parts=word.split(':')
   if len(parts)!=3:continue
   try:matches=(int(parts[0],16),int(parts[1],16),int(parts[2]))==(os.major(device),os.minor(device),inode)
   except ValueError:continue
   if matches:
    rows.append({'line':line,'owner_pid':int(words[i-1]),'waiting':'->' in words})
    break
 return rows
def live_identity(row):
 return row is not None and row.get('state')!='Z'
def same_identity(row,wanted):
 return row is not None and row['pid']==wanted['pid'] and row['start_ticks']==wanted['start_ticks']

def collect(plan_sha):
 st=CONTROL.stat();need((st.st_dev,st.st_ino)==(2048,239602719),'Host control replaced')
 hp=json_file(CONTROL/'host-plan.json',True);need(hp['sha256']==plan_sha,'Host plan changed');plan=hp['content']
 need(plan['control_root']==str(CONTROL),'Unexpected control root')
 observer=Path(plan['observer']['path']);need(sha(observer.read_bytes())==plan['observer']['sha256']==OBSERVER_SHA,'Observer source changed')
 spec=importlib.util.spec_from_file_location('reviewed_one_shot_process_reader',observer);o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o)
 launch=json_file(CONTROL/'campaign-launch.json',True);pipeline=json_file(CONTROL/'pipeline.json')
 manifest=json_file(RUN/'manifest.json',True);need(manifest['sha256']==MANIFEST_SHA and manifest['content']['manifest_hash']==MANIFEST_HASH,'Frozen manifest changed')
 owner=launch['content']['driver_process'];boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
 need(owner['boot_id']==boot and plan['host']=={'hostname':socket.gethostname(),'boot_id':boot},'Launch belongs to another host/boot')
 rows,errors=o.proc_snapshot();known={owner['pid']:owner['start_ticks']}
 journal=pipeline.get('content',{});work=journal.get('workload',{}).get('process')
 if isinstance(work,dict):known[work['pid']]=work['start_ticks']
 owned=o.owned_set(rows,owner,known);processes=[]
 for pid in sorted(owned):
  r=rows[pid];p=Path('/proc')/str(pid);entry={k:r[k] for k in ('pid','start_ticks','parent','state','affinity','last_processor','user_ticks','system_ticks','rss_pages')}
  argv=r.get('argv',[]);entry.update(command_sha256=sha(b'\0'.join(x.encode() for x in argv)+b'\0'),argv=argv,native_workload=o.native_workload(r))
  try:
   entry['selected_environment']=filtered_environment((p/'environ').read_bytes())
   entry['executable']=os.readlink(p/'exe')
   st=(p/'exe').stat();entry['executable_identity']={'device':st.st_dev,'inode':st.st_ino,'bytes':st.st_size}
   entry['namespaces']={k:os.readlink(p/'ns'/k) for k in ('pid','mnt','net')}
   end=o.parse_stat((p/'stat').read_text(),pid)
   need(same_identity(end,r),'PID/start changed during process capture')
  except (FileNotFoundError,ProcessLookupError):entry['capture_race']='process exited during capture';entry.pop('selected_environment',None)
  except (OSError,ValueError) as error:entry['capture_error']=repr(error);entry.pop('selected_environment',None)
  processes.append(entry)
 attempts=[];counts=collections.Counter();active=[]
 for a in manifest['content']['attempts']:
  directory=RUN/'attempts'/a['attempt_id'];rec=json_file(directory/'result-record.json')
  row={**a,'directory_present':directory.is_dir()}
  if 'content' in rec:
   v=rec['content'];need(v['attempt_id']==a['attempt_id'],'Attempt receipt identity differs')
   row.update(state='terminal_record_present',status=v['status'],record={k:rec[k] for k in ('path','sha256','bytes')},result=v['result']);counts[v['status']]+=1
  elif directory.exists():
   row.update(state='started_without_terminal_record',request=pin_only(json_file(directory/'request.json')),supervisor=json_file(directory/'supervisor.json'))
   active.append(a['attempt_id'])
  else:row['state']='not_started'
  attempts.append(row)
 prefix=0
 for a in attempts:
  if a['state']!='terminal_record_present':break
  prefix+=1
 locktext=Path('/proc/locks').read_text();locks=[]
 for p in (Path(plan['global_lock']),RUN/'.segmented.lock',CONTROL/'controller.lock'):
  if not p.exists():locks.append({'path':str(p),'present':False});continue
  s=p.stat();holders=lock_records(locktext,s.st_dev,s.st_ino)
  for v in holders:
   pr=rows.get(v['owner_pid']);v['owner_start_ticks']=None if pr is None else pr['start_ticks'];v['owned_at_snapshot']=v['owner_pid'] in owned
  locks.append({'path':str(p),'device':s.st_dev,'inode':s.st_ino,'bytes':s.st_size,'kernel_locks':holders})
 proof=json_file(TEMP/'campaign-control/prelaunch-probe.json')
 return {'schema':'orbit-poc-campaign-live-readonly-snapshot-v1','captured_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'host':plan['host'],'host_control':{'path':str(CONTROL),'device':2048,'inode':239602719},
  'host_plan':{k:hp[k] for k in ('path','sha256','bytes')},'launch':launch,'pipeline':pipeline,'prelaunch_probe':proof,'prefix_before':json_file(TEMP/'campaign-control/prefix-before.json'),
  'observer_latest':json_file(CONTROL/'observer/latest.json'),'manifest':{k:manifest[k] for k in ('path','sha256','bytes')},'manifest_hash':MANIFEST_HASH,
  'driver_identity_matches':same_identity(rows.get(owner['pid']),owner),'driver_live':same_identity(rows.get(owner['pid']),owner) and live_identity(rows.get(owner['pid'])),
  'owned_processes':processes,'process_visibility_errors':errors,'locks':locks,'terminal_count':sum(counts.values()),'terminal_prefix':prefix,'terminal_status_counts':dict(counts),'current_nonterminal_attempt_ids':active,'attempts':attempts,
  'expected_native_pins':{k:manifest['content']['runtimes'][k]['native'] for k in ('dense','segmented')},'native_processes':[r for r in processes if r['native_workload']],
  'notes':['One non-atomic read-only snapshot; transient process/file races are explicit.','Only HOME and the four known numerical-thread variables are captured from owned processes.','Executable device/inode/path are observed; executable bytes are not rehashed during the timed fit. Expected native hashes come from the frozen manifest.','Terminal record presence/status is not an independent scientific audit or release certification.','No new observer/service, native workload, lock acquisition, signal or process-affinity change is performed.']}
def main():
 p=argparse.ArgumentParser();p.add_argument('--host-plan-sha256',required=True);a=p.parse_args()
 need(len(a.host_plan_sha256)==64,'Exact actual host plan SHA required')
 print(json.dumps(collect(a.host_plan_sha256),indent=2,sort_keys=True,allow_nan=False))
if __name__=='__main__':main()
