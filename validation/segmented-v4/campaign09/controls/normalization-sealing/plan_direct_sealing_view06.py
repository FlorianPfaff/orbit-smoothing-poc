#!/usr/bin/env python3
"""Derive the reviewed read-only sealing view from a real sealing plan."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json

def need(ok,why):
 if not ok:raise ValueError(why)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def read(p):
 need(set(p)=={'path','sha256'} and Path(p['path']).is_absolute() and sha(p['path'])==p['sha256'],'Pinned sealing input changed');return json.loads(Path(p['path']).read_bytes())

def build(sealing_plan,readonly_helper,output):
 plan=read(sealing_plan);need(plan['schema']=='orbit-poc-direct-fit-sealing-plan-v1' and plan['native_executions']==0 and plan['fit_execution_authorized'] is False,'Actual sealing plan required')
 request=plan['request'];helper=request['helper'];need(helper['sha256']=='ece54c60d011e3ef8ee252d9a424d35dc1862a1069246e7c0bf8f4b950ace776' and sha(helper['path'])==helper['sha256'],'Unreviewed sealing adapter')
 need(readonly_helper['sha256']=='e2d6532cb90e91694aca103e9541e5450ff7c589c62a9982fc6970e3f0f674e1' and pin(readonly_helper['path'])==readonly_helper,'Unreviewed direct readonly helper')
 spec=importlib.util.spec_from_file_location('reviewed_direct_view',readonly_helper['path']);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 execution=read(request['execution']);prep=read(request['preparation_plan']);controller=read(request['preparation_controller']);after=read(controller['checks'][1]['result'])
 need(after['prepared']['manifest']==plan['manifest'] and read(plan['manifest'])['manifest_hash']==plan['manifest_hash'],'Sealing plan differs from actual terminal manifest')
 control=request['control'];need(control==m.identity(control['path']),'Sealing control inode changed');output=Path(output)
 need(output.is_absolute() and str(output.resolve())==str(output) and output.parent==Path(control['path']) and not output.exists() and not output.is_symlink(),'Use a fresh output file in the actual sealing control')
 lock=Path(prep['global_lock']);st=lock.stat();need(lock.is_file() and not lock.is_symlink() and st.st_size==0 and str(lock.resolve())==str(lock),'Canonical empty shared lock required')
 result={'schema':'orbit-poc-completed-preparation-direct-readonly-view-v1','helper':readonly_helper,
  'execution':request['execution'],'preparation_plan':request['preparation_plan'],'preparation_controller':request['preparation_controller'],
  'directories':{k:m.identity(execution['paths'][k]) for k in m.SLOTS},
  'historical_validation':m.identity(str(Path(execution['paths']['run'])/'validation')),
  'shared_lock':{'path':str(lock),'device':st.st_dev,'inode':st.st_ino},'control':control,
  'payload':{'mode':'seal_inputs','helper':helper,'plan':sealing_plan},
  'control_python':pin('/usr/bin/python3'),'bubblewrap':request['bubblewrap']}
 topology_path=output.with_name(output.stem+'-parents.json')
 topology=m.capture_topology([(row['source'],row['target']) for row in execution['read_only_bindings']])
 with topology_path.open('x') as f:json.dump(topology,f,indent=2,sort_keys=True);f.write('\n')
 result['parent_topology']=pin(topology_path)
 m.build(result)
 with output.open('x') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
 return {'schema':'orbit-poc-direct-readonly-plan-build-result-v1','plan':pin(output),'actual_manifest':plan['manifest'],
         'native_executions':0,'fit_attempts':0,'fit_execution_authorized':False}

def main():
 p=argparse.ArgumentParser();p.add_argument('--sealing-plan',required=True);p.add_argument('--sha256',required=True);p.add_argument('--readonly-helper',required=True);p.add_argument('--readonly-helper-sha256',required=True);p.add_argument('--output',required=True);a=p.parse_args()
 print(json.dumps(build({'path':a.sealing_plan,'sha256':a.sha256},{'path':a.readonly_helper,'sha256':a.readonly_helper_sha256},a.output)))
if __name__=='__main__':main()
