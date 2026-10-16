from pathlib import Path
import json,hashlib,datetime,importlib.util,socket,os
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');D=B/'tangent-complete-supplemental-01';C=D/'control'
def pin(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
p=json.loads((C/'plan.json').read_text());e=json.loads((C/'execution.json').read_text());base=json.loads((B/'native-complete-build-02/control/execution.json').read_text())
assert pin(C/'plan.json')['sha256']=='bf0e0e36a98b1558276d03c7fcc826f15ee73a929cbae79c2f3069af02b57d55'
assert pin(C/'execution.json')['sha256']=='65f8d55e9eeca061572ddb738c10157354aec407516cec2776e6f0b5dc053d7e'
spec=importlib.util.spec_from_file_location('owned',p['driver']['path']);d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d);d.load_execution(C/'execution.json')
helpers={n:pin(C/n)for n in ('owned_driver09.py','with_correctness_namespace_09.py','replay_nominal_complete_supplemental01.py','run_nominal_complete_supplemental01.py','stage_nominal_complete_checks02.py','complete_native_replay_attribution02.py','compensation_native_regression02.py','tangent_compensated_quadrature.cpp','launch_nominal_complete_supplemental01.py')}
inputs={k:{'pin':v,'observed':pin(Path(v['path']))}for k,v in p['inputs'].items()}
lock=Path(p['global_lock']);st=lock.stat()
r={'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'hostname':socket.gethostname(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'plan_pin':pin(C/'plan.json'),'execution_pin':pin(C/'execution.json'),'plan':p,'execution':e,'base_execution':base,'helpers':helpers,'inputs':inputs,'mutable_inventory':{n:sorted(x.name for x in(D/n).iterdir())for n in('native_source','build','binaries','run','temporary')},'control_outputs_present':{n:(C/n).exists()for n in('pipeline.json','native-supplemental-launch.json','native-supplemental-launch-failure.json')},'global_lock':{'path':str(lock),'device':st.st_dev,'inode':st.st_ino},'admission':d.admission(e,[])}
print(json.dumps(r,indent=2))
