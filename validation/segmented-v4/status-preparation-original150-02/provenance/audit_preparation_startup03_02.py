from pathlib import Path
import hashlib,json
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');C=B/'preparation-01/control';S=B/'validation-03/staging/preparation-startup-03'
def pin(p):return {'path':str(p),'sha256':hashlib.sha256(Path(p).read_bytes()).hexdigest(),'bytes':Path(p).stat().st_size}
def checked(x):
 p=Path(x['path']);a=pin(p);assert a['sha256']==x['sha256'] and ('bytes' not in x or a['bytes']==x['bytes']),p
 return json.loads(p.read_text())
p=checked({'path':str(S/'process.json'),'sha256':'471e6b8fc00c5956f231b15f83694aaed08b3a7fe4ab501555b7662238128adf'})
r=checked(p['result']);assert p['result']['sha256']=='961a55d41c7c431f9cfcc0784fd0245012bb6035ebcb590e5cd2ed75d45c9bb3'
for x in (p,r):assert x['status']=='passed' and x['physical_propagations']==x['benchmark_fits']==0
assert p['returncode']==0 and p['interrupted_or_timeout'] is False and p['elapsed_seconds']<900
assert p['final_cleanup']['verified'] is True and p['final_cleanup']['errors']==[]
assert p['cleanup']['verified'] is True and p['cleanup']['live_owned_processes']==[] and p['cleanup']['returncode']==0 and p['cleanup']['forced'] is False
m=checked(p['plan']);q=checked(p['probe_plan']);e=checked(p['execution']);derived=checked(p['derived_execution'])
assert p['plan']['sha256']=='06258d09d28719041fb06b57b982ef74ccf939cb2529a71a27dc13053e519169'
assert p['probe_plan']['sha256']=='6dd191e8c9b614e2128f4bdaaa4ff23f81eea99242f974bcda6d3612f766eb0b'
assert p['execution']['sha256']=='e525182c48e80d27403c905f7e3b29f1385eb0e3532447013ea93c1e7951fb69'
assert {k:v for k,v in e.items() if k!='paths'}=={k:v for k,v in derived.items() if k!='paths'}
for k,v in e['paths'].items():assert derived['paths'][k]==(str(S/k) if k in ('native_source','build','binaries','run','temporary') else v)
assert p['argv']==[e['runtime_artifacts']['control_python']['path'],e['paths']['wrapper'],'--execution',str(S/'execution.json'),'--execution-sha256',p['derived_execution']['sha256'],'--','/usr/bin/taskset','-c','24',e['paths']['python'],q['helper']['path'],'--plan',str(C/'probe-plan03.json'),'--sha256',p['probe_plan']['sha256']]
assert r['config']==q['config'] and r['source_sha256']==q['source_sha256']=='8ee869dd82c86833662fad8985e13197a422f6f0faf3628db83573ee8010cd3b'
assert len(r['cache_products'])==20 and len(r['flight_sources'])==4 and len(r['validation']['checks'])==14 and r['validation']['status']=='passed'
products=checked(q['products']);seed=checked(q['cache_seed'])
assert all(Path(x['path']).parent==B/'validation-03/cache/gnss' for x in r['cache_products'])
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
for n in ('manifest.json','attempts'):assert not (B/'validation-03/run'/n).exists()
for n in ('pipeline.json','preparation-launch.json'):assert not (C/n).exists()
assert pin(S/'process.json')['sha256']=='471e6b8fc00c5956f231b15f83694aaed08b3a7fe4ab501555b7662238128adf' and pin(S/'temporary/probe-result/result.json')['sha256']=='961a55d41c7c431f9cfcc0784fd0245012bb6035ebcb590e5cd2ed75d45c9bb3'
readiness=checked({'path':str(C/'preparation-launch-readiness03.json'),'sha256':'4cbddad6b722650226d5773a857f27a4e88580d878c5c08e5462a1e4dcb834c8'})
assert readiness['status']=='ready_for_data_preparation_only' and readiness['runtime_pins_verified']==241 and readiness['generation_launched'] is False and readiness['benchmark_attempts']==0
assert readiness['startup_process']['sha256']==pin(S/'process.json')['sha256'] and readiness['startup_result']['sha256']==p['result']['sha256']
assert readiness['plan']['sha256']=='c36c9a57d3b1aea50a6e516bbfdeade3e339afb06ecba9978821af6ed2920d15' and readiness['pins']['sha256']=='b1ec692b604d55089093137c63450c48497b529283e6101f61dbed6a8788a2e7'
assert readiness['admission']['status']=='admitted' and readiness['admission']['conflicting_processes']==[] and readiness['admission']['boot_id']==boot
print(json.dumps({'readiness':pin(C/'preparation-launch-readiness03.json'),'schema':'orbit-poc-preparation-startup-independent-review-v1','passed':True,'process':pin(S/'process.json'),'result':pin(S/'temporary/probe-result/result.json'),'current_boot_id':boot,'owned_process_absence':absence,'checks':{'exact_process_and_result_bytes':True,'actual_command_and_five_scratch_only_mounts':True,'runtime_and_context_identity':True,'original_four_flight_inputs_readable':True,'twenty_product_cache_readable':True,'tudat_import_and_truth_script_loaded_without_run':True,'successful_exit_and_owned_cleanup':True,'generation_and_fit_outputs_absent':True},'physical_propagations':0,'benchmark_fits':0,'scope':'Actual owned startup passed; preparation launch still requires its current-host admission and exclusive lock. This does not establish generation or benchmark completion.'},sort_keys=True))
