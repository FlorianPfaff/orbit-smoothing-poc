"""Stage one of four explicitly distinct, archived native regression problems."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,shutil,socket,xml.etree.ElementTree as ET
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff')
BAD='753992c25b8ee35f52468f0d4439501f642bc531685eecd44942eac438ba7769'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def save(p,v):
 with Path(p).open('x')as f:json.dump(v,f,indent=2);f.write('\n')
def selection(case,mode):
 if case not in ('preparation03','preparation04')or mode not in ('single','closure'):raise ValueError('Unknown exact native check')
 old=case=='preparation03';validation='validation-04'if old else'validation-05'
 if mode=='single':
  return {'root':'tangent-compensation-single-'+('01'if old else'02'),'validation':validation,'template':'iteration-01/propagate.xml'if old else'iteration-03/propagate.xml','reference':'initial'if old else'iteration-02','failure':'iteration-01/propagate.log'if old else'iteration-03/propagate.log','worker':'replay_nominal_precision_single01.py','controller':'run_nominal_precision_single01.py','schema':'orbit-poc-nominal-precision-single-replay-plan-v1'}
 return {'root':'tangent-precision-closure-'+('02'if old else'03'),'validation':validation,'template':'iteration-01/propagate.xml','reference':'initial','failure':'iteration-01/propagate.log'if old else'iteration-03/propagate.log','worker':'replay_nominal_precision_closure02.py','controller':'run_nominal_precision_closure02.py','schema':'orbit-poc-nominal-precision-closure-plan-v1'}
def add_ro(e,path):
 matches=[x for x in e['read_only_bindings']if x['target']==str(path)]
 if matches:
  if matches!=[{'source':str(path),'target':str(path)}]:raise ValueError('Conflicting preserved read-only target')
 else:e['read_only_bindings'].append({'source':str(path),'target':str(path)})
def main(argv=None):
 ap=argparse.ArgumentParser();ap.add_argument('--case',required=True,choices=('preparation03','preparation04'));ap.add_argument('--mode',required=True,choices=('single','closure'));a=ap.parse_args(argv);s=selection(a.case,a.mode)
 R=B/'validation-05';P=B/'preparation-04';D=B/s['root'];C=D/'control';original=B/s['validation']/'run/preparation/prefixes'/BAD/'nominal-initialization'
 base=P/'control/execution.json';assert sha(base)=='98e9ea204c22d176e271141b993338579430df9354bcde5f74a44fb9476efe77';e=json.loads(base.read_text())
 assert sha(P/'control/pipeline.json')=='7f3e029b2314dde54ebab75892f2193adb474f9caa1bb15225b58d041f7e8241'
 for name in('source','native_source','build','binaries','run','temporary'):assert not(D/name).exists(),name
 shutil.copytree(R/'source',D/'source')
 for name in('native_source','build','binaries','run','temporary'):(D/name).mkdir()
 for name in('owned_driver09.py','with_correctness_namespace_09.py','source-freeze.json'):shutil.copy2(R/'control'/name,C/name)
 e['paths'].update(root=str(D),source=str(D/'source'),control=str(C),native_source=str(D/'native_source'),build=str(D/'build'),binaries=str(D/'binaries'),run=str(D/'run'),temporary=str(D/'temporary'),wrapper=str(C/'with_correctness_namespace_09.py'))
 for path in(R,B/s['validation'],B/'tangent-precision-02'):add_ro(e,path)
 e['host']={'hostname':socket.gethostname(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
 e['reserved_cpu_note']='One separately attributed archived native check onCPU24/one thread/8GiB/2h. Distinct preparation03 and preparation04 references/fixed states preserved; no fitting or regenerated initialization.'
 names=['owned_driver09.py','with_correctness_namespace_09.py',s['worker'],s['controller'],'stage_nominal_compensation_checks01.py']
 if a.mode=='single':names+=['compensation_native_regression01.py','tangent_compensated_quadrature.cpp']
 for name in names:e['runtime_artifacts']['compensation_check_'+name]=pin(C/name)
 save(C/'execution.json',e)
 spec=importlib.util.spec_from_file_location('owned',C/'owned_driver09.py');o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o);o.load_execution(C/'execution.json')
 assert o.source_receipt(D/'source')==json.loads((C/'source-freeze.json').read_text())['source']
 inputs={}
 for name,relative in [('template',s['template']),('initial_orbit',s['reference']+'/nominal.dat'),('initial_text',s['reference']+'/nominal.txt'),('initial_state','initial_state.txt'),('bootstrap','input_bootstrap.dat'),('initialization','initialization.json'),('original_log',s['failure'])]:inputs[name]=pin(original/relative)
 inputs['request']=pin(B/s['validation']/'run/preparation-jobs'/('prefix-'+BAD)/'request.json')
 t=ET.parse(inputs['template']['path']).getroot()
 assert t.findtext('.//PreprocessingVariationalEquation/inputfileOrbit')==inputs['initial_orbit']['path']
 assert t.findtext('.//OrbitPocEvaluateVariational/inputfileInitialState')==inputs['initial_state']['path']
 for name,tag in [('attitude','inputfileStarCamera'),('satellite_model','inputfileSatelliteModel'),('eop','inputfileEOP'),('ephemerides','inputfileEphemerides'),('gravityfield','inputfilePotentialCoefficients')]:
  canonical=t.find('.//'+tag).text;inputs[name]={'path':canonical,'sha256':sha(o.resolved_host_path(canonical,e))}
 result=B/'tangent-precision-02/run/build-result/result.json';built=json.loads(result.read_text())
 assert built['status']=='built_precision_candidate'and built['baseline_relinked_sha256']=='a66949456ad67b816d09f2f14df792c68c2685f5304139499e4d90092fd75b22'
 assert built['source_after']['misc/orbitPoc/sixStateTangent.h']=='9a46f04591de8b8956cb6af0888936ace7f35688cef778861a99a859a65cdef0'
 native=Path(built['native']['path']);assert pin(native)==built['native'];inputs['build_result']=pin(result)
 if a.mode=='single':inputs['supplemental_fixture']=pin(C/'tangent_compensated_quadrature.cpp')
 p={'schema':s['schema'],'execution':pin(C/'execution.json'),'driver':pin(C/'owned_driver09.py'),'worker':pin(C/s['worker']),'controller':pin(C/s['controller']),'native':pin(native),'source_freeze':pin(C/'source-freeze.json'),'inputs':inputs,'output':str(D/'run/replay'),'global_lock':'/mnt/seagate10tb/orbit-v31-correctness-10-florianpfaff/control/candidate09-validation.lock'}
 save(C/'plan.json',p)
 for name,value in e['runtime_artifacts'].items():assert sha(o.resolved_host_path(value['path'],e))==value['sha256'],name
 receipt={'schema':'orbit-poc-nominal-compensation-check-staging-v1','case':a.case,'mode':a.mode,'selection':s,'plan':pin(C/'plan.json'),'execution':pin(C/'execution.json'),'source_freeze':pin(C/'source-freeze.json'),'base_execution':pin(base),'input_attribution':inputs,'native':p['native'],'runtime_pins_verified':len(e['runtime_artifacts']),'mutable_inventory':{name:[str(x)for x in(D/name).iterdir()]for name in('native_source','build','binaries','run','temporary')},'initialization_recomputed':False,'per_propagation_time_limit_seconds':7200 if a.mode=='single'else600,'outer_time_limit_seconds':7200,'fit_attempts':0,'release_evidence':False,'native_runs':0}
 save(C/'staging.json',receipt);print(json.dumps(receipt,indent=2))
if __name__=='__main__':main()
