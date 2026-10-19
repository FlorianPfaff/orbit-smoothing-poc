from pathlib import Path
import argparse,hashlib,importlib.util,json,os,stat,subprocess,time
SOURCE=Path('/mnt/d/orbit-segmented-v4/control/device-bootstrap-wrapper-draft01/with_segmented_fit_namespace05.py')
EXPECTED='3a0493c9ce4c446977f303dd9a1c13e3d0ef68ba9529e12ebc40aa18b33b9e4f'
BWRAP=Path('/mnt/d/orbit-segmented-v4/control/bwrap-recovery-research01/binary/usr/bin/bwrap')
BWRAP_SHA='bf6cf3d4456665f5d80c14eb79a76e0ce87b39a0883e614a161658b4ec33492c'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def meta(p):
 try:
  s=os.lstat(p);return {'device':s.st_dev,'inode':s.st_ino,'mode':stat.S_IMODE(s.st_mode),'uid':s.st_uid,'gid':s.st_gid,'target':os.readlink(p) if stat.S_ISLNK(s.st_mode) else None}
 except FileNotFoundError:return None
OBSERVER=r'''import pathlib,sys,os,stat,json,subprocess,hashlib
case,command_json=sys.argv[1:];command=json.loads(command_json)
def meta(p):
 try:
  s=os.lstat(p);r={'device':s.st_dev,'inode':s.st_ino,'mode':stat.S_IMODE(s.st_mode),'uid':s.st_uid,'gid':s.st_gid,'kind':'symlink' if stat.S_ISLNK(s.st_mode) else 'directory' if stat.S_ISDIR(s.st_mode) else 'file'}
  if stat.S_ISLNK(s.st_mode):r['target']=os.readlink(p)
  elif stat.S_ISREG(s.st_mode):r['sha256']=hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
  return r
 except FileNotFoundError:return None
def snapshot():
 paths=['/dev/shm','/dev/core','/dev/console']
 if pathlib.Path('/dev/shm').is_dir():paths.extend(str(p) for p in pathlib.Path('/dev/shm').iterdir())
 return {p:meta(p) for p in paths}
assert pathlib.Path('/dev/shm').is_dir() and os.readlink('/dev/core')=='/proc/kcore'
if case=='nonempty_shm':pathlib.Path('/dev/shm/sentinel').write_text('preserve me')
elif case=='wrong_core':os.unlink('/dev/core');os.symlink('/wrong-target','/dev/core')
elif case=='wrong_shm_mode':os.chmod('/dev/shm',0o700)
elif case=='console':pathlib.Path('/dev/console').write_text('unexpected console')
elif case=='host_namespace':
 # Replace only expected outer identities with current IDs, proving freshness rejection.
 command[7]=json.dumps({k:os.readlink('/proc/self/ns/'+k) for k in ('mnt','pid','net')},sort_keys=True,separators=(',',':'))
before=snapshot();r=subprocess.run(command,capture_output=True,text=True,timeout=10,env=dict(os.environ));after=snapshot()
positive=case=='positive';tail_seen='FROZEN_TAIL_EXECUTED' in r.stdout
if positive:
 assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
 assert tail_seen and after['/dev/shm'] is None and after['/dev/core'] is None,(r.stdout,after)
 receipts=[json.loads(x) for x in r.stdout.splitlines()];boot=next(x for x in receipts if x.get('schema')=='orbit-poc-private-dev-bootstrap-result-v1');tail=next(x for x in receipts if x.get('marker')=='FROZEN_TAIL_EXECUTED')
 assert boot['original_command_preserved'] is True and boot['descriptors']==[]
 assert tail['affinity']==[24] and not {'shm','core'}&set(tail['dev_entries'])
else:
 assert r.returncode!=0 and not tail_seen and before==after,(case,r.returncode,r.stdout,r.stderr,before,after)
print(json.dumps({'case':case,'passed':True,'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr,'before':before,'after':after,'original_entries_unchanged_on_rejection':None if positive else before==after,'tail_executed':tail_seen,'namespaces':{k:os.readlink('/proc/self/ns/'+k) for k in ('mnt','pid','net')}},sort_keys=True))
'''
TAIL="import json,os;print(json.dumps({'marker':'FROZEN_TAIL_EXECUTED','affinity':sorted(os.sched_getaffinity(0)),'dev_entries':sorted(os.listdir('/dev'))}))"
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();a.output.mkdir(exist_ok=False)
 assert sha(SOURCE)==EXPECTED and sha(BWRAP)==BWRAP_SHA
 spec=importlib.util.spec_from_file_location('exact_wrapper05',SOURCE);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 outer={k:os.readlink('/proc/self/ns/'+k) for k in ('mnt','pid','net')}
 command=m.namespace_command(['/usr/bin/taskset','-c','24','/usr/bin/python3','-B','-c',TAIL],outer)
 host_before={p:meta(p) for p in ['/dev','/dev/shm','/dev/core']};rows=[]
 for case in ['positive','nonempty_shm','wrong_core','wrong_shm_mode','shm_submount','console','host_namespace']:
  args=[str(BWRAP),'--unshare-user','--unshare-pid','--unshare-net','--unshare-ipc','--unshare-uts','--die-with-parent','--new-session','--cap-drop','ALL','--clearenv','--setenv','PATH','/usr/bin','--setenv','PYTHONDONTWRITEBYTECODE','1','--setenv','FIXTURE_VALUE','preserved','--tmpfs','/','--ro-bind','/usr','/usr','--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64','--proc','/proc','--dev','/dev']
  if case=='shm_submount':args+=['--tmpfs','/dev/shm']
  args+=['--remount-ro','/','--','/usr/bin/python3','-B','-c',OBSERVER,case,json.dumps(command)]
  start=time.monotonic();r=subprocess.run(args,capture_output=True,text=True,timeout=20)
  (a.output/(case+'.stdout')).write_text(r.stdout);(a.output/(case+'.stderr')).write_text(r.stderr)
  row={'case':case,'returncode':r.returncode,'elapsed_seconds':time.monotonic()-start,'stdout_sha256':hashlib.sha256(r.stdout.encode()).hexdigest(),'stderr_sha256':hashlib.sha256(r.stderr.encode()).hexdigest()}
  if r.returncode==0:row['evidence']=json.loads(r.stdout)
  rows.append(row)
  if r.returncode!=0:break
 host_after={p:meta(p) for p in ['/dev','/dev/shm','/dev/core']}
 result={'schema':'orbit-v4-private-dev-bootstrap-real-kernel-fixture-v1','source_sha256':sha(SOURCE),'bootstrap_sha256':m.BOOTSTRAP_SHA256,'fixture_source_sha256':sha(__file__),'bubblewrap_sha256':sha(BWRAP),'bubblewrap_version':subprocess.run([str(BWRAP),'--version'],capture_output=True,text=True,check=True).stdout.strip(),'scope':'Local genuine fresh kernel namespaces, exact original Ubuntu0.6.1 binary; cap increase is irrelevant to these small argv. Host libraries and Python used for fixture only, no production inputs or fits.','outer_namespaces':outer,'cases':rows,'host_before':host_before,'host_after':host_after,'host_entries_unchanged':host_before==host_after,'all_passed':len(rows)==7 and all(r['returncode']==0 for r in rows),'source_unchanged':sha(SOURCE)==EXPECTED,'remote_workloads':False,'scientific_workloads':False}
 (a.output/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'result':str(a.output/'result.json'),'sha256':sha(a.output/'result.json'),'all_passed':result['all_passed'],'cases':len(rows),'host_entries_unchanged':result['host_entries_unchanged']}))
 if not result['all_passed'] or host_before!=host_after:raise SystemExit(1)
if __name__=='__main__':main()
