import pathlib,json,hashlib,subprocess,os,datetime
p=pathlib.Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/fit-seal-control-07/sealed-inputs-03/mount-plan.json');raw=p.read_bytes();assert hashlib.sha256(raw).hexdigest()=='937e2bf3cb2dae31e459950f912593058cf2f58a30cc77c218794fe295ee6826';a=json.loads(raw)
result={'time_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'host':os.uname().nodename,'boot_id':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'affinity':sorted(os.sched_getaffinity(0)),'mount_plan_sha256':hashlib.sha256(raw).hexdigest(),'commands':{},'libraries':{}}
key='/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2';i=a['verified_file_backings'][key];loader=pathlib.Path(i['path']);assert hashlib.sha256(loader.read_bytes()).hexdigest()==i['sha256'];q=subprocess.run([str(loader),'--help'],env={'PATH':'/usr/bin:/bin','LC_ALL':'C'},capture_output=True,text=True,timeout=5);result['commands']['loader_help']={'argv':[str(loader),'--help'],'returncode':q.returncode,'stdout':q.stdout,'stderr':q.stderr};assert q.returncode==0
for key,i in a['verified_file_backings'].items():
 if key.startswith('/usr/lib/x86_64-linux-gnu/'):
  path=pathlib.Path(i['path']);b=path.read_bytes();assert hashlib.sha256(b).hexdigest()==i['sha256'];q=subprocess.run(['/usr/bin/readelf','-W','-d',str(path)],capture_output=True,text=True,timeout=5);assert q.returncode==0
  result['libraries'][key]={'backing':str(path),'sha256':i['sha256'],'readelf_dynamic':q.stdout}
print(json.dumps(result,indent=2))
