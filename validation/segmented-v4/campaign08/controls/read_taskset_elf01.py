import json,subprocess,hashlib,pathlib,os,datetime
p=pathlib.Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/fit-seal-control-07/sealed-inputs-03/mount-plan.json')
b=p.read_bytes();assert hashlib.sha256(b).hexdigest()=='937e2bf3cb2dae31e459950f912593058cf2f58a30cc77c218794fe295ee6826'
a=json.loads(b);result={'time_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'host':os.uname().nodename,'boot_id':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'affinity':sorted(os.sched_getaffinity(0)),'mount_plan_sha256':hashlib.sha256(b).hexdigest(),'files':{}}
for name in ['/usr/bin/taskset','/usr/lib/x86_64-linux-gnu/libc.so.6','/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2']:
 identity=a['verified_file_backings'][name];path=pathlib.Path(identity['path']);data=path.read_bytes();sha=hashlib.sha256(data).hexdigest();assert sha==identity['sha256']
 row={'backing':str(path),'sha256':sha,'bytes':len(data),'commands':{}}
 for flag in ['-V','-d','-l']:
  q=subprocess.run(['/usr/bin/readelf','-W',flag,str(path)],capture_output=True,text=True);row['commands'][flag]={'returncode':q.returncode,'stdout':q.stdout,'stderr':q.stderr};assert q.returncode==0
 result['files'][name]=row
print(json.dumps(result,indent=2))
