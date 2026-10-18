#!/usr/bin/env python3
"""Read-only direct-path completed-preparation view for input sealing only.

This control does not authorize or launch a fit. Its single exact pinned payload
is an external metadata sealer. Host PID/network visibility is retained.
"""
from pathlib import Path
import argparse,hashlib,json,os,stat
KEYS={'schema','helper','execution','preparation_plan','preparation_controller','directories','historical_validation','shared_lock','control','payload','control_python','bubblewrap','parent_topology'}
SLOTS=('native_source','build','binaries','run','temporary')
def need(ok,why):
 if not ok:raise RuntimeError(why)
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for x in iter(lambda:f.read(1048576),b''):h.update(x)
 return h.hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def checked(p):
 need(isinstance(p,dict) and set(p)=={'path','sha256'} and Path(p['path']).is_absolute() and sha(p['path'])==p['sha256'],'Changed exact canonical-view artifact');return Path(p['path'])
def read(p):return json.loads(checked(p).read_text())
def identity(p):
 p=Path(p);need(p.is_absolute() and '..' not in p.parts and str(p.resolve())==str(p) and p.is_dir() and not p.is_symlink(),'Expected ordinary canonical absolute directory');s=p.stat();return {'path':str(p),'device':s.st_dev,'inode':s.st_ino}
def disjoint(a,b):return a!=b and a not in b.parents and b not in a.parents

def entry(p):
 p=Path(p);s=p.lstat()
 kind='directory' if stat.S_ISDIR(s.st_mode) else 'file' if stat.S_ISREG(s.st_mode) else 'symlink' if stat.S_ISLNK(s.st_mode) else 'unsupported'
 need(kind!='unsupported','Unsupported parent member: '+str(p))
 return {'path':str(p),'device':s.st_dev,'inode':s.st_ino,'kind':kind,'mode':stat.S_IMODE(s.st_mode),'uid':s.st_uid,'gid':s.st_gid,'link_target':os.readlink(p) if kind=='symlink' else None}
def capture_topology(binds):
 roots=set();parents=set()
 for _,name in binds:
  target=Path(name);need(target.is_absolute() and '..' not in target.parts,'Invalid alias target')
  q=target
  if q.exists() or q.is_symlink():continue
  while not q.exists() and not q.is_symlink():
   if q!=target:parents.add(str(q))
   q=q.parent
  need(q.is_dir() and not q.is_symlink() and str(q.resolve())==str(q),'Alias parent must be an ordinary canonical directory')
  need(str(q) not in ('/','/proc','/dev','/sys'),'Unsupported alias parent overlay')
  roots.add(str(q))
 records=[]
 for name in sorted(roots,key=lambda x:(len(Path(x).parts),x)):
  q=Path(name);records.append({'directory':entry(q),'children':[entry(x) for x in sorted(q.iterdir())]})
 return {'schema':'orbit-poc-direct-readonly-parent-topology-v1','roots':records,'missing_parents':sorted(parents,key=lambda x:(len(Path(x).parts),x))}
def topology_args(topology):
 argv=[];roots={row['directory']['path'] for row in topology['roots']}
 for row in topology['roots']:
  root=row['directory']['path'];argv+=['--tmpfs',root,'--chmod',format(row['directory']['mode'],'o'),root]
  for child in row['children']:
   name=child['path']
   if name in roots:argv+=['--dir',name]
   elif child['kind']=='symlink':argv+=['--symlink',child['link_target'],name]
   else:argv+=['--ro-bind',name,name]
 for name in topology['missing_parents']:argv+=['--dir',name]
 return argv

def build(p):
 need(set(p)==KEYS and p['schema']=='orbit-poc-completed-preparation-direct-readonly-view-v1','Wrong canonical-view schema')
 for k in ('helper','control_python','bubblewrap'):checked(p[k])
 need(p['helper']==pin(Path(__file__).resolve()) and p['control_python']['path']=='/usr/bin/python3' and p['bubblewrap']['path']=='/usr/bin/bwrap','Exact host controls required')
 e=read(p['execution']);pp=read(p['preparation_plan']);cp=read(p['preparation_controller'])
 need(pp['schema']=='orbit-poc-segmented-preparation-owned-plan-v1' and pp['execution']==p['execution'],'Preparation does not identify direct execution')
 need(cp['schema']=='orbit-poc-segmented-preparation-owned-run-v1' and cp['status']=='prepared' and cp['benchmark_attempts']==0 and cp['final_cleanup']['verified'] is True and cp['final_cleanup']['errors']==[],'Preparation is not terminal, complete and clean')
 need({k:cp['plan'][k] for k in ('path','sha256')}==p['preparation_plan'] and Path(p['preparation_controller']['path']).parent==Path(pp['control_root']),'Preparation controller/plan/control identity differs')
 need([x['phase'] for x in cp['checks']]==['before','after'] and all(x['status']=='complete' and x['returncode']==0 for x in cp['checks']) and cp['preparation']['status']=='complete' and cp['preparation']['returncode']==0,'Preparation execution/checks are not complete')
 after=read(cp['checks'][1]['result']);cfg=read(pp['config'])
 need(after['schema']=='orbit-poc-segmented-preparation-state-check-v1' and after['status']=='passed' and after['phase']=='after' and after['config']==pp['config'],'Actual after-check attribution differs')
 need(all(after['prepared'][k]==v for k,v in {'cases':28,'attempts':68,'benchmark_fit_count':0}.items()),'Actual preparation must contain28cases/68attempts and zero fits')
 need(after['source_sha256']==cfg['segmented_runtime']['source_sha256']==cfg['dense_runtime']['source_sha256'] and after['validation']['status']=='passed' and {k:after['validation']['pipeline'][k] for k in ('path','sha256')}==pp['pipeline'],'Preparation source or validation identity differs')
 need(e['fit_cpu']==24 and cfg['resources']['reserved_cpu_ids']==[24] and cfg['resources']['threads']==1 and cfg['output_dir']==e['paths']['run'],'Frozen numerical CPU/config/output differs')
 need(after['prepared']['manifest']['path']==str(Path(e['paths']['run'])/'manifest.json'),'Prepared manifest is outside direct run directory');checked(after['prepared']['manifest'])
 need(set(p['directories'])==set(SLOTS),'Exactly five direct slot identities required')
 binds=[]
 for row in e.get('read_only_bindings',[]):
  need(set(row)=={'source','target'} and all(Path(row[k]).is_absolute() and '..' not in Path(row[k]).parts for k in ('source','target')),'Invalid frozen readonly alias')
  binds.append((row['source'],row['target']))
 for k in SLOTS:
  r=p['directories'][k];need(r==identity(e['paths'][k]),'Changed direct canonical directory identity');binds.append((r['path'],r['path']))
 hist=p['historical_validation'];need(hist==identity(str(Path(e['paths']['run'])/'validation')),'Historical validation identity changed')
 checked(pp['pipeline']);binds.append((hist['path'],hist['path']))
 lock=p['shared_lock'];need(set(lock)=={'path','device','inode'} and lock['path']==pp['global_lock'],'Changed shared lock attribution')
 lp=Path(lock['path']);need(lp.is_absolute() and str(lp.resolve())==str(lp) and lp.is_file() and not lp.is_symlink(),'Shared lock is not canonical regular file');ls=lp.stat();need((ls.st_dev,ls.st_ino)==(lock['device'],lock['inode']),'Shared lock inode changed')
 control=p['control'];need(control==identity(control['path']),'Control identity changed');c=Path(control['path'])
 immutable_controls=[pp['control_root'],str(Path(p['execution']['path']).parent),e['paths']['source'],e['paths']['root']]
 immutable_controls.extend(e['paths'][k] for k in ('control','prefix') if k in e['paths'])
 need(all(disjoint(c,Path(x)) and disjoint(c,Path(x).resolve()) for pair in binds for x in pair) and all(disjoint(c,Path(x)) for x in immutable_controls),'Control overlaps canonical evidence/source or preserved control')
 payload=p['payload'];need(set(payload)=={'mode','helper','plan'} and payload['mode']=='seal_inputs','Only external input sealing is allowed');checked(payload['helper']);checked(payload['plan']);need(Path(payload['helper']['path']).parent==c and Path(payload['plan']['path']).parent==c,'Sealer artifacts must be in dedicated control directory')
 topology=read(p['parent_topology']);need(topology==capture_topology(binds),'Alias parent topology changed')
 argv=[p['bubblewrap']['path'],'--unshare-user','--ro-bind','/','/','--proc','/proc','--dev','/dev']
 argv+=topology_args(topology)
 for source,target in binds:argv+=['--ro-bind',source,target]
 for row in reversed(topology['roots']):argv+=['--remount-ro',row['directory']['path']]
 argv+=['--bind',str(c),str(c),'--',p['control_python']['path'],'-B',payload['helper']['path'],'--plan',payload['plan']['path'],'--sha256',payload['plan']['sha256']]
 need(not any(x in argv for x in ('--unshare-pid','--unshare-net','--die-with-parent')),'Host visibility must be retained')
 return argv

def main(argv=None):
 ap=argparse.ArgumentParser();ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--sha256',required=True);a=ap.parse_args(argv);need(sha(a.plan)==a.sha256,'Canonical-view plan changed');p=json.loads(a.plan.read_text());v=build(p)
 print(json.dumps({'schema':'orbit-poc-completed-preparation-direct-readonly-view-exec-v1','plan':pin(a.plan),'mode':'seal_inputs','benchmark_fits':0,'host_pid_namespace':os.readlink('/proc/self/ns/pid'),'host_net_namespace':os.readlink('/proc/self/ns/net')}),flush=True);os.execv(v[0],v)
if __name__=='__main__':main()
