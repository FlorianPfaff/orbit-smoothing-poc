#!/usr/bin/env python3
"""Direct-path receipt view for the host controller, outside its blind fit namespace.

The completed preparation and sealing controls are read-only. Only the exact
fresh campaign control, attempts, temporary directory, and two locks are writable.
The existing controller remains responsible for admission and the empty-root
estimation namespace; this view does not replace that boundary.
"""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,posixpath
KEYS={'schema','helper','readonly_helper','readonly_plan','launch_pins','mount_plan','control_python','bubblewrap'}
def need(ok,msg):
 if not ok:raise RuntimeError(msg)
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for x in iter(lambda:f.read(1048576),b''):h.update(x)
 return h.hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def checked(p):
 need(isinstance(p,dict) and set(p)=={'path','sha256'} and Path(p['path']).is_absolute() and sha(p['path'])==p['sha256'],'Changed host-view artifact');return Path(p['path'])
def read(p):return json.loads(checked(p).read_text())
def canonical_path(value):
 need(isinstance(value,str) and value.startswith('/') and posixpath.normpath(value)==value and '\0' not in value,'Noncanonical host writable path');p=Path(value);need(str(p.resolve())==value,'Host writable path has symlink ancestor');return p
def module(p):
 s=importlib.util.spec_from_file_location('verified_completed_view',checked(p));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def build(p):
 need(set(p)==KEYS and p['schema']=='orbit-poc-segmented-campaign-host-direct-view-v1','Unknown host-view plan')
 for k in ('helper','control_python','bubblewrap'):checked(p[k])
 need(p['helper']==pin(Path(__file__).resolve()) and p['control_python']['path']=='/usr/bin/python3' and p['bubblewrap']['path']=='/usr/bin/bwrap','Exact host executables required')
 m=module(p['readonly_helper']);base=read(p['readonly_plan']);need(base['helper']==p['readonly_helper'] and base['control_python']==p['control_python'] and base['bubblewrap']==p['bubblewrap'],'Read-only base differs')
 validated=m.build(base);head=validated[:validated.index('--')];need(head.count('--bind')==1,'Unexpected writable base');i=head.index('--bind');need(head[i+1:i+3]==[base['control']['path']]*2,'Base control mapping differs');head[i]='--ro-bind'
 e=read(base['execution']);prepplan=read(base['preparation_plan']);launch=read(p['launch_pins']);need(launch['schema']=='orbit-poc-segmented-campaign-launch-pins-v1','Exact detached host launcher required')
 for k in ('launcher','controller','control_python','plan'):checked(launch[k])
 need(launch['control_python']==p['control_python'],'Host launch interpreter differs');host=read(launch['plan']);need(host['helper']==launch['controller'] and host['control_python']==p['control_python'] and host['preparation_controller']==base['preparation_controller'] and host['global_lock']==base['shared_lock']['path'],'Host plan/preparation/lock differs')
 need(host['config']==prepplan['config'] and host['fit_cpu']==24 and host['observer_cpu']==32,'Frozen host config or fit/observer allocation differs')
 control=canonical_path(launch['control_root']);need(host['control_root']==str(control) and control.is_dir() and not control.is_symlink(),'Fresh host control missing')
 protected=[base['control']['path'],prepplan['control_root'],*e['paths'].values(),*[x['path'] for x in base['directories'].values()]]
 protected.extend(row[key] for row in e.get('read_only_bindings',[]) for key in ('source','target'))
 need(all(m.disjoint(control,Path(x)) for x in protected),'Host control overlaps prior controls/inputs/outputs')
 need(all(not (control/x).exists() and not (control/x).is_symlink() for x in ('campaign-launch.json','campaign-driver.log','pipeline.json')),'Preserve earlier campaign output')
 mount=read(p['mount_plan']);need(mount['schema']=='orbit-poc-segmented-fit-mount-plan-v1','Initial campaign requires reviewed fresh mount plan')
 invocation=read(host['invocation']);need(invocation['mount_plan']==p['mount_plan'],'Host invocation uses different fit map')
 writes=mount['writable_mounts'];need(len(writes)==3 and {x['kind'] for x in writes}=={'attempts','temporary','lock'},'Exact three blind writable targets required')
 run=base['directories']['run'];tmp=base['directories']['temporary'];rw=[]
 for row in writes:
  kind=row['kind'];target=canonical_path(row['target']);source=canonical_path(row['source']);identity=row['identity'];need(identity['path']==str(source) and not source.is_symlink(),'Writable source differs or aliases');st=source.stat();need((st.st_dev,st.st_ino)==(identity['device'],identity['inode']),'Writable backing identity changed')
  if kind=='attempts':need(target==Path(run['path'])/'attempts' and source==target,'Attempts mapping differs')
  elif kind=='lock':need(target==Path(run['path'])/'.segmented.lock' and source==target,'Statistical lock mapping differs')
  else:
   need(Path(tmp['path']) in target.parents and source==target,'Temporary must be a direct child within the original temporary slot')
  if kind=='lock':need(source.is_file() and st.st_size==0,'Exact empty regular statistical lock required')
  else:need(source.is_dir() and not any(source.iterdir()),'Writable fit directories must be fresh and empty')
  need(m.disjoint(control,source) and m.disjoint(control,target),'Control overlaps writable fit paths');rw.append((str(source),str(target)))
 lock=base['shared_lock'];lp=canonical_path(lock['path']);ls=lp.stat();need(host['global_lock']==str(lp) and lp.is_file() and not lp.is_symlink() and ls.st_size==0 and (ls.st_dev,ls.st_ino)==(lock['device'],lock['inode']),'Shared physical lock differs')
 rw.extend([(str(lp),str(lp)),(str(control),str(control))]);seen=set()
 aliases=[Path(row[key]) for row in e.get('read_only_bindings',[]) for key in ('source','target')]
 aliases.extend([path.resolve() for path in aliases])
 for source,target in rw:
  # Direct preparation07 preserves the former correctness root read-only.
  # Its explicitly pinned empty shared flock file is the sole allowed carveout
  # under such an ancestor; no directory or sibling evidence becomes writable.
  need(all(m.disjoint(Path(path),alias) or
           (source==target==str(lp) and alias in lp.parents)
           for path in (source,target) for alias in aliases),
       'Writable host mapping overlaps frozen readonly alias')
  need(target not in seen,'Duplicate writable target');seen.add(target);head+=['--bind',source,target]
 head+=['--',p['control_python']['path'],'-B',launch['launcher']['path'],'--pins',p['launch_pins']['path'],'--pins-sha256',p['launch_pins']['sha256']]
 need(not any(x in head for x in ('--unshare-pid','--unshare-net','--die-with-parent')),'Host controller visibility must remain intact')
 return head

def main(argv=None):
 ap=argparse.ArgumentParser();ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--sha256',required=True);a=ap.parse_args(argv);need(sha(a.plan)==a.sha256,'Host-view plan changed');p=json.loads(a.plan.read_text());v=build(p)
 print(json.dumps({'schema':'orbit-poc-segmented-campaign-host-direct-view-exec-v1','plan':pin(a.plan),'host_pid_namespace':os.readlink('/proc/self/ns/pid'),'host_net_namespace':os.readlink('/proc/self/ns/net'),'fit_namespace':'Existing separately verified empty-root namespace remains mandatory.'}),flush=True);os.execv(v[0],v)
if __name__=='__main__':main()
