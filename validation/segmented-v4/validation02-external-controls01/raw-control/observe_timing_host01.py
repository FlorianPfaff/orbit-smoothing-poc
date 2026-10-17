#!/usr/bin/env python3
"""Read-only CPU/topology observation, never an exclusive reservation receipt."""
import json,os,time,socket,datetime
from pathlib import Path
CPUS={24,88}
def read(p):
 try:return Path(p).read_text().strip()
 except OSError as e:return {'unavailable':type(e).__name__}
def expand(value):
 out=set()
 for token in value.split(','):
  a,_,b=token.partition('-');out.update(range(int(a),int(b or a)+1))
 return out
def snapshot():
 rows={};unreadable=0
 for process in Path('/proc').glob('[0-9]*'):
  for thread in (process/'task').glob('[0-9]*'):
   try:
    fields=(thread/'stat').read_text().rsplit(')',1)[1].split();status=dict(x.split(':',1) for x in (thread/'status').read_text().splitlines());allowed=expand(status['Cpus_allowed_list'].strip())
    if not allowed&CPUS:continue
    key=(int(thread.name),int(fields[19]));rows[key]={'pid':int(process.name),'tid':int(thread.name),'start_ticks':int(fields[19]),'cpu_ticks':int(fields[11])+int(fields[12]),'last_cpu':int(fields[36]),'state':fields[0],'allowed_cpus':status['Cpus_allowed_list'].strip(),'uid':int(status['Uid'].split()[0]),'name':status['Name'].strip(),'ppid':int(status['PPid'])}
   except (OSError,ValueError,KeyError):unreadable+=1
 return rows,unreadable
start=time.monotonic();t0=datetime.datetime.now(datetime.timezone.utc).isoformat();a,ea=snapshot();stat0=read('/proc/stat');time.sleep(2);b,eb=snapshot();stat1=read('/proc/stat');elapsed=time.monotonic()-start
active=[]
for key,row in b.items():
 delta=row['cpu_ticks']-a.get(key,row)['cpu_ticks']
 if delta>0:active.append({**row,'delta_cpu_ticks':delta,'sample_cpu_seconds':delta/os.sysconf('SC_CLK_TCK'),'observed_last_cpu_is_reserved_or_sibling':row['last_cpu'] in CPUS})
topology={str(cpu):{name:read('/sys/devices/system/cpu/cpu'+str(cpu)+'/topology/'+name) for name in ('physical_package_id','core_id','thread_siblings_list','core_siblings_list')} for cpu in CPUS}
value={'schema':'orbit-poc-timing-host-observation-v1','hostname':socket.gethostname(),'boot_id':read('/proc/sys/kernel/random/boot_id'),'started_at':t0,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'elapsed_seconds':elapsed,'purpose':'Future timed benchmark planning only; current correctness validation may own CPU24. No exclusive reservation is claimed.','observer_pid':os.getpid(),'observer_affinity':sorted(os.sched_getaffinity(0)),'topology':topology,'isolated_cpus':read('/sys/devices/system/cpu/isolated'),'nohz_full':read('/sys/devices/system/cpu/nohz_full'),'self_cgroup':read('/proc/self/cgroup'),'cpuset_effective':read('/sys/fs/cgroup/cpuset.cpus.effective'),'loadavg':read('/proc/loadavg'),'cpu_stat_before':stat0,'cpu_stat_after':stat1,'active_threads_allowed_on_reserved_core':sorted(active,key=lambda x:-x['delta_cpu_ticks']),'eligible_thread_count_before':len(a),'eligible_thread_count_after':len(b),'unreadable_thread_count_before':ea,'unreadable_thread_count_after':eb,'limitation':'Allowed affinity is potential competition. Last CPU is a sampled observation, not a complete scheduling trace. A quiet two-second sample cannot certify future exclusivity.'}
print(json.dumps(value,sort_keys=True,indent=2))
