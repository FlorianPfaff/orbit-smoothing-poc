"""Actual composition smokes; full real-runtime preflight remains separate."""
from pathlib import Path
import datetime, importlib.util, json, subprocess, sys
C=Path(__file__).absolute().parent;B=C.parent
spec=importlib.util.spec_from_file_location('composition_gates07',C/'reference_gates09.py')
g=importlib.util.module_from_spec(spec);exec(compile((C/'reference_gates09.py').read_bytes(),str(C/'reference_gates09.py'),'exec'),g.__dict__)
MODES=('prepared','flight-refinement','objective-log_drag_ou','objective-pulses')

def child(path,stage):
 plan=g.read(path);o=g.objective_output_api();row=o.verify(plan,g.overlay_mount_identity)
 proof=g.readonly_mounts(plan);_,multi=g.api();data=[]
 for overlay in plan['directory_overlays']:
  expected=g.read(overlay['inventory']['path']);actual=multi.native_data_inventory(overlay['target'])
  fields=('relative','kind','link_target','bytes','sha256')
  semantic=lambda d:[{k:r.get(k) for k in fields} for r in d['entries']]
  if semantic(actual)!=semantic(expected):raise ValueError('Frozen data inventory differs')
  data.append({'target':overlay['target'],'entries':len(actual['entries']),'identical':True})
 objective=stage in o.STAGES
 target=o.TARGET
 if objective:
  (target/'output/2024-04-24').mkdir(parents=True)
  (target/'output/2024-04-24/probe-output.txt').write_text(stage+'\n')
  if (Path(row['stage_outputs'][stage]['path'])/'2024-04-24/probe-output.txt').read_text()!=stage+'\n':raise ValueError('Output backing mismatch')
 else:
  if (target/'output').exists():raise ValueError('Non-objective namespace gained exporter output')
 o.verify(plan,g.overlay_mount_identity)
 parent_identity=o.identity(target)
 if parent_identity!=(row['view_identity'] if objective else row['host_identity']):raise ValueError('Unexpected namespace parent context')
 g.save(Path(plan['output'])/stage/'child-result.json',{'passed':True,'stage':stage,'objective':objective,
    'parent_identity':parent_identity,'data_overlays':data,'mount_proof':proof,
    'guard_rechecked_after_output':True,'full_checked_plan_real_runtime':False,
    'scope':'Actual corrected guard, kernel mount proof and complete data inventories; full real preflight remains mandatory',
    'native_launched':False})

def main():
 output=C/'namespace-probe01';output.mkdir()
 old=B/'reference-gates13-run01/plan.json';old_pin=g.pin(old);plan=g.read(old)
 plan['output']=str(output);plan['runner']=g.pin(C/'reference_gates09.py')
 plan['storage']=g.storage_api().create(output,tuple(s for s in MODES if s!='prepared'))
 for stage in MODES:
  for leaf in ('tmp','scratch','row-spool'):(output/stage/leaf).mkdir(parents=True,exist_ok=True)
 plan['objective_outputs']=g.objective_output_api().create(output,g.overlay_mount_identity(str(g.objective_output_api().TARGET)))
 g.save(output/'plan.json',plan)
 sources=[g.pin(C/n) for n in ('reference_gates09.py','reference_objective_output.py','reference_storage09.py','namespace_composition_probe.py')]
 boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();results=[]
 for stage in MODES:
  env=g.planned_stage_env(output/stage)
  argv=g.namespace(plan,output/stage,[str(g.PYTHON),'-s','-B',str(Path(__file__).absolute()),'_child',str(output/'plan.json'),stage])
  g.save(output/stage/'command.json',{'argv':argv,'environment':env,'native_launched':False})
  error=None;code=None
  try:
   with (output/stage/'stdout.log').open('x') as stream:
    code=subprocess.run(argv,stdout=stream,stderr=subprocess.STDOUT,env=env,timeout=180).returncode
  except BaseException as exc:error=repr(exc)
  p=output/stage/'child-result.json'
  results.append({'stage':stage,'returncode':code,'error':error,'passed':code==0 and p.exists() and g.read(p)['passed'],
      'child':g.pin(p) if p.exists() else None,'command':g.pin(output/stage/'command.json'),'log':g.pin(output/stage/'stdout.log')})
 same=all(g.pin(r['path'])==r for r in sources);old_same=g.pin(old)==old_pin;boot_same=boot==Path('/proc/sys/kernel/random/boot_id').read_text().strip()
 o=g.objective_output_api();o.verify(plan,g.overlay_mount_identity);host_absent=not(o.TARGET/'output').exists()
 value={'schema':'orbit-reference-composition-namespace-smoke-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'passed':all(r['passed'] for r in results) and same and old_same and boot_same and host_absent,'stages':results,
    'sources':sources,'sources_unchanged':same,'old_plan':old_pin,'old_plan_unchanged':old_same,
    'boot_id':boot,'boot_unchanged':boot_same,'original_host_output_remains_absent':host_absent,
    'original_parent_inventory_unchanged':True,'full_checked_plan_real_runtime':False,'native_launched':False,'release_authority':False}
 g.save(output/'result.json',value);print(json.dumps({'passed':value['passed'],'stages':[{'stage':r['stage'],'passed':r['passed'],'error':r['error']} for r in results]}))
 if not value['passed']:raise RuntimeError('Preserve failed namespace smoke')
if __name__=='__main__':
 if len(sys.argv)>1:child(Path(sys.argv[2]),sys.argv[3])
 else:main()
