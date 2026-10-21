#!/usr/bin/env python3
"""Assemble exact reviewed host/launcher plans from actual sealed metadata.

This program only writes metadata into an existing fresh host-control directory.
It neither launches a namespace nor runs an observer, estimator or native code.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import socket

HELPERS={
 'host':'30fe0add2c5489052f6f353aa66f74dc5425a82e459eb3b06d5bda3037ce680d',
 'launcher':'9a1d6f83ae99d1abc2c017a7b1ca6b1bbf763fe06a1e7d4e0f2dc6c598f04ad4',
 'host_view':'aa1255a0826cc61cbcb9abd2997984bf8610f2c21b7d18dbcd6687dc862b3bb6',
 'readonly':'e2d6532cb90e91694aca103e9541e5450ff7c589c62a9982fc6970e3f0f674e1',
 'observer':'31707b24977fe7d8884c402dcf478253ae99e7d56fecfb22b692312f92a1405e',
 'observer_owner':'d3327e08445462960a6736de4d7dee61b5b35ab7afe0079c4e29c5c520528310',
}
KEYS={'schema','helper','sealed_result','sealing_plan','readonly_plan','helpers',
      'host_control','validation_audit','shifted_audit','prelaunch_evidence'}
OUTPUTS=('host-plan.json','launch-pins.json','host-view-plan.json','assembly.json','failure.json')

def need(ok,why):
 if not ok:raise ValueError(why)
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
 return h.hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def checked(p):
 need(isinstance(p,dict) and set(p)=={'path','sha256'},'Exact pin required')
 q=Path(p['path']);need(q.is_absolute() and q.is_file() and sha(q)==p['sha256'],'Pinned input changed');return q
def read(p):return json.loads(checked(p).read_bytes())
def write(p,v):
 with Path(p).open('x') as f:json.dump(v,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
 return pin(p)
def identity(p):
 q=Path(p);need(q.is_absolute() and str(q.resolve())==str(q) and q.is_dir() and not q.is_symlink(),'Canonical host control directory required');s=q.stat()
 return {'path':str(q),'device':s.st_dev,'inode':s.st_ino}
def module(name,p):
 spec=importlib.util.spec_from_file_location(name,checked(p));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def short(p):return {k:p[k] for k in ('path','sha256')}

def context(p):
 need(set(p)==KEYS and p['schema']=='orbit-poc-direct-campaign-assembly-request-v1','Unknown campaign assembly request')
 need(p['helper']==pin(Path(__file__).resolve()),'Assembler identity differs')
 need(set(p['helpers'])==set(HELPERS),'Exact reviewed helper set required')
 for name,digest in HELPERS.items():checked(p['helpers'][name]);need(p['helpers'][name]['sha256']==digest,'Unreviewed helper: '+name)
 result=read(p['sealed_result']);plan=read(p['sealing_plan']);base=read(p['readonly_plan'])
 need(result['schema']=='orbit-poc-direct-fit-sealing-result-v1' and result['status']=='sealed_metadata' and result['native_executions']==result['fit_attempts']==0 and result['fit_execution_authorized'] is False,'Actual metadata sealing did not complete')
 need(plan['schema']=='orbit-poc-direct-fit-sealing-plan-v1' and plan['manifest']==result['manifest'] and plan['manifest_hash']==result['manifest_hash'] and plan['native_executions']==0 and plan['fit_execution_authorized'] is False,'Sealing plan/result differ')
 need(plan['request']['helper']['sha256']=='4d84a0cbf1f0a053d8b529d0a37f77f4c0de0851b13ab701a8809e1ddbf26c0c','Sealed metadata was not attributed to the reviewed adapter')
 need(base['helper']==p['helpers']['readonly'] and base['payload']['plan']==p['sealing_plan'] and base['payload']['helper']==plan['request']['helper'],'Actual read-only sealing context differs')
 readonly=module('reviewed_direct_readonly',p['helpers']['readonly']);readonly.build(base)
 need(plan['request']['preparation_controller']==base['preparation_controller'] and plan['request']['preparation_plan']==base['preparation_plan'] and plan['request']['execution']==base['execution'] and plan['request']['control']==base['control'],'Sealing used another preparation/control view')
 pp=read(base['preparation_plan']);cp=read(base['preparation_controller']);after=read(cp['checks'][1]['result'])
 need(p['validation_audit']==pp['validation_audit']==plan['request']['validation_audit'] and plan['request']['config']==pp['config'],'Prepared config/audit differs')
 need(result['manifest']==after['prepared']['manifest'] and result['manifest_hash']==read(result['manifest'])['manifest_hash'],'Sealed result does not bind actual checked manifest')
 out=Path(plan['request']['output_root']);need(checked(p['sealed_result'])==out/'result.json','Result outside declared sealing output')
 artifacts=result['artifacts'];need(set(artifacts)<=set(plan['planned_outputs']) and {'mount-plan.json','invocation.json','allowlist.json','backing-map.json','probe-spec.json','correspondence.json'}<=set(artifacts),'Sealing output inventory incomplete')
 for name,r in artifacts.items():need(r['path']==plan['planned_outputs'][name],'Sealed artifact escaped declared path');checked(r)
 need(not (out/'failure.json').exists(),'Failed sealing cannot authorize assembly')
 invocation=read(artifacts['invocation.json']);mount=read(artifacts['mount-plan.json']);allow=read(artifacts['allowlist.json']);probe=read(artifacts['probe-spec.json'])
 need(invocation['schema']=='orbit-poc-segmented-fit-namespace-invocation-v1' and invocation['mount_plan']==artifacts['mount-plan.json'] and invocation['probe_spec']==artifacts['probe-spec.json'] and invocation['config']==pp['config'] and invocation['resume_planner'] is None,'Sealed invocation differs or is not fresh')
 need(mount['schema']=='orbit-poc-segmented-fit-mount-plan-v1' and short(mount['inputs']['allowlist'])==artifacts['allowlist.json'] and short(mount['inputs']['mapping'])==artifacts['backing-map.json'],'Sealed mount inputs differ')
 need(allow['manifest_hash']==probe['manifest_hash']==result['manifest_hash'],'Allowlist/probe manifest differs')
 host=module('reviewed_host',p['helpers']['host'])
 need(p['host_control']==identity(p['host_control']['path']),'Host control inode changed');control=Path(p['host_control']['path'])
 execution=read(base['execution'])
 protected=[base['control']['path'],pp['control_root'],*execution['paths'].values(),*[r['path'] for r in base['directories'].values()]]
 protected.extend(row[key] for row in execution['read_only_bindings'] for key in ('source','target'))
 protected.extend(row[key] for row in mount['writable_mounts'] for key in ('source','target'))
 need(all(readonly.disjoint(control,Path(q)) and readonly.disjoint(control,Path(q).resolve()) for q in protected),'Host control overlaps preserved inputs, outputs or controls')
 need(all(not (control/name).exists() and not (control/name).is_symlink() for name in (*OUTPUTS,'pipeline.json','campaign-launch.json','campaign-driver.log','controller.lock')),'Preserve earlier host/control output')
 need(isinstance(p['prelaunch_evidence'],list) and p['prelaunch_evidence'] and len({r['path'] for r in p['prelaunch_evidence']})==len(p['prelaunch_evidence']),'Explicit unique prelaunch evidence pins required')
 for r in p['prelaunch_evidence']:checked(r)
 checked(pp['driver']);checked(p['shifted_audit']);checked(p['validation_audit'])
 return result,base,pp,invocation,host

def assemble(p):
 result,base,pp,inv,host=context(p);control=Path(p['host_control']['path']);artifacts={}
 def save(name,v):
  r=write(control/name,v);artifacts[name]=r;return r
 try:
  hp={'schema':'orbit-poc-segmented-blind-host-plan-v1','helper':p['helpers']['host'],'driver':pp['driver'],
   'wrapper':inv['wrapper'],'invocation':result['artifacts']['invocation.json'],
   'observer':p['helpers']['observer'],'observer_owner':p['helpers']['observer_owner'],
   'control_python':base['control_python'],'taskset':inv['taskset'],'config':pp['config'],
   'validation_audit':p['validation_audit'],'shifted_audit':p['shifted_audit'],
   'preparation_controller':base['preparation_controller'],
   'host':{'hostname':socket.gethostname(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()},
   'global_lock':pp['global_lock'],'control_root':str(control),'maximum_seconds':604800,
   'minimum_free_bytes':34359738368,'fit_cpu':24,'sibling_cpus':[88],'observer_cpu':32,'cadence_seconds':2}
  hpin=save('host-plan.json',hp);need(host.load_plan(hpin['path'],hpin['sha256'])==hp,'Reviewed host rejected assembled plan')
  host.bind_prepared_context(hp,read(result['artifacts']['allowlist.json']),read(result['artifacts']['probe-spec.json']))
  lp={'schema':'orbit-poc-segmented-campaign-launch-pins-v1','launcher':p['helpers']['launcher'],
      'controller':p['helpers']['host'],'control_python':base['control_python'],'plan':hpin,'control_root':str(control)}
  lpin=save('launch-pins.json',lp)
  vp={'schema':'orbit-poc-segmented-campaign-host-direct-view-v1','helper':p['helpers']['host_view'],
      'readonly_helper':p['helpers']['readonly'],'readonly_plan':p['readonly_plan'],'launch_pins':lpin,
      'mount_plan':result['artifacts']['mount-plan.json'],'control_python':base['control_python'],'bubblewrap':base['bubblewrap']}
  vpin=save('host-view-plan.json',vp);view=module('reviewed_direct_host_view',p['helpers']['host_view']);view.build(vp)
  for r in [p['sealed_result'],p['sealing_plan'],p['readonly_plan'],p['validation_audit'],p['shifted_audit'],*p['helpers'].values(),*p['prelaunch_evidence']]:checked(r)
  assembly={'schema':'orbit-poc-direct-campaign-assembly-result-v1','status':'assembled_metadata','request':p,
   'actual_manifest':result['manifest'],'manifest_hash':result['manifest_hash'],'artifacts':artifacts,
   'native_executions':0,'fit_attempts':0,'fit_execution_authorized':False,
   'launch_command':['/usr/bin/taskset','-c','32',base['control_python']['path'],'-B',p['helpers']['host_view']['path'],'--plan',vpin['path'],'--sha256',vpin['sha256']],
   'scope':'Metadata assembly only. Exact concrete packet review and unchanged inner positive/denial probes remain prerequisites. Owned host controller rechecks current admission and launches only the existing empty-root numerical namespace on CPU24.'}
  save('assembly.json',assembly);return assembly
 except BaseException as error:
  write(control/'failure.json',{'schema':'orbit-poc-direct-campaign-assembly-failure-v1','status':'failed','error':repr(error),'artifacts':artifacts,'native_executions':0,'fit_attempts':0,'prior_outputs_preserved':True});raise

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--request',required=True);parser.add_argument('--sha256',required=True);a=parser.parse_args()
 r=assemble(read({'path':a.request,'sha256':a.sha256}));print(json.dumps({k:r[k] for k in ('status','manifest_hash','native_executions','fit_attempts','fit_execution_authorized','launch_command')}))
if __name__=='__main__':main()
