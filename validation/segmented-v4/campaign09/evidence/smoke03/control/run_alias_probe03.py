#!/usr/bin/env python3
"""Owned diagnostic of the corrected namespace; the public campaign is never called."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os
KEYS={'schema','helper','invocation','readonly_helper','readonly_plan','control_python','bubblewrap'}
WRAPPER_SHA='3a0493c9ce4c446977f303dd9a1c13e3d0ef68ba9529e12ebc40aa18b33b9e4f'
MOUNT_SHA='b37477b0ead871285a1fef15144281f60d01fe4521a1626a8c70b51671d732ca'
ALLOW_SHA='a3be6f52f790ed1b03fd5027f5e3d1d0acee25ef5a0df26391a0988c27ddf026'
def need(v,m):
 if not v:raise ValueError(m)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def checked(p):
 need(isinstance(p,dict) and set(p)=={'path','sha256'} and Path(p['path']).is_absolute() and sha(p['path'])==p['sha256'],'Changed smoke pin');return Path(p['path'])
def read(p):return json.loads(checked(p).read_text())
def module(name,p):
 s=importlib.util.spec_from_file_location(name,checked(p));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def context(p):
 need(set(p)==KEYS and p['schema']=='orbit-poc-loader-alias-probe-smoke-v1','Unknown smoke options')
 need(p['helper']==pin(Path(__file__).resolve()),'Smoke helper changed')
 for k in ('control_python','bubblewrap'):checked(p[k])
 need(p['control_python']['path']=='/usr/bin/python3' and p['bubblewrap']['path']=='/usr/bin/bwrap','Original host controls required')
 inv=read(p['invocation']);need(inv['wrapper']['sha256']==WRAPPER_SHA and inv['mount_plan']['sha256']==MOUNT_SHA and inv['resume_planner'] is None,'Exact corrected wrapper and original map required')
 return inv

def empty_writes(mount):
 rows=mount['writable_mounts'];need(len(rows)==3 and {r['kind'] for r in rows}=={'attempts','temporary','lock'},'Exactly original three writable targets required')
 for row in rows:
  p=Path(row['source']);need(row['source']==row['target'] and p.is_absolute() and p.resolve()==p and not p.is_symlink(),'Writable aliases differ');s=p.stat();i=row['identity'];need((s.st_dev,s.st_ino)==(i['device'],i['inode']),'Writable identity changed')
  need((p.is_file() and s.st_size==0) if row['kind']=='lock' else (p.is_dir() and not any(p.iterdir())),'Writable targets must remain empty')
 return [(r['source'],r['target']) for r in rows]

def outer_arguments(p,base_argv,mount):
 need('--' in base_argv,'Base command missing');head=list(base_argv[:base_argv.index('--')]);need(head[0]==p['bubblewrap']['path'] and head.count('--bind')==1,'Unexpected base writable mappings')
 index=head.index('--bind');need(head[index+1]==head[index+2] and Path(head[index+1]).name=='fit-seal-control-07','Original sealing control bind differs');head[index]='--ro-bind'
 for source,target in empty_writes(mount):head+=['--bind',source,target]
 need(not any(v in head for v in ('--unshare-pid','--unshare-net','--die-with-parent')),'Outer visibility changed')
 return head

def probe_command(inv,prepared):
 need(prepared['prefix']==0 and prepared['mount_plan_sha256']==MOUNT_SHA and prepared['allowlist_sha256']==ALLOW_SHA,'Diagnostic must start at original zero-fit prefix')
 need(inv['taskset']['path']=='/usr/bin/taskset','Taskset changed')
 return [inv['taskset']['path'],'-c','24',inv['python']['path'],'-B',inv['probe_helper']['path'],'--spec',inv['probe_spec']['path'],'--sha256',inv['probe_spec']['sha256'],'--allowlist-sha256',ALLOW_SHA,'--mount-plan-sha256',MOUNT_SHA,'--expected-completed','0']

def prepare_probe(p):
 inv=context(p);wrapper=module('exact_alias_wrapper',inv['wrapper']);fresh=module('exact_fresh_planner',inv['fresh_planner']);mount=read(inv['mount_plan']);empty_writes(mount)
 links={r['path']:r['target'] for r in mount['canonical_symlinks']};name=fresh.links_resolve(inv['probe_helper']['path'],links);back=mount['verified_file_backings'][name]
 need(back['sha256']==inv['probe_helper']['sha256'],'Probe backing differs');probe=module('exact_public_probe',{'path':back['path'],'sha256':back['sha256']})
 prepared=wrapper.prepare(inv,fresh,None,probe);command=probe_command(inv,prepared)
 return inv,wrapper,fresh,prepared,command

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--sha256',required=True);ap.add_argument('--inner-host',action='store_true');a=ap.parse_args();need(sha(a.plan)==a.sha256,'Smoke plan changed');p=json.loads(a.plan.read_text());inv=context(p)
 if not a.inner_host:
  base=read(p['readonly_plan']);need(base['helper']==p['readonly_helper'] and base['control_python']==p['control_python'] and base['bubblewrap']==p['bubblewrap'],'Exact readonly base differs');readonly=module('exact_readonly_base',p['readonly_helper']);head=outer_arguments(p,readonly.build(base),read(inv['mount_plan']))
  command=[p['control_python']['path'],'-B',p['helper']['path'],'--plan',str(a.plan),'--sha256',a.sha256,'--inner-host'];os.execv(head[0],head+['--',*command])
 inv,wrapper,fresh,prepared,command=prepare_probe(p);entry=wrapper.namespace_command(command,prepared['outer_namespaces']);fd=fresh.sealed_args_fd(prepared['mount_args'])
 try:
  payload=prepared['mount_args']+['--',*command]
  print(json.dumps({'schema':'orbit-poc-loader-alias-probe-namespace-exec-v1','invocation':p['invocation'],'wrapper':inv['wrapper'],'bubblewrap':inv['bubblewrap'],'mount_plan':inv['mount_plan'],'probe_helper':inv['probe_helper'],'probe_spec':inv['probe_spec'],'command':command,'entry_command':entry,'bootstrap_sha256':wrapper.BOOTSTRAP_SHA256,'entry_args_sha256':hashlib.sha256(fresh.args_bytes(prepared['mount_args']+['--',*entry])).hexdigest(),'environment':prepared['environment'],'allowlist_sha256':ALLOW_SHA,'loader_aliases':prepared['loader_aliases'],'loader_aliases_sha256':hashlib.sha256(json.dumps(prepared['loader_aliases'],sort_keys=True,separators=(',',':')).encode()).hexdigest(),'setup_args_sha256':hashlib.sha256(fresh.args_bytes(payload)).hexdigest(),'sealed_options_sha256':hashlib.sha256(fresh.args_bytes(prepared['mount_args'])).hexdigest(),'argument_transport':'sealed_setup_fd_with_direct_command_argv','benchmark_attempts_launched':0,'scope':'Fixed existing probe02 CLI with full public_checks; no inner campaign invocation.'}),flush=True)
  wrapper.descriptor_boundary(fd);os.execve(inv['bubblewrap']['path'],[inv['bubblewrap']['path'],'--args',str(fd),'--',*entry],{})
 finally:os.close(fd)
if __name__=='__main__':main()
