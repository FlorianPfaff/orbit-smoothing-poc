from pathlib import Path
import os,json,hashlib,shutil,tarfile,importlib.util,socket
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');D=B/'native-complete-preflight-01';C=D/'control';I=B/'native-complete-inputs-01';R=B/'validation-05';P=B/'preparation-04';BASE=B/'tangent-precision-02'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def save(p,v):
 with Path(p).open('x')as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
base_execution=P/'control/execution.json';assert sha(base_execution)=='98e9ea204c22d176e271141b993338579430df9354bcde5f74a44fb9476efe77';e=json.loads(base_execution.read_text())
# All archives are exact committed source snapshots, extracted once into fresh immutable input slots.
for name in ('installer','fixtures'):
 receipt=json.loads((I/(name+'-receipt.json')).read_text());archive=I/(name+'.tar');assert sha(archive)==receipt['archive']['sha256'];dest=I/name;assert not dest.exists();dest.mkdir()
 with tarfile.open(archive)as t:
  for m in t.getmembers():
   assert not Path(m.name).is_absolute()and'..'not in Path(m.name).parts and(m.isdir()or m.isfile())
   if m.isfile():
    data=t.extractfile(m).read();assert hashlib.sha256(data).hexdigest()==receipt['files'][m.name];out=dest/m.name;out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(data)
 assert {str(p.relative_to(dest)):sha(p)for p in dest.rglob('*')if p.is_file()}==receipt['files']
 assert receipt['commit']=='3bffd21c604cccd1488a01b896c62db88df69af4'
save(I/'repository-inventory.json',{'schema':'orbit-poc-native-installer-repository-inventory-v1','root':str(I/'installer'),'files':json.loads((I/'installer-receipt.json').read_text())['files']})
for name in ('source','native_source','build','binaries','run','temporary'):assert not(D/name).exists(),name
shutil.copytree(R/'source',D/'source')
for name in ('native_source','build','binaries','run','temporary'):(D/name).mkdir()
for name in ('owned_driver09.py','with_correctness_namespace_09.py','source-freeze.json'):shutil.copy2(R/'control'/name,C/name)
e['paths'].update(root=str(D),source=str(D/'source'),control=str(C),native_source=str(D/'native_source'),build=str(D/'build'),binaries=str(D/'binaries'),run=str(D/'run'),temporary=str(D/'temporary'),wrapper=str(C/'with_correctness_namespace_09.py'))
for path in (R,BASE,I,B/'native-source-install-inputs-01'):
 match=[x for x in e['read_only_bindings']if x['target']==str(path)]
 if match:assert match==[{'source':str(path),'target':str(path)}]
 else:e['read_only_bindings'].append({'source':str(path),'target':str(path)})
e['host']={'hostname':socket.gethostname(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()};e['reserved_cpu_note']='Owned CPU24 serial source/fixture preflight only; copied-object baseline relink, pristine installer equality and two supplemental fixtures. No candidate GROOPS compilation, propagation or fitting.'
def host(path):
 p=Path(path)
 rows=sorted(e['read_only_bindings'],key=lambda x:-len(x['target']))
 for row in rows:
  if p==Path(row['target'])or p.is_relative_to(row['target']):return Path(row['source'])/p.relative_to(row['target'])
 return p
def canonical(path):
 p=Path(path)
 rows=sorted(e['read_only_bindings'],key=lambda x:-len(x['source']))
 for row in rows:
  if p==Path(row['source'])or p.is_relative_to(row['source']):return Path(row['target'])/p.relative_to(row['source'])
 return p
def logical_pin(path):return {'path':str(path),'sha256':sha(host(path))}
def identity(path):
 physical=host(path);st=physical.stat();return {'path':str(path),'sha256':sha(physical),'resolved_path':str(canonical(physical.resolve())),'symlink_text':os.readlink(physical)if physical.is_symlink()else None,'device':st.st_dev,'inode':st.st_ino,'bytes':st.st_size}
base_result=BASE/'run/build-result/result.json';assert sha(base_result)=='92dcf754ad42ad22c92b0e0413e86af83fd7d4f9700b69c08c86254022e69224';base=json.loads(base_result.read_text());basepin=pin(base_result)
oldmanifest=json.loads(host(base['original_build_manifest']['path']).read_text());oldroot=Path(oldmanifest['build_command'][oldmanifest['build_command'].index('-S')+1]);oldbuild=Path(base['original_build_manifest']['path']).parent
recipe=I/'native-source-delta01-recipe-inspection01.json';r=json.loads(recipe.read_text());assert r['baseline_result']==basepin
ext=set()
for block in r['all_dependency_blocks']:
 if block.startswith('groops:'):continue
 for line in block.splitlines()[1:]:
  path=line.strip()
  if path and not Path(path).is_relative_to(oldroot):ext.add(path)
save(I/'dependency-inventory.json',{'schema':'orbit-poc-complete-native-external-dependencies-v1','recipe_inventory':pin(recipe),'files':[identity(p)for p in sorted(ext)]})
links={}
for path,h in base['all_original_link_inputs'].items():
 old=Path(path)
 if old.is_relative_to(oldbuild)and str(old.relative_to(oldbuild))in base['original_object_sha256']:p=BASE/'build'/old.relative_to(oldbuild)
 else:p=old;assert sha(host(p))==h
 links[str(p)]=identity(p)
assert len(links)==637
save(I/'link-inventory.json',{'schema':'orbit-poc-current-native-link-inputs-v1','baseline_result':basepin,'inputs':[links[x]for x in sorted(links)]})
overlay=json.loads((I/'installer/groops/extension/wide_tangent/manifest.json').read_text());changes=[]
for row in overlay['files']:
 name=row['path'];old=base['source_after'].get(name);assert old==row['original_sha256'];payload=I/'installer/groops/extension/wide_tangent/proposed'/name;assert sha(payload)==row['proposed_sha256'];changes.append({'relative':name,'action':'add'if old is None else'replace','old_sha256':old,'new_file':pin(payload)})
save(I/'source-delta.json',{'schema':'orbit-poc-native-source-delta-v1','baseline_result':basepin,'base_source_sha256':hashlib.sha256(json.dumps(base['source_after'],sort_keys=True,separators=(',',':')).encode()).hexdigest(),'changes':changes})
prefix=Path(e['paths']['prefix']);python=canonical(host(e['paths']['python']).resolve());tool={'schema':'orbit-poc-native-complete-toolchain-v1','python':logical_pin(python),'cmake':logical_pin(oldmanifest['build_command'][0]),'ninja':logical_pin('/usr/bin/ninja'),'cxx':logical_pin(prefix/'bin/x86_64-conda-linux-gnu-c++'),'cc':logical_pin(prefix/'bin/x86_64-conda-linux-gnu-cc'),'fc':logical_pin(prefix/'bin/x86_64-conda-linux-gnu-gfortran'),'git':logical_pin('/usr/bin/git')};save(I/'toolchain.json',tool)
fix=I/'fixtures';save(I/'fixture-inventory.json',{'schema':'orbit-poc-native-wide-supplemental-fixtures-v1','interpolation':pin(fix/'tests/fixtures/wide_interpolation_fixture.cpp'),'serializer':pin(fix/'tests/fixtures/wide_interpolation_export_fixture.cpp'),'decoder':pin(fix/'src/orbit_poc/segmented/tangent_export.py')})
pristine=B/'native-source-install-inputs-01';provenance=json.loads((pristine/'receipt.json').read_text());gitdir=B/'engineering-02/groops-source/.git'
request={'schema':'orbit-poc-native-installer-equivalence-request-v1','archive':provenance['archive'],'archive_provenance':pin(pristine/'receipt.json'),'python':tool['python'],'git':tool['git'],'git_head':pin(gitdir/'HEAD'),'git_dir':str(gitdir),'repository_inventory':pin(I/'repository-inventory.json'),'baseline_result':basepin,'source_delta':pin(I/'source-delta.json'),'output':str(D/'native_source/reproduction')};save(I/'installation-request.json',request)
inputs={'baseline_result':basepin,'source_delta':pin(I/'source-delta.json'),'recipe_inventory':pin(recipe),'link_inventory':pin(I/'link-inventory.json'),'dependency_inventory':pin(I/'dependency-inventory.json'),'utility':pin(I/'build_native_source_delta01.py'),'installation_helper':pin(I/'verify_native_installer_equivalence02.py'),'installation_request':pin(I/'installation-request.json'),'toolchain':pin(I/'toolchain.json'),'fixture_inventory':pin(I/'fixture-inventory.json')}
for name in ('owned_driver09.py','with_correctness_namespace_09.py','run_native_complete01.py','build_native_complete01.py'):e['runtime_artifacts']['native_complete_'+name]=pin(C/name)
for key,value in inputs.items():e['runtime_artifacts']['native_complete_input_'+key]=value
save(C/'execution.json',e)
spec=importlib.util.spec_from_file_location('owned',C/'owned_driver09.py');o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o);o.load_execution(C/'execution.json');assert o.source_receipt(D/'source')==json.loads((C/'source-freeze.json').read_text())['source']
p={'schema':'orbit-poc-native-complete-build-plan-v1','phase':'prepare','execution':pin(C/'execution.json'),'driver':pin(C/'owned_driver09.py'),'worker':pin(C/'build_native_complete01.py'),'controller':pin(C/'run_native_complete01.py'),'native':base['native'],'source_freeze':pin(C/'source-freeze.json'),'inputs':inputs,'output':str(D/'run/preflight'),'global_lock':'/mnt/seagate10tb/orbit-v31-correctness-10-florianpfaff/control/candidate09-validation.lock'};save(C/'plan.json',p)
for key,value in e['runtime_artifacts'].items():assert sha(o.resolved_host_path(value['path'],e))==value['sha256'],key
receipt={'schema':'orbit-poc-native-complete-preflight-staging-v1','plan':pin(C/'plan.json'),'execution':pin(C/'execution.json'),'source_freeze':pin(C/'source-freeze.json'),'inputs':inputs,'runtime_pin_count':len(e['runtime_artifacts']),'external_compile_dependencies':len(ext),'link_dependencies':len(links),'installer_commit':'3bffd21c604cccd1488a01b896c62db88df69af4','source_files':len(json.loads((C/'source-freeze.json').read_text())['source']['files']),'compiled':False,'mutable_inventory':{n:[str(x)for x in(D/n).iterdir()]for n in('native_source','build','binaries','run','temporary')}};save(C/'staging.json',receipt);print(json.dumps(receipt,indent=2))
