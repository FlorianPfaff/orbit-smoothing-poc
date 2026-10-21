from pathlib import Path
import datetime, hashlib, importlib.util, json, xml.etree.ElementTree as ET
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff')
C=B/'closure-diagnostic-01/control'; R=C.parent
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def read(p):return json.loads(Path(p).read_bytes())
def check(r):assert sha(r['path'])==r['sha256'];return Path(r['path'])
assert sha(C/'plan.json')=='3c20f3a4c04a3df8bcb68a98ab047f24a87de72a4b2e617ea7508666bf9568dc'
assert sha(C/'execution.json')=='98bf35fa49a37661f4fce112f1dcb20d22ff00a07eaf896a900be2fe94bc5b34'
assert sha(C/'staging.json')=='5af16b671ae869c26a782ca5ea4b117839bd6afa5130487a4c78abe7f0324637'
p=read(C/'plan.json');s=read(C/'staging.json')
for key in ('execution','driver','worker','controller','native','source_freeze'):check(p[key])
spec=importlib.util.spec_from_file_location('reviewed_driver',p['driver']['path']);d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
e=d.load_execution(C/'execution.json');old=read(check(s['base_execution']))
spec=importlib.util.spec_from_file_location('reviewed_worker',p['worker']['path']);w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w);w.validate_plan(p)
assert e['host']==old['host'] and e['build_cpus']==old['build_cpus']==[24,25,26,27] and e['fit_cpu']==old['fit_cpu']==24
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==e['host']['boot_id']=='95156dd4-0d4c-499d-a214-8883a2d650fa'
assert len(e['runtime_artifacts'])==364 and all(e['runtime_artifacts'][k]==v for k,v in old['runtime_artifacts'].items())
assert set(e['runtime_artifacts'])-set(old['runtime_artifacts'])=={'diagnostic_owned_driver09.py','diagnostic_with_correctness_namespace_09.py','diagnostic_run_nominal_profile01.py','diagnostic_replay_nominal_profile01.py'}
resolved=[]
for key,value in e['runtime_artifacts'].items():
    host=d.resolved_host_path(value['path'],e)
    assert sha(host)==value['sha256'],key
    resolved.append({'name':key,'pin':value,'physical_path':str(host)})
freeze=read(p['source_freeze']['path']);assert d.source_receipt(Path(e['paths']['source']))==freeze['source']
assert freeze['source']['sha256']=='8ee869dd82c86833662fad8985e13197a422f6f0faf3628db83573ee8010cd3b'
for name,row in s['input_attribution'].items():
    original=check(row['physical_original']); v=p['inputs'][name]
    actual=d.resolved_host_path(v['path'],e); assert sha(actual)==v['sha256']==sha(original)
    if row['copy'] is not None:
        assert v==row['copy'] and check(v).read_bytes()==original.read_bytes()
    else:
        assert v['path']==row['canonical_original'] and actual==original
assert p['inputs']['request']['sha256']=='fa646eee50d30d6db54a51a40411e1bb81e6ca3b72bee6ea29425e2c6bc9e39d'
assert p['inputs']['initialization']['sha256']=='35cdb2ccdc0cb51fe8bedb7664b1d9f5e8a030d324afc000661dca1e231c4540'
assert p['native']['sha256']=='a66949456ad67b816d09f2f14df792c68c2685f5304139499e4d90092fd75b22'
assert p['global_lock']=='/mnt/seagate10tb/orbit-v31-correctness-10-florianpfaff/control/candidate09-validation.lock'
assert p['output']==str(R/'run/replay') and not Path(p['output']).exists()
assert not (C/'pipeline.json').exists() and not (C/'native-replay.log').exists()
mutable={}
for key in d.MUTABLE_KEYS:
    folder=Path(e['paths'][key]);assert folder==R/key and folder.is_dir() and not folder.is_symlink()
    mutable[key]=[x.name for x in folder.iterdir()];assert not mutable[key]
assert e['read_only_bindings'][:len(old['read_only_bindings'])]==old['read_only_bindings']
extra=e['read_only_bindings'][len(old['read_only_bindings']):]
expected=[{'source':str(B/'validation-03'),'target':str(B/'validation-03')}]
for key,target in [('native_source','preparation'),('build','cache'),('binaries','artifacts'),('run','run'),('temporary','temporary')]:
    expected.append({'source':str(B/'preparation-02/backings'/key),'target':str(B/'validation-03'/target)})
expected.append({'source':str(B/'validation-03/run/validation'),'target':str(B/'validation-03/run/validation')})
assert extra==expected
for row in extra:
    assert Path(row['source']).exists()
    assert all(Path(row['target'])!=Path(e['paths'][k]) and Path(row['target']) not in Path(e['paths'][k]).parents and Path(e['paths'][k]) not in Path(row['target']).parents for k in d.MUTABLE_KEYS)
template=ET.parse(p['inputs']['template']['path']).getroot();raw=ET.tostring(template)
modified=w.tree_for(template,Path(p['inputs']['initial_orbit']['path']),Path(p['inputs']['initial_state']['path']),Path(p['output'])/'iteration-01')
assert ET.tostring(template)==raw
programs=[list(v)[0] for v in modified.findall('program')]
assert programs[0].findtext('orbitPocDerivativeProfile')=='synthetic_complete_v1'
for key in ('orbitPocDerivativeProfile','orbitPocDerivativeDiagnostics'):programs[0].remove(programs[0].find(key))
for original,changed,keys in zip([list(v)[0] for v in template.findall('program')],programs,[['inputfileOrbit','outputfileVariational'],['inputfileVariational','outputfileOrbit','inputfileInitialState'],['inputfile','outputfile']]):
    for key in keys:changed.find(key).text=original.findtext(key)
assert ET.tostring(modified)==raw
init=read(p['inputs']['initialization']['path'])
state=[float(x) for x in Path(p['inputs']['initial_state']['path']).read_text().split()]
assert state==init['fixed_initial_state_si']
assert init['maximum_iterations']==10 and init['position_tolerance_m']==2e-6 and init['velocity_tolerance_m_s']==3e-9
check(s['original_failure'])
print(json.dumps({'schema':'orbit-poc-nominal-profile-diagnostic-packet-independent-review-v1','passed':True,
 'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'plan':pin(C/'plan.json'),'execution':pin(C/'execution.json'),'staging':pin(C/'staging.json'),
 'source_sha256':freeze['source']['sha256'],'input_attribution':s['input_attribution'],'runtime_pin_count':len(resolved),'resolved_runtime':resolved,
 'mutable_inventory':mutable,'read_only_binding_delta':extra,'original_failure':s['original_failure'],
 'fixed_initial_state_si':state,'native':p['native'],'code':{k:p[k] for k in ('worker','controller','driver')},
 'scope':'Exact archived failed48h inputs and unchanged native binary; only declared staged profile, telemetry and output/recurrence paths change. Original failed output remains read-only. No initializer, fit, source edit or native execution occurred during this independent review. Admission and ownership cleanup remain required at launch; diagnostic output requires independent terminal interpretation.'},sort_keys=True))
