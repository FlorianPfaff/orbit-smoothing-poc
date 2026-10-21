#!/usr/bin/env python3
"""Revalidate and exec a sealed empty-root fit namespace; no host-root bind."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,sys

KEYS={'schema','wrapper','fresh_planner','resume_planner','mount_plan','bubblewrap','config','python','taskset','inner_helper','inner_plan','probe_helper','probe_spec'}
EXPECTED_BUBBLEWRAP={'path': '/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/bwrap-cap-01/binaries/bwrap-0.6.1-ubuntu0.3-maxargs16384', 'sha256': '7983e8f9ac3c68f072b4ea7884f4d3ce87c2086a1198412649663614113fc3f4'}

FROZEN_SYSTEM_LIBRARIES={'libc.so.6': 'c4de0f865ef79abebf1111f8e4629de4b1835c3e7d71316092885125959daeab', 'libdl.so.2': '7d13eb4345b129fe7572c2eb9a3e120ca02783303c292fe270dd41d5afdb5a72', 'libm.so.6': 'c858d0f5308a1b6ab2fcb4388b34faca06ac6f34ac4db77357a3a91ad8598319', 'libmvec.so.1': 'e1085bc088290d133d45446ee9565d22b3bd1d1eca03c02cc424ded855529944', 'libpthread.so.0': '435030ab98d97c8a9553ef25258315f23b0da3d79066cc2e22008bc6bb940e82', 'libutil.so.1': '71a691869703058342be2581f2b27b7ae4c46ece1f48f91c409890fe68dee925'}
FROZEN_LOADER_SHA256='e2e607e0a17ad7c83f5e5db97f476ed31faebbd587321613f5fddcb4220d7711'
CANONICAL=('config','python','taskset','inner_helper','inner_plan','probe_helper','probe_spec')
def need(ok,why):
 if not ok:raise RuntimeError(why)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def host_pin(pin):
 need(isinstance(pin,dict) and set(pin)=={'path','sha256'} and Path(pin['path']).is_absolute() and sha(pin['path'])==pin['sha256'],'Host control pin differs')
def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

BOOTSTRAP_CODE="import hashlib,json,os,re,stat,sys\n\ndef need(ok,why):\n if not ok:raise RuntimeError(why)\ndef digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()\ndef args_hash(argv):return hashlib.sha256(b''.join(v.encode()+b'\\0' for v in argv)).hexdigest()\ndef descriptors():\n out=[]\n for name in os.listdir('/proc/self/fd'):\n  if int(name)<3:continue\n  try:os.fstat(int(name))\n  except OSError as error:\n   if error.errno==9:continue\n   raise\n  out.append(int(name))\n return sorted(out)\ndef metadata(s):return {'device':s.st_dev,'inode':s.st_ino,'mode':stat.S_IMODE(s.st_mode),'uid':s.st_uid,'gid':s.st_gid,'kind':'directory' if stat.S_ISDIR(s.st_mode) else 'symlink' if stat.S_ISLNK(s.st_mode) else 'other'}\ndef decode(s):return re.sub(r'\\\\([0-7]{3})',lambda m:chr(int(m.group(1),8)),s)\n\nneed(len(sys.argv)>=10,'Bootstrap command is incomplete')\nouter=json.loads(sys.argv[1]);code_sha=sys.argv[2];tail_sha=sys.argv[3];tail=sys.argv[4:]\nneed(set(outer)=={'mnt','pid','net'} and all(re.fullmatch(k+r':\\[\\d+\\]',v) for k,v in outer.items()),'Outer namespace identities differ')\nneed(sys.orig_argv[1:3]==['-B','-c'] and hashlib.sha256(sys.orig_argv[3].encode()).hexdigest()==code_sha,'Bootstrap bytes differ')\nneed(args_hash(tail)==tail_sha and tail[:3]==['/usr/bin/taskset','-c','24'] and tail[3].startswith('/') and tail[4]=='-B','Original command tail differs')\nneed(descriptors()==[],'Bootstrap inherited a descriptor')\ncurrent={k:os.readlink('/proc/self/ns/'+k) for k in outer}\nneed(all(current[k]!=outer[k] for k in outer),'Bootstrap namespace is not fresh')\nneed(os.readlink('/proc/1/ns/pid')==current['pid'],'Bootstrap proc belongs to another PID namespace')\nrows=[]\nwith open('/proc/self/mountinfo') as stream:\n for line in stream:\n  a,sep,b=line.partition(' - ');left,right=a.split(),b.split();need(sep and len(left)>=6 and len(right)>=3,'Malformed bootstrap mount table')\n  rows.append({'id':int(left[0]),'parent':int(left[1]),'target':decode(left[4]),'options':left[5].split(','),'filesystem':right[0]})\nneed(len({r['id'] for r in rows})==len(rows),'Duplicate bootstrap mount identity')\nroots=[r for r in rows if r['target']=='/'];devs=[r for r in rows if r['target']=='/dev'];procs=[r for r in rows if r['target']=='/proc']\nneed(len(roots)==len(devs)==len(procs)==1 and roots[0]['filesystem']=='tmpfs' and devs[0]['filesystem']=='tmpfs' and procs[0]['filesystem']=='proc','Expected private root/dev/proc mounts required')\nneed('ro' in roots[0]['options'] and 'rw' in devs[0]['options'] and bool(os.statvfs('/').f_flag&os.ST_RDONLY) and not bool(os.statvfs('/dev').f_flag&os.ST_RDONLY),'Private root/dev access mode differs')\nneed(not any(r['target']==p or r['target'].startswith(p+'/') for r in rows for p in ('/dev/shm','/dev/core')),'Unexpected shm/core mount')\nenvironment_sha=digest(dict(os.environ));fd=os.open('/dev',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)\ntry:\n dev=os.fstat(fd);need(stat.S_ISDIR(dev.st_mode) and dev.st_dev!=os.stat('/').st_dev and dev.st_uid==os.geteuid(),'Private dev identity differs')\n need('console' not in os.listdir(fd),'Unexpected console device')\n shm=os.stat('shm',dir_fd=fd,follow_symlinks=False);core=os.stat('core',dir_fd=fd,follow_symlinks=False)\n need(stat.S_ISDIR(shm.st_mode) and stat.S_IMODE(shm.st_mode)==0o755 and shm.st_uid==os.geteuid() and shm.st_dev==dev.st_dev,'Unexpected private shm identity')\n need(stat.S_ISLNK(core.st_mode) and core.st_uid==os.geteuid() and core.st_dev==dev.st_dev and os.readlink('core',dir_fd=fd)=='/proc/kcore','Unexpected private core identity')\n shm_fd=os.open('shm',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)\n try:\n  need((os.fstat(shm_fd).st_dev,os.fstat(shm_fd).st_ino)==(shm.st_dev,shm.st_ino) and os.listdir(shm_fd)==[],'Private shm is nonempty or replaced')\n finally:os.close(shm_fd)\n need(metadata(os.stat('shm',dir_fd=fd,follow_symlinks=False))==metadata(shm) and metadata(os.stat('core',dir_fd=fd,follow_symlinks=False))==metadata(core) and os.readlink('core',dir_fd=fd)=='/proc/kcore','Private defaults changed before removal')\n os.rmdir('shm',dir_fd=fd);os.unlink('core',dir_fd=fd)\n need(not {'shm','core'}&set(os.listdir(fd)),'Private default removal did not complete')\nfinally:os.close(fd)\nneed(descriptors()==[] and digest(dict(os.environ))==environment_sha,'Bootstrap altered descriptors or environment')\nprint(json.dumps({'schema':'orbit-poc-private-dev-bootstrap-result-v1','status':'passed','bootstrap_sha256':code_sha,'original_command_sha256':tail_sha,'command':tail,'environment_sha256':environment_sha,'outer_namespaces':outer,'namespaces':current,'mounts':{'root':roots[0],'dev':devs[0],'proc':procs[0]},'dev':metadata(dev),'removed':[{'path':'/dev/shm',**metadata(shm)},{'path':'/dev/core','target':'/proc/kcore',**metadata(core)}],'descriptors':[],'original_command_preserved':True}),flush=True)\nos.execve(tail[0],tail,dict(os.environ))\n"
BOOTSTRAP_SHA256=hashlib.sha256(BOOTSTRAP_CODE.encode()).hexdigest()

def namespace_command(command,outer_namespaces):
 need(isinstance(command,list) and len(command)>=6 and all(isinstance(v,str) and "\0" not in v for v in command),"Invalid original command")
 need(command[:3]==["/usr/bin/taskset","-c","24"] and Path(command[3]).is_absolute() and command[4]=="-B","Original command entry differs")
 need(set(outer_namespaces)=={"mnt","pid","net"},"Complete outer namespace identities required")
 tail_hash=hashlib.sha256(b"".join(v.encode()+b"\0" for v in command)).hexdigest()
 return command[:5]+["-c",BOOTSTRAP_CODE,json.dumps(outer_namespaces,sort_keys=True,separators=(",",":")),BOOTSTRAP_SHA256,tail_hash,*command]

def add_loader_aliases(mount,initial,fresh,backing):
 """Expose the existing frozen libraries at this loader's default paths."""
 args=list(mount['mount_args']);links={x['path']:x['target'] for x in initial['canonical_symlinks']}
 need(args[-2:]==['--remount-ro','/'] and args.count('--remount-ro')==1,'Exact final readonly root boundary required')
 need(links.get('/lib64')=='usr/lib64' and fresh.links_resolve('/lib64',links)=='/usr/lib64','Default library directory topology changed')
 need(links.get('/usr/lib64/ld-linux-x86-64.so.2')=='/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2','Existing loader alias changed')
 backing({'path':'/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2','sha256':FROZEN_LOADER_SHA256})
 rows=[];extra=[];targets=[r['target'] for r in initial['readonly_mounts']+initial['writable_mounts']]
 for name,digest in sorted(FROZEN_SYSTEM_LIBRARIES.items()):
  source='/usr/lib/x86_64-linux-gnu/'+name;destination='/usr/lib64/'+name
  need(fresh.links_resolve(source,links)==source,'Frozen library canonical path changed')
  backing({'path':source,'sha256':digest})
  need(destination not in args and destination not in links and destination not in initial['verified_file_backings'],'Library alias destination already exists')
  need(fresh.links_resolve(destination,links)==destination,'Library alias destination resolves elsewhere')
  need(not any(destination==p or destination.startswith(p.rstrip('/')+'/') for p in targets),'Library alias lies inside an existing mount')
  rows.append({'path':destination,'target':source,'sha256':digest});extra+=['--symlink',source,destination]
 return args[:-2]+extra+args[-2:],rows

def prepare(p,fresh,resume,probe):
 need(set(p)==KEYS and p['schema']=='orbit-poc-segmented-fit-namespace-invocation-v1','Unknown namespace invocation options')
 for key in ('wrapper','fresh_planner','mount_plan','bubblewrap'):host_pin(p[key])
 need(p['wrapper']['sha256']==sha(__file__),'Namespace wrapper changed')
 need(p['bubblewrap']==EXPECTED_BUBBLEWRAP,'Explicit pinned control bubblewrap required')
 mount=json.loads(Path(p['mount_plan']['path']).read_text());schema=mount.get('schema')
 if schema=='orbit-poc-segmented-fit-mount-plan-v1':
  need(p['resume_planner'] is None and resume is None,'Fresh namespace cannot carry a resume adapter')
  need(fresh.build(mount['inputs'])==mount,'Fresh namespace identities changed');initial=mount;prefix=0
 elif schema=='orbit-poc-segmented-fit-resume-mount-plan-v1':
  host_pin(p['resume_planner']);need(resume is not None and resume.build(mount['inputs'])==mount,'Resume namespace identities changed')
  initial=fresh.read(mount['inputs']['inputs']['initial_mount_plan']);prefix=len(mount['terminal_prefix'])
  need(mount.get('input_mounts_unchanged') is True and mount.get('prior_attempts_readonly') is True,'Resume must preserve immutable input/prefix mounts')
 else:raise RuntimeError('Unknown blinded mount plan')
 need(prefix<68,'Already-complete campaign is a verified no-op; do not launch a namespace')
 allow=fresh.read(initial['inputs']['allowlist']);mapping=fresh.read(initial['inputs']['mapping']);links={x['path']:x['target'] for x in initial['canonical_symlinks']};backings=initial['verified_file_backings']
 def backing(pin):
  need(isinstance(pin,dict) and set(pin)=={'path','sha256'},'Canonical artifact pin differs');name=fresh.links_resolve(pin['path'],links);need(name in backings,'Command/control file is not in the original allowlist')
  b=backings[name];need(b['sha256']==pin['sha256'] and sha(b['path'])==pin['sha256'],'Canonical command/control bytes differ');return Path(b['path'])
 for key in CANONICAL:backing(p[key])
 config=json.loads(backing(p['config']).read_text());inner=json.loads(backing(p['inner_plan']).read_text());spec=json.loads(backing(p['probe_spec']).read_text())
 need(p['python']==config['segmented_runtime']['python'],'Parent interpreter differs from frozen runtime')
 need(p['taskset']['path']=='/usr/bin/taskset','Pinned canonical taskset required')
 need(inner['config']==p['config'] and inner['probe_helper']==p['probe_helper'] and inner['probe_spec']==p['probe_spec'],'Inner controller has different pinned inputs')
 need(config['resources']['reserved_cpu_ids']==[24] and config['resources']['maximum_process_tree_rss_bytes']==8589934592,'Frozen numerical CPU/memory settings differ')
 need(config['dense_runtime']['source_root']==config['segmented_runtime']['source_root'] and config['dense_runtime']['source_sha256']==config['segmented_runtime']['source_sha256'],'Shared source identity differs')
 probe.verify_spec_correspondence(spec,mount,allow,mapping)
 library_pin=config['segmented_runtime']['library_manifest'];library=json.loads(backing(library_pin).read_text());source=config['segmented_runtime']['source_root']
 env={'PYTHONPATH':source+'/src','LD_LIBRARY_PATH':library['directory'],'PYTHONNOUSERSITE':'1','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','NUMEXPR_NUM_THREADS':'1','VECLIB_MAXIMUM_THREADS':'1','BLIS_NUM_THREADS':'1','GOTO_NUM_THREADS':'1'}
 args,loader_aliases=add_loader_aliases(mount,initial,fresh,backing)
 for key,value in sorted(env.items()):args+=['--setenv',key,value]
 command=[p['taskset']['path'],'-c','24',p['python']['path'],'-B',p['inner_helper']['path'],'--plan',p['inner_plan']['path'],'--sha256',p['inner_plan']['sha256'],'--allowlist-sha256',initial['inputs']['allowlist']['sha256'],'--mount-plan-sha256',p['mount_plan']['sha256'],'--expected-completed',str(prefix)]
 return {'outer_namespaces':{k:os.readlink('/proc/self/ns/'+k) for k in ('mnt','pid','net')},'loader_aliases':loader_aliases,'mount_args':args,'command':command,'prefix':prefix,'allowlist_sha256':initial['inputs']['allowlist']['sha256'],'mount_plan_sha256':p['mount_plan']['sha256'],'environment':env,'schema':schema,'probe_backing':str(backing(p['probe_helper']))}

def descriptor_boundary(args_fd):
 """Only the sealed setup descriptor survives exec; bwrap consumes it."""
 null=os.open('/dev/null',os.O_RDONLY)
 try:os.dup2(null,0)
 finally:
  if null!=0:os.close(null)
 for name in os.listdir('/proc/self/fd'):
  fd=int(name)
  if fd<3 or fd==args_fd:continue
  try:os.close(fd)
  except OSError:pass
 os.set_inheritable(args_fd,True)

def main(argv=None):
 ap=argparse.ArgumentParser();ap.add_argument('--invocation',type=Path,required=True);ap.add_argument('--sha256',required=True);a=ap.parse_args(argv)
 need(sha(a.invocation)==a.sha256,'Namespace invocation changed');p=json.loads(a.invocation.read_text());need(set(p)==KEYS,'Unknown namespace invocation options')
 host_pin(p['fresh_planner']);fresh=module('reviewed_fresh_fit_mount_planner',p['fresh_planner']['path']);resume=None
 if p['resume_planner'] is not None:host_pin(p['resume_planner']);resume=module('reviewed_fit_resume_planner',p['resume_planner']['path'])
 # Resolve the separately pinned probe helper from the original validated map;
 # no canonical host fallback is permitted, including for libc aliases.
 host_pin(p['mount_plan']);mount=json.loads(Path(p['mount_plan']['path']).read_text());initial=mount if mount.get('schema')=='orbit-poc-segmented-fit-mount-plan-v1' else fresh.read(mount['inputs']['inputs']['initial_mount_plan'])
 links={x['path']:x['target'] for x in initial['canonical_symlinks']};name=fresh.links_resolve(p['probe_helper']['path'],links);pin=initial['verified_file_backings'][name];need(pin['sha256']==p['probe_helper']['sha256'] and sha(pin['path'])==pin['sha256'],'Probe helper changed');probe=module('reviewed_blind_fit_probe',pin['path'])
 prepared=prepare(p,fresh,resume,probe);entry=namespace_command(prepared['command'],prepared['outer_namespaces']);payload=prepared['mount_args']+['--',*prepared['command']];fd=fresh.sealed_args_fd(prepared['mount_args'])
 try:
  print(json.dumps({'schema':'orbit-poc-segmented-fit-namespace-exec-v1','invocation_sha256':a.sha256,'mount_plan_sha256':prepared['mount_plan_sha256'],'starting_terminal_prefix':prepared['prefix'],'host_root_visible':False,'command':prepared['command'],'entry_command':entry,'bootstrap_sha256':BOOTSTRAP_SHA256,'entry_args_sha256':hashlib.sha256(fresh.args_bytes(prepared['mount_args']+['--',*entry])).hexdigest(),'setup_args_sha256':hashlib.sha256(fresh.args_bytes(payload)).hexdigest(),'sealed_options_sha256':hashlib.sha256(fresh.args_bytes(prepared['mount_args'])).hexdigest(),'argument_transport':'sealed_setup_fd_with_direct_command_argv','loader_aliases':prepared['loader_aliases']}),flush=True)
  descriptor_boundary(fd);os.execve(p['bubblewrap']['path'],[p['bubblewrap']['path'],'--args',str(fd),'--',*entry],{})
 finally:os.close(fd)
if __name__=='__main__':main()
