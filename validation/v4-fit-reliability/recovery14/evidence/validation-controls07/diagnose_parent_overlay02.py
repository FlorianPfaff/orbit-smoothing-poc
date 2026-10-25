"""Reproduce frozen06 composition guard in a fresh namespace; no native work."""
from pathlib import Path
import datetime, importlib.util, json, subprocess, sys
B=Path('/mnt/d/orbit-v41-recovery02');C=B/'validation-controls06'
spec=importlib.util.spec_from_file_location('original_gates06',C/'reference_gates09.py')
g=importlib.util.module_from_spec(spec);exec(compile((C/'reference_gates09.py').read_bytes(),str(C/'reference_gates09.py'),'exec'),g.__dict__)

def child(path):
 plan=g.read(path);o=g.objective_output_api();row=plan['objective_outputs'];target=Path(row['target'])
 overlay=next(r for r in plan['directory_overlays'] if r['target']==str(target/'data'))
 actual=o.tree(target);original=row['original_tree'];data=o.tree(Path(overlay['source']))
 expected=sorted([r for r in original if not (r['relative']=='data' or r['relative'].startswith('data/'))]+[{'relative':'data','kind':'directory'}]+[{**r,'relative':'data/'+r['relative']} for r in data],key=lambda r:r['relative'])
 error=None
 try:o.verify(plan,g.overlay_mount_identity)
 except Exception as exc:error=repr(exc)
 result={'schema':'orbit-parent-overlay-diagnosis-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'native_launched':False,'frozen_guard_exception':error,'parent_identity':o.identity(target),'frozen_host_identity':row['host_identity'],'data_identity':o.identity(target/'data'),'mirror_identity':o.identity(overlay['source']),'actual_tree':actual,'original_tree':original,'expected_composed_tree':expected,'actual_equals_exact_composition':actual==expected,'nondata_unchanged': [r for r in actual if not(r['relative']=='data' or r['relative'].startswith('data/'))]==[r for r in original if not(r['relative']=='data' or r['relative'].startswith('data/'))], 'readonly_proof':g.readonly_mounts(plan)}
 g.save(Path(plan['output'])/'prepared/child-result.json',result)
 assert error=="ValueError('Original prepared parent changed')" and actual==expected and result['nondata_unchanged']
 assert result['parent_identity']==row['host_identity'] and result['data_identity']==result['mirror_identity']

def main():
 output=B/'validation-controls07/diagnosis02';output.mkdir()
 old=B/'reference-gates13-run01/plan.json';before=g.pin(old);plan=g.read(old)
 plan['output']=str(output);plan['storage']=g.storage_api().create(output,())
 for leaf in ('tmp','scratch','row-spool'):(output/'prepared'/leaf).mkdir(parents=True,exist_ok=True)
 plan['objective_outputs']=g.objective_output_api().create(output,g.overlay_mount_identity(str(g.objective_output_api().TARGET)))
 g.save(output/'plan.json',plan)
 argv=g.namespace(plan,output/'prepared',[str(g.PYTHON),'-s','-B',str(Path(__file__).absolute()),'_child',str(output/'plan.json')])
 g.save(output/'command.json',{'argv':argv,'environment':g.planned_stage_env(output/'prepared'),'original_plan':before,'probe_source':g.pin(Path(__file__)),'native_launched':False})
 with (output/'stdout.log').open('x') as stream:
  result=subprocess.run(argv,stdout=stream,stderr=subprocess.STDOUT,env=g.planned_stage_env(output/'prepared'),timeout=180)
 o=g.objective_output_api();unchanged=o.tree(o.TARGET)==plan['objective_outputs']['original_tree']
 g.save(output/'result.json',{'returncode':result.returncode,'reproduced':result.returncode==0,'original_plan_unchanged':g.pin(old)==before,'original_host_tree_unchanged':unchanged,'host_output_absent':not(o.TARGET/'output').exists(),'native_launched':False,'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()})
 print(json.dumps(g.read(output/'result.json')))
 if result.returncode:raise RuntimeError('Diagnosis failed; preserve receipt')
if __name__=='__main__':
 if len(sys.argv)>1:child(Path(sys.argv[2]))
 else:main()
