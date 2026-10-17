"""Stage a fresh pinned CLI source/config; no gate or native executable is run."""
from pathlib import Path
import argparse,hashlib,json,tarfile,importlib.util,os,datetime
R=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/validation-05')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def save(p,x):
 with p.open('x') as f:json.dump(x,f,sort_keys=True,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True);p.add_argument('--sha256',required=True);a=p.parse_args()
assert sha(a.archive)==a.sha256 and not R.exists() and not R.is_symlink();R.mkdir()
with tarfile.open(a.archive,'r:gz') as t:
 for m in t.getmembers():assert m.isfile() and not Path(m.name).is_absolute() and '..' not in Path(m.name).parts
 t.extractall(R)
C=R/'control';files=json.loads((C/'packet-files.json').read_text())
for n,h in files.items():assert sha(R/n)==h,n
spec=importlib.util.spec_from_file_location('owned',C/'owned_driver09.py');d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
e=d.load_execution(C/'execution.json');freeze=json.loads((C/'source-freeze.json').read_text());assert d.source_receipt(R/'source')==freeze['source']
for key,value in e['runtime_artifacts'].items():assert sha(d.resolved_host_path(value['path'],e))==value['sha256'],key
assert all(not Path(e['paths'][k]).exists() for k in d.MUTABLE_KEYS)
admission=d.admission(e);admission.update(reserved_cpu_ids=[24],scope='Prelaunch host/boot/CPU and live absence of competing native jobs; task affinity, not administrator-exclusive reservation')
save(C/'admission.json',admission)
cfg=json.loads((C/'config-before-admission.json').read_text());assert cfg['resources']['reserved_cpu_ids']==[24] and cfg['output_dir']==str(R/'run')
assert all(cfg[k]['source_root']==str(R/'source') and cfg[k]['source_sha256']==freeze['comparison_source']['sha256'] for k in ('dense_runtime','segmented_runtime'))
cfg['resources']['admission']=pin(C/'admission.json');save(C/'segmented-v4.json',cfg)
original_plan=json.loads(Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/engineering-02/control/plan.json').read_text())
plan={'schema':'orbit-poc-v4-cli-validation-launch-plan-v1','execution':pin(C/'execution.json'),'driver':pin(C/'owned_driver09.py'),'runner':pin(C/'run_segmented_validation02.py'),'source_freeze':pin(C/'source-freeze.json'),'config':pin(C/'segmented-v4.json'),'native_equivalence':pin(C/'native-rebuild-provenance.json'),'global_lock':original_plan['global_lock'],'wall_limit_seconds':108000}
save(C/'launch-plan.json',plan)
launch={'driver_sha256':sha(C/'run_segmented_validation02.py'),'execution_sha256':sha(C/'execution.json'),'plan':pin(C/'launch-plan.json')};save(C/'launch-pins.json',launch)
r={'schema':'orbit-poc-v4-cli-validation-staging-v1','status':'passed','utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'archive':pin(a.archive),'source_freeze':pin(C/'source-freeze.json'),'source_files':len(freeze['source']['files']),'full_source_sha256':freeze['source']['sha256'],'comparison_source_sha256':freeze['comparison_source']['sha256'],'execution':pin(C/'execution.json'),'config':pin(C/'segmented-v4.json'),'launch_plan':pin(C/'launch-plan.json'),'launch_pins':pin(C/'launch-pins.json'),'admission':pin(C/'admission.json'),'native_equivalence':pin(C/'native-rebuild-provenance.json'),'all_production_outputs_absent':True,'native_work_started':False,'helper':pin(Path(__file__))}
save(C/'staging.json',r);print(json.dumps(r))
