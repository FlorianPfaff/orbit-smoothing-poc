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
 return {'loader_aliases':loader_aliases,'mount_args':args,'command':command,'prefix':prefix,'allowlist_sha256':initial['inputs']['allowlist']['sha256'],'mount_plan_sha256':p['mount_plan']['sha256'],'environment':env,'schema':schema,'probe_backing':str(backing(p['probe_helper']))}

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
 prepared=prepare(p,fresh,resume,probe);payload=prepared['mount_args']+['--',*prepared['command']];fd=fresh.sealed_args_fd(prepared['mount_args'])
 try:
  print(json.dumps({'schema':'orbit-poc-segmented-fit-namespace-exec-v1','invocation_sha256':a.sha256,'mount_plan_sha256':prepared['mount_plan_sha256'],'starting_terminal_prefix':prepared['prefix'],'host_root_visible':False,'command':prepared['command'],'setup_args_sha256':hashlib.sha256(fresh.args_bytes(payload)).hexdigest(),'sealed_options_sha256':hashlib.sha256(fresh.args_bytes(prepared['mount_args'])).hexdigest(),'argument_transport':'sealed_setup_fd_with_direct_command_argv','loader_aliases':prepared['loader_aliases']}),flush=True)
  descriptor_boundary(fd);os.execve(p['bubblewrap']['path'],[p['bubblewrap']['path'],'--args',str(fd),'--',*prepared['command']],{})
 finally:os.close(fd)
if __name__=='__main__':main()
