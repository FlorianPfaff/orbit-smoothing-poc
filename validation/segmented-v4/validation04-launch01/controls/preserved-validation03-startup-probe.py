#!/usr/bin/env python3
"""Actual namespace startup/dependency checks; never fit or run a numerical gate."""
from pathlib import Path
import argparse,json,os,subprocess,sys,hashlib,re,importlib.metadata

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def need(ok,why):
 if not ok:raise ValueError(why)
def main(argv=None):
 a=argparse.ArgumentParser();a.add_argument('--root',type=Path,required=True);a.add_argument('--output',type=Path,required=True);v=a.parse_args(argv);source=v.root/'source';need(not v.output.exists(),'Preserve startup probe');need(not os.access(source,os.W_OK),'Source is writable');v.output.mkdir(parents=True)
 from orbit_poc.segmented.config import load_config
 from orbit_poc.segmented import protocol as p,validation as gates
 config=load_config(v.root/'control/segmented-v4.json');runtimes={k:p.verify_runtime(getattr(config,k+'_runtime'),source) for k in ('dense','segmented')};inputs=gates.verify_inputs(config,{'runtimes':runtimes},source);runtime=runtimes['segmented']
 need(len(inputs['input_artifacts'])==14,'Original input count differs')
 native=Path(runtime['native']['path']).resolve(strict=True);sidecar=Path(str(native)+'.build-manifest.json');build=json.loads(sidecar.read_text())
 need(build['executable_sha256']==sha(native)==runtime['native']['sha256'],'Adjacent build sidecar identifies wrong executable');need(sha(sidecar)==config.segmented_runtime.build_manifest.sha256,'Sidecar differs from sealed generic build manifest')
 env=dict(os.environ,PYTHONPATH=str(source/'src'),PYTHONDONTWRITEBYTECODE='1',ORBIT_POC_SEGMENTED_GROOPS=str(native),ORBIT_POC_SEGMENTED_SOLVER=runtime['segmented_solver']['path'],ORBIT_POC_SEGMENTED_SOLVER_SHA256=runtime['segmented_solver']['sha256'])
 checked=[]
 for stage in ('nuisance-replay','nuisance-replay-candidate1-point012','segmented-native-tangent','segmented-structural','linearization-log_drag_ou','linearization-pulses'):
  args=gates.command(stage,inputs,runtime,v.output/stage);row={'stage':stage,'original_gate_argv':args,'scope':'Dependency/startup only; original gate not executed'}
  if stage.startswith('nuisance-replay'):
   original=Path(args[args.index('--source-profile')+1]);row.update(source_profile=p.artifact(original),native=p.artifact(native),build_sidecar=p.artifact(sidecar));command=[args[0],args[1],'--help']
  elif stage in ('segmented-native-tangent','segmented-structural'):
   command=[x for x in args if not x.startswith(('--junitxml=','--basetemp='))]+['--collect-only'];row['expected_collection']=3 if stage=='segmented-native-tangent' else 301
  else:
   original=Path(args[args.index('--request')+1]);request=p.read_json(original);p.verify_nested_artifacts(request['estimation_inputs']);state=Path(args[args.index('--initial-state-from')+1]);need(state.is_file(),'Original initial state missing');row.update(request=p.artifact(original),initial_state=p.artifact(state));command=[args[0],args[1],'--help']
  done=subprocess.run(command,cwd=source,env=env,text=True,capture_output=True,timeout=180,check=False);log=v.output/(stage+'.log');log.write_text(done.stdout+done.stderr);row.update(command=command,returncode=done.returncode,log=p.artifact(log));need(done.returncode==0,'Startup failed: '+stage)
  if 'expected_collection' in row:
   matches=re.findall(r'(\d+) tests? collected',done.stdout);need(matches and int(matches[-1])==row['expected_collection'],'Collection incomplete: '+stage);row['collected']=int(matches[-1])
  checked.append(row)
 need(checked[0]['source_profile']['sha256']!=checked[1]['source_profile']['sha256'],'Replay inputs are not distinct')
 import gtsam
 need(importlib.metadata.version('gtsam')=='4.2' and hasattr(gtsam.JacobianFactor,'eliminate'),'Pinned GTSAM4.2 QR oracle unavailable')
 done=subprocess.run([str(native),'--help'],env=env,capture_output=True,text=True,timeout=30,check=False);need(done.returncode==0,'Native executable startup failed')
 result={'schema':'orbit-poc-segmented-validation03-startup-probe-v1','status':'passed','source_read_only':True,'comparison_source_sha256':p.source_snapshot(source)['sha256'],'original_inputs':14,'dependencies':len(inputs['dependencies']),'data_directories':len(inputs['data_directories']),'runtimes':{k:{'native':r['native'],'python':r['python'],'source_sha256':r['source_sha256']} for k,r in runtimes.items()},'native_sidecar':p.artifact(sidecar),'last_six_stage_startup':checked,'gtsam_version':'4.2','full_runtime_verified':True,'fit_or_numerical_gate_executed':False,'native_startup_only':'--help'}
 p.write_json(v.output/'result.json',result);return 0
if __name__=='__main__':raise SystemExit(main())
