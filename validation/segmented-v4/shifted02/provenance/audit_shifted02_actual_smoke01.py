from pathlib import Path
import json,hashlib,datetime,importlib.util
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');R=B/'shifted-diagnostic-02';C=R/'control';S=R/'staging/runtime-smoke-01'
def art(p):
 b=Path(p).read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
def checked(pin):
 a=art(pin['path']);assert a['sha256']==pin['sha256'] and ('bytes' not in pin or a['bytes']==pin['bytes']);return json.loads(Path(pin['path']).read_text())
j=checked({'path':str(S/'process.json'),'sha256':'369fa707a7e3bbaa3d3cffddfebed4838e24d2c75154d002fe14c3a08b79dc0d'});r=checked(j['result']);assert j['result']['sha256']=='3139a29191453a12b2950eb0abe2b902c847de8bb6f3982bd216fd5b51c4c13c'
p=checked(j['original_plan']);e=checked(j['original_execution']);derived=checked(j['derived_execution'])
assert j['original_plan']['sha256']=='256dc7655b6f6888dae2760d86d62d6b86f4e63662fbc0f1dd24361bbfdc8eb5' and j['original_execution']['sha256']=='8e9be3c485ae53cec8fb99c2e57bf7a04ce508b64b4dfb87d9d9def2649c7f93'
assert j['helper']['sha256']==art(j['helper']['path'])['sha256']=='d8bfc99cc66f75a4aa16d681efffc4ca42ad26357fe5f2842e0e68eeab18795b'
assert {k:v for k,v in e.items() if k!='paths'}=={k:v for k,v in derived.items() if k!='paths'}
mutable=('native_source','build','binaries','run','temporary')
for k,v in e['paths'].items():assert derived['paths'][k]==(str(S/k) if k in mutable else v)
spec=importlib.util.spec_from_file_location('reviewed_runner',p['runner']['path']);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);assert m.load_plan(C/'plan.json',j['original_plan']['sha256'])==p
q=dict(p,execution=j['derived_execution']);assert j['argv']==m.runtime_command(derived,q,'log_drag_ou','before')
assert j['status']==r['status']=='passed' and j['returncode']==0 and j['interrupted_or_timeout'] is False and j['elapsed_seconds']<600
assert j['physical_evaluations']==j['constrained_solves']==0 and r['full_runtime_verified'] is True
assert r['config']==p['config'] and r['solver']==p['solver'] and r['source_sha256']=='68e17e5b5ebe6fe22a47b9c6213c89397cfb80e25cc5e033da2621fc0aa44474'
assert r['native']['sha256']=='a66949456ad67b816d09f2f14df792c68c2685f5304139499e4d90092fd75b22' and r['source_root']==str(B/'validation-04/source')
assert j['final_cleanup']['verified'] and not j['final_cleanup']['errors'] and j['cleanup']['verified'] and j['cleanup']['returncode']==0 and not j['cleanup']['live_owned_processes'] and j['cleanup']['forced'] is False
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();assert boot==j['admission']['boot_id']=='95156dd4-0d4c-499d-a214-8883a2d650fa'
ids={(x['pid'],x['start_ticks']):x for x in [j['admission']['driver_identity'],j['process'],*j['cleanup']['identities'],*(x for c in j['final_cleanup']['commands'] for x in c['identities'])]};absent=[]
for (pid,ticks),x in ids.items():
 f=Path('/proc')/str(pid)/'stat'
 try:
  tail=f.read_text().rsplit(')',1)[1].split();actual=int(tail[19]);assert actual!=ticks or tail[0]=='Z';absent.append({'pid':pid,'start_ticks':ticks,'current_start_ticks':actual,'current_state':tail[0]})
 except FileNotFoundError:absent.append({'pid':pid,'start_ticks':ticks,'absent':True})
outputs={k:not Path(e['paths'][k]).exists() and not Path(e['paths'][k]).is_symlink() for k in mutable};assert all(outputs.values())
for name in ('pipeline.json','diagnostic-launch.json'):assert not (C/name).exists()
print(json.dumps({'passed':True,'observed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'process':art(S/'process.json'),'result':art(S/'run/runtime-log_drag_ou-before.json'),'plan':art(C/'plan.json'),'execution':art(C/'execution.json'),'actual_command':j['argv'],'elapsed_seconds':j['elapsed_seconds'],'current_boot_id':boot,'owned_process_absence':absent,'production_outputs_absent':outputs,'physical_evaluations':0,'constrained_solves':0,'scope':'Exact actual read-only runtime smoke, scratch-only execution delta and owned cleanup checked without repeating bulk runtime hashing. Unchanged numerical diagnostic still unlaunched.'},indent=2))
