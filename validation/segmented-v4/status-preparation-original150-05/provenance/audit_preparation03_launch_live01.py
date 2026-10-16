from pathlib import Path
import datetime,hashlib,json,os
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');C=B/'preparation-03/control'
def pin(p):return {'path':str(p),'sha256':hashlib.sha256(Path(p).read_bytes()).hexdigest()}
def proc(pid):
 p=Path('/proc')/str(pid);f=(p/'stat').read_text().rsplit(')',1)[1].split();raw=(p/'cmdline').read_bytes()
 return {'pid':pid,'parent':int(f[1]),'start_ticks':int(f[19]),'state':f[0],'argv':[x.decode() for x in raw.split(b'\0') if x],'command_sha256':hashlib.sha256(raw).hexdigest(),'affinity':sorted(os.sched_getaffinity(pid)),'pid_namespace':os.readlink(p/'ns/pid')}
lp=C/'preparation-launch.json'
l=json.loads(lp.read_text());praw=(C/'pipeline.json').read_bytes();p=json.loads(praw);pp=C/'plan.json';assert pin(pp)['sha256']=='99579b42e6bb743b6bba16da9da12ef04e568fa18b920af03231f6aca4d7de83';plan=json.loads(pp.read_text())
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();assert boot==l['driver_process']['boot_id']==p['admission']['boot_id']=='95156dd4-0d4c-499d-a214-8883a2d650fa'
assert l['launch_committed'] is True and l['observed_argv']==l['argv'] and l['launch_helper_sha256']=='671e177ba7309f18c2b5a0914f75e389d6500b03b7989e85190c75410144e014'
assert l['execution_sha256']==plan['execution']['sha256']=='d2297c51648d9ba1f3644cbdae36ba5a95ad289d941ec4823aca6817af923236'
assert p['plan']['path']==str(pp) and p['plan']['sha256']==pin(pp)['sha256']
assert p['admission']['status']=='admitted' and p['admission']['conflicting_processes']==[] and p['status']=='running' and p['benchmark_attempts']==0 and p['release_ready'] is False
driver=proc(2414723);assert driver['start_ticks']==111523164 and driver['parent']==1 and driver['argv']==l['argv'] and driver['command_sha256']==l['command_sha256']==p['admission']['driver_identity']['command_sha256']
lock=Path(plan['global_lock']);stat=lock.stat();assert stat.st_ino==217252784
held=[]
for f in (Path('/proc')/str(driver['pid'])/'fd').iterdir():
 try:st=f.stat()
 except FileNotFoundError:continue
 if (st.st_dev,st.st_ino)==(stat.st_dev,stat.st_ino):held.append({'fd':int(f.name),'target':os.readlink(f)})
assert held
locklines=[]
for line in Path('/proc/locks').read_text().splitlines():
 fields=line.split()
 if len(fields)>6 and fields[4]==str(driver['pid']) and fields[5].split(':')[-1]==str(stat.st_ino):locklines.append(line)
assert len(locklines)==1 and ' FLOCK  ADVISORY  WRITE ' in locklines[0]
owned=[];front={driver['pid']}
for _ in range(8):
 nxt=set()
 for path in Path('/proc').iterdir():
  if not path.name.isdecimal():continue
  try:x=proc(int(path.name))
  except (FileNotFoundError,ProcessLookupError,PermissionError):continue
  if x['parent'] in front:owned.append(x);nxt.add(x['pid'])
 if not nxt:break
 front=nxt
active=[]
for x in owned:
 if len(x['argv'])>1 and (x['argv'][1].endswith('check_preparation_state01.py') or x['argv'][1].endswith('run_segmented_preparation.py')):
  assert x['affinity']==[24]
  active.append(x)
assert active
mounts={}
for x in active:
 rows=[]
 for line in (Path('/proc')/str(x['pid'])/'mountinfo').read_text().splitlines():
  fields=line.split();target=fields[4]
  if target in [str(B/'validation-04'/z) for z in ('source','native-source','cache','binaries','run','temporary')]+[str(C),'/dev']:rows.append(line)
 mounts[str(x['pid'])]=rows
assert l['pins_sha256']=='62b25e801759673a149b324cf649e5290c798a97f52193061a18ceb53817eba4'
assert l['driver_process']=={'pid':2414723,'start_ticks':111523164,'boot_id':boot}
print(json.dumps({'schema':'orbit-poc-preparation-live-launch-independent-review-v1','passed':True,'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'launch':pin(lp),'plan':pin(pp),'pipeline_snapshot':p,'pipeline_snapshot_sha256':hashlib.sha256(praw).hexdigest(),'live_driver':driver,'live_owned_descendants':owned,'global_lock':{'path':str(lock),'device':stat.st_dev,'inode':stat.st_ino,'held_fds':held,'proc_locks':locklines},'active_worker_selected_mounts':mounts,'boot_id':boot,'scope':'Actual detached preparation03 is live, owned and admitted under the exact plan and unchanged global exclusive lock. This is preparation/checking, not completion or any of the 68 fit attempts. No runtime rescan, namespace launch or process mutation by reviewer.'},sort_keys=True))
