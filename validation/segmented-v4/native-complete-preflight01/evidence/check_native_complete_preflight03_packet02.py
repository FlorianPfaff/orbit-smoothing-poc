import json,hashlib,datetime
from pathlib import Path
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');old=B/'native-complete-preflight-02';new=B/'native-complete-preflight-03'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p,h=None):
 if h:assert sha(p)==h
 return json.loads(Path(p).read_bytes())
p=load(new/'control/plan.json','801162ef6f4e7e6c5ae5295c31e2f3df2bf4368631ab3f69540cbc296affe7f3');o=load(old/'control/plan.json','cf35f2bbaf810f065d79d4f3f41e007e7fb58cb8c72a4d99ad39d8c54217d150');e=load(new/'control/execution.json','4c6569f4adb1b7be42332b303de9bf000e4d3a1e78cba05eaa847eb01f87f927');oe=load(old/'control/execution.json','f0c20575afe310e36524ee3659f1e117ba9f53fbea177e00a51c8c3051aa0056')
for k in p['inputs']:
 if k not in ('installation_request','toolchain'):assert p['inputs'][k]==o['inputs'][k]
for k in ('worker','controller','driver'):assert p[k]['sha256']==o[k]['sha256'] and sha(p[k]['path'])==p[k]['sha256']
a=load(p['inputs']['installation_request']['path'],p['inputs']['installation_request']['sha256']);oa=load(o['inputs']['installation_request']['path'],o['inputs']['installation_request']['sha256']);t=load(p['inputs']['toolchain']['path'],p['inputs']['toolchain']['sha256']);ot=load(o['inputs']['toolchain']['path'],o['inputs']['toolchain']['sha256'])
assert {k:v for k,v in a.items()if k not in ('python','output')}=={k:v for k,v in oa.items()if k not in ('python','output')}
assert {k:v for k,v in t.items()if k!='python'}=={k:v for k,v in ot.items()if k!='python'}
assert a['python']==t['python'] and a['python']['sha256']==oa['python']['sha256']==ot['python']['sha256']=='58f0ee5f4cb0af42a69aed9f122d63cc535fcfa6bca71132a3d0e24be95c4ac8'
assert a['python']['path']==oa['python']['path']+'3.11' and a['output']==oa['output'].replace(str(old),str(new))
path=Path(a['python']['path'])
for row in sorted(e['read_only_bindings'],key=lambda x:-len(x['target'])):
 target=Path(row['target'])
 if path==target or target in path.parents:path=Path(row['source'])/path.relative_to(target);break
assert path.is_file()and not path.is_symlink()and sha(path)==a['python']['sha256']
oldpins=oe['runtime_artifacts'];newpins=e['runtime_artifacts'];assert all(newpins.get(k)==h for k,h in oldpins.items())
assert all(r in e['read_only_bindings']for r in oe['read_only_bindings'])
mut={k:list(Path(e['paths'][k]).iterdir())for k in ('native_source','build','binaries','run','temporary')};assert all(not x for x in mut.values())
for name in ('pipeline.json','native-complete-launch.json'):assert not(new/'control'/name).exists()
assert p['native']==o['native'] and p['global_lock']==o['global_lock']and p['phase']==o['phase']=='prepare'
print(json.dumps({'passed':True,'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'plan':{'path':str(new/'control/plan.json'),'sha256':sha(new/'control/plan.json')},'execution':p['execution'],'python':a['python'],'same_python_bytes':True,'prior_runtime_pins':len(oldpins),'runtime_pins':len(newpins),'additional_runtime_pins':{k:h for k,h in newpins.items()if k not in oldpins},'added_readonly_mappings':[r for r in e['read_only_bindings']if r not in oe['read_only_bindings']],'fresh_mutable_outputs':list(mut),'source_and_controls_unchanged':True,'native_and_lock_unchanged':True,'no_native_work':True},indent=2))
