from pathlib import Path
import hashlib,json,sys,datetime
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');C=B/'preparation-03/control';S=B/'validation-04/staging/preparation-03/startup-01'
def pin(p):return {'path':str(p),'sha256':hashlib.sha256(Path(p).read_bytes()).hexdigest(),'bytes':Path(p).stat().st_size}
def checked(x):
 p=Path(x['path']);a=pin(p);assert a['sha256']==x['sha256'] and ('bytes' not in x or a['bytes']==x['bytes']),p
 return json.loads(p.read_text())
p=checked({'path':str(S/'process.json'),'sha256':sys.argv[1]})
r=checked(p['result']);assert p['result']['sha256']==sys.argv[2]
for x in (p,r):assert x['status']=='passed' and x['physical_propagations']==x['benchmark_fits']==0
assert p['returncode']==0 and p['interrupted_or_timeout'] is False and p['elapsed_seconds']<900
assert p['final_cleanup']['verified'] is True and p['final_cleanup']['errors']==[]
assert p['cleanup']['verified'] is True and p['cleanup']['live_owned_processes']==[] and p['cleanup']['returncode']==0 and p['cleanup']['forced'] is False
m=checked(p['plan']);q=checked(p['probe_plan']);e=checked(p['execution']);derived=checked(p['derived_execution'])
assert p['plan']['sha256']=='8f6b9e5ea56ac31b14ecf7120194146f899ca3fdb83aeb98429a781b4ae84238'
assert p['probe_plan']['sha256']=='80e1ee99f66052203602bcb6e695058cad585b52a8388992e959808140da65de'
assert p['execution']['sha256']=='d2297c51648d9ba1f3644cbdae36ba5a95ad289d941ec4823aca6817af923236'
assert {k:v for k,v in e.items() if k!='paths'}=={k:v for k,v in derived.items() if k!='paths'}
for k,v in e['paths'].items():assert derived['paths'][k]==(str(S/k) if k in ('native_source','build','binaries','run','temporary') else v)
assert p['argv']==[e['runtime_artifacts']['control_python']['path'],e['paths']['wrapper'],'--execution',str(S/'execution.json'),'--execution-sha256',p['derived_execution']['sha256'],'--','/usr/bin/taskset','-c','24',e['paths']['python'],q['helper']['path'],'--plan',str(C/'probe-plan.json'),'--sha256',p['probe_plan']['sha256']]
assert r['config']==q['config'] and q['config']['sha256']=='e23eb3a1b4eafc6c1c279183292513b87e64a366061ac6ef645987700c193fac' and r['source_sha256']==q['source_sha256']=='68e17e5b5ebe6fe22a47b9c6213c89397cfb80e25cc5e033da2621fc0aa44474'
assert len(r['cache_products'])==20 and len(r['flight_sources'])==4 and len(r['validation']['checks'])==14 and r['validation']['status']=='passed'
products=checked(q['products']);seed=checked(q['cache_seed'])
assert all(Path(x['path']).parent==B/'validation-04/cache/gnss' for x in r['cache_products'])
# The probe's cached product list is already pinned to the original source products by its unchanged reviewed code.
assert len({x['path'] for x in r['cache_products']})==20
assert {x['role'] for x in r['tudat_startup']['imports']}=={'tudatpy','environment_setup','propagation_setup','simulator','spice'}
assert r['tudat_startup']['status']=='passed' and r['tudat_startup']['propagations']==0 and r['tudat_startup']['truth_script_loaded_without_run'] is True and r['tudat_stderr']==''
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();assert boot==p['admission']['boot_id']=='95156dd4-0d4c-499d-a214-8883a2d650fa'
identities={}
for x in [p['admission']['driver_identity'],p['process'],*p['cleanup']['identities'],*(x for command in p['final_cleanup']['commands'] for x in command['identities'])]:identities[(x['pid'],x['start_ticks'])]=x
absence=[]
for (pid,ticks),x in identities.items():
 path=Path('/proc')/str(pid)/'stat'
 try:
  fields=path.read_text().rsplit(')',1)[1].split();actual=int(fields[19]);assert actual!=ticks,(pid,ticks);absence.append({'pid':pid,'start_ticks':ticks,'current_start_ticks':actual})
 except FileNotFoundError:absence.append({'pid':pid,'start_ticks':ticks,'absent':True})
for n in ('manifest.json','attempts'):assert not (B/'validation-04/run'/n).exists()
for n in ('pipeline.json','preparation-launch.json'):assert not (C/n).exists()
assert pin(S/'process.json')['sha256']==sys.argv[1] and pin(S/'temporary/probe-result/result.json')['sha256']==sys.argv[2]
reuse=r['actual_cache_reuse'];assert reuse['example_sources']==56 and reuse['flight_sources']==33 and reuse['network_download_allowed'] is False
expected=[v for k,v in e['runtime_artifacts'].items() if k.startswith('preparation03_verification_record_')]
assert {x['path']:x['sha256'] for x in reuse['product_source_records']}=={x['path']:x['sha256'] for x in expected} and len(expected)==len(reuse['product_source_records'])==20
assert len(p['cleanup']['identities'])>=3
run=B/'validation-04/run';assert {x.name for x in run.iterdir()}=={'plan.json','validation','.segmented.lock'}
lock=run/'.segmented.lock';assert not lock.is_symlink() and lock.is_file() and lock.stat().st_size==0
assert not (C/'preparation-launch.json').exists() and not (C/'pipeline.json').exists()
print(json.dumps({'schema':'orbit-poc-preparation-startup-independent-review-v1','passed':True,'process':pin(S/'process.json'),'result':pin(S/'temporary/probe-result/result.json'),'plan':pin(C/'smoke-plan.json'),'execution':pin(C/'execution.json'),'probe_plan':pin(C/'probe-plan.json'),'observed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'current_boot_id':boot,'owned_process_absence':absence,'elapsed_seconds':p['elapsed_seconds'],'checks':{'exact_process_and_result_bytes':True,'actual_command_and_five_scratch_only_mounts':True,'runtime_and_context_identity':True,'original_four_flight_inputs_readable':True,'twenty_product_cache_readable':True,'twenty_offline_product_records':True,'actual_frozen_auxiliary_reuse_56_and_33':True,'tudat_import_and_truth_script_loaded_without_run':True,'successful_exit_and_owned_cleanup':True,'generation_and_fit_outputs_absent':True,'all_fourteen_validation_context_checks_unchanged':True},'physical_propagations':0,'benchmark_fits':0,'scope':'Actual owned preparation03 startup passed with the matching completed validation04 context, four flight inputs, 89 auxiliary sources, and 20 product records. Preparation launch still requires current-host admission and exclusive lock. This does not establish generation or benchmark completion.'},sort_keys=True))
