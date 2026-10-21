#!/usr/bin/env python3
from pathlib import Path,PurePosixPath
import argparse,hashlib,importlib.util,json,os,subprocess,time,traceback

def need(ok,message):
 if not ok:raise ValueError(message)
def pin(p):
 p=Path(p);return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}
def write(p,v):
 with Path(p).open('x') as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--helper',required=True);ap.add_argument('--sha256',required=True);ap.add_argument('--output',required=True);a=ap.parse_args()
 helper=Path(a.helper);need(pin(helper)['sha256']==a.sha256,'Helper pin changed');out=Path(a.output);need(out.is_absolute() and not out.exists(),'Fresh absolute output required');out.mkdir()
 spec=importlib.util.spec_from_file_location('candidate',helper);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 source=out/'backing.txt';source.write_text('exact fixture backing, no orbit data\n');before=pin(source)
 # Use an actual dynamically linked local Python and loader; these are fixture
 # controls only, not either frozen orbit executable or its remote loader.
 python=Path('/usr/bin/python3').resolve();stdlib=Path('/usr/lib')/('python'+str(os.sys.version_info.major)+'.'+str(os.sys.version_info.minor))
 # The fixture runner is system Python, ensuring this standard library matches.
 need(stdlib.is_dir(),'System Python standard library missing')
 links={'/lib':'usr/lib','/lib64':'usr/lib64','/lib64/ld-linux-x86-64.so.2':'/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2','/usr/lib64/ld-linux-x86-64.so.2':'/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2','/fixture/a':'real','/fixture/a/child':'data.txt','/fixture/real/child':'data.txt','/fixture/b':'/fixture/a','/fixture/b/child':'data.txt','/fixture/rchain':'a/child'}
 placements=m.symlink_placements(links);need(len(placements)==7,'Exactly seven unique actual symlinks expected')
 mounts=[(str(python),str(python)),(str(stdlib),str(stdlib)),(str(source),'/fixture/real/data.txt')]
 for name in ('ld-linux-x86-64.so.2','libc.so.6','libm.so.6','libz.so.1','libexpat.so.1'):
  p=Path('/usr/lib/x86_64-linux-gnu')/name;need(p.is_file(),'Fixture runtime missing '+name);mounts.append((str(p.resolve()),str(p)))
 dirs={'/usr','/usr/bin','/usr/lib','/usr/lib64','/usr/lib/x86_64-linux-gnu','/fixture','/fixture/real'}
 for _,dest in mounts:
  dirs.update(str(p) for p in PurePosixPath(dest).parents if str(p)!='/')
 argv=['/usr/bin/bwrap','--unshare-user','--unshare-pid','--unshare-net','--unshare-ipc','--unshare-uts','--die-with-parent','--new-session','--cap-drop','ALL','--clearenv','--tmpfs','/']
 for d in sorted(dirs,key=lambda p:(len(PurePosixPath(p).parts),p)):argv+=['--dir',d]
 for p,t in sorted(placements.items(),key=lambda x:(len(PurePosixPath(x[0]).parts),x[0])):argv+=['--symlink',t,p]
 for src,dst in mounts:argv+=['--ro-bind',src,dst]
 argv+=['--dev','/dev','--setenv','PYTHONDONTWRITEBYTECODE','1','--chdir','/fixture','--remount-ro','/','--',str(python),'-I','-S','-B','-c',r'''
import json,os,errno
paths=['/fixture/real/data.txt','/fixture/a/child','/fixture/real/child','/fixture/b/child','/fixture/rchain']
values={p:open(p).read() for p in paths}
if len(set(values.values()))!=1:raise ValueError('Read mismatch')
loader=[os.stat(p).st_ino for p in ('/lib64/ld-linux-x86-64.so.2','/usr/lib64/ld-linux-x86-64.so.2','/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2','/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2')]
if len(set(loader))!=1:raise ValueError('Loader aliases differ')
denied={}
for p in ('/fixture/a/child','/fixture/real/data.txt','/fixture/new','/usr/lib64/new','/outside-new'):
 try:
  with open(p,'w') as f:f.write('forbidden')
 except OSError as e:
  if e.errno not in (errno.EROFS,errno.EACCES,errno.EPERM):raise
  denied[p]=e.errno
 else:raise ValueError('Write succeeded '+p)
print(json.dumps({'reads':values,'loader_aliases':4,'loader_inodes_equal':True,'denials':denied,'pid':os.getpid()}))
''']
 request={'schema':'orbit-poc-symlink-closure-real-fixture-request-v1','helper':pin(helper),'links':links,'placements':placements,'argv':argv,'file_backings':[pin(src) for src,_ in mounts if Path(src).is_file()],'host_fixture_name_absent_before':not Path('/fixture').exists(),'frozen_orbit_binaries_used':False,'remote_loader_changed':False}
 write(out/'request.json',request);start=time.monotonic();r=subprocess.run(argv,text=True,capture_output=True,timeout=60,env={'PATH':'/usr/bin:/bin','HOME':str(out),'PYTHONDONTWRITEBYTECODE':'1'})
 (out/'stdout.json').write_text(r.stdout);(out/'stderr.log').write_text(r.stderr)
 result={'schema':'orbit-poc-symlink-closure-real-fixture-result-v1','status':'passed' if r.returncode==0 else 'failed','returncode':r.returncode,'elapsed_seconds':time.monotonic()-start,'helper':pin(helper),'request':pin(out/'request.json'),'stdout':pin(out/'stdout.json'),'stderr':pin(out/'stderr.log'),'backing_unchanged':pin(source)==before,'host_fixture_name_absent_after':not Path('/fixture').exists(),'orbit_native_executions':0,'fit_attempts':0}
 if r.returncode==0:result['checks']=json.loads(r.stdout)
 write(out/'result.json',result);need(r.returncode==0 and result['backing_unchanged'] and result['host_fixture_name_absent_after'],'Real fixture failed; inspect preserved outputs')
 print(json.dumps({'status':result['status'],'result':pin(out/'result.json'),'unique_symlinks':len(placements),'positive_reads':len(result['checks']['reads']),'write_denials':len(result['checks']['denials'])}))
if __name__=='__main__':main()
