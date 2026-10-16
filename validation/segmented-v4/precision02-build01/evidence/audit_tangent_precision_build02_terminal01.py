from pathlib import Path
import json,hashlib,datetime,importlib.util
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');D=B/'tangent-precision-02';C=D/'control';R=D/'run/build-result'
def pin(p):
 p=Path(p);h=hashlib.sha256()
 with p.open('rb')as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return dict(path=str(p),sha256=h.hexdigest(),bytes=p.stat().st_size)
def read(p):return json.loads(Path(p).read_text())
p=read(C/'plan.json');e=read(C/'execution.json');j=read(C/'pipeline.json');r=read(R/'result.json')
assert pin(C/'plan.json')['sha256']=='09f659c3a5fb3719a4cb46e6b76194f9317e6f379653ec21e5828607ba088e53'
assert pin(C/'execution.json')['sha256']=='89814a08b267b3a5c23bf5e188175095c7a4e86b4936de0b063513af6d13a7b8'
assert pin(C/'sixStateTangent-compensated-native01.h')['sha256']=='9a46f04591de8b8956cb6af0888936ace7f35688cef778861a99a859a65cdef0'
assert j['status']=='passed_diagnostic'and j['returncode']==0 and j['final_cleanup']['verified']and not j['final_cleanup']['errors']
assert r['status']=='built_precision_candidate'and r['fit_attempts']==0 and r['release_evidence']is False
assert r['baseline_relinked_sha256']==p['native']['sha256']=='a66949456ad67b816d09f2f14df792c68c2685f5304139499e4d90092fd75b22'
assert pin(r['native']['path'])['sha256']==r['native']['sha256']
spec=importlib.util.spec_from_file_location('owned',p['driver']['path']);o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o)
spec=importlib.util.spec_from_file_location('worker',p['worker']['path']);w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
for item in p['inputs'].values():assert pin(o.resolved_host_path(item['path'],e))['sha256']==item['sha256']
assert pin(p['native']['path'])['sha256']==p['native']['sha256']
manifest=read(p['inputs']['original_build_manifest']['path']);assert {'source/'+k:v for k,v in r['source_before'].items()}==manifest['patched_source']['files']
assert set(r['source_before'])==set(r['source_after'])
changed={k for k,v in r['source_after'].items()if v!=r['source_before'][k]};assert changed=={'misc/orbitPoc/sixStateTangent.h'}
ns=D/'native_source/source';actual={str(q.relative_to(ns)):pin(q)['sha256']for q in ns.rglob('*')if q.is_file()};assert actual==r['source_after']and len(actual)==1131
original=B/'engineering-02/groops-source/source';actualold={str(q.relative_to(original)):pin(q)['sha256']for q in original.rglob('*')if q.is_file()};assert actualold==r['source_before']
assert (ns/'misc/orbitPoc/sixStateTangent.h').read_bytes()==(C/'sixStateTangent-compensated-native01.h').read_bytes()
assert pin(ns/'misc/orbitPoc/sixStateTangent.h')['sha256']=='9a46f04591de8b8956cb6af0888936ace7f35688cef778861a99a859a65cdef0'
assert pin(ns/'misc/orbitPoc/stagedVariationalBody.h')['sha256']=='1cace042d5deffac657cc68b9be08de4dc607fba2f8028ac1440e4446fb5d500'
assert r['reused_object_count']==584 and len(r['original_object_sha256'])==611 and len(r['all_original_link_inputs'])==637
inspection=read(p['inputs']['recipe_inspection']['path']);commands,link=w.recipes(inspection,original.parent,D/'native_source');assert commands==r['compile_commands']and link==r['link_command']and len(commands)==27
actual_changed={name for name,digest in r['original_object_sha256'].items()if pin(D/'build'/name)['sha256']!=digest}
assert actual_changed==set(r['changed_objects'])and 0<len(actual_changed)<=27 and actual_changed<=set(commands)
assert set(r['rebuilt_objects'])==set(commands)
for name,digest in r['all_original_link_inputs'].items():assert pin(o.resolved_host_path(name,e))['sha256']==digest
assert all(flag in argv for argv in commands.values()for flag in ['-O3','-DNDEBUG','-std=gnu++17'])
assert o.source_receipt(D/'source')==read(p['source_freeze']['path'])['source']
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==j['admission']['boot_id']==e['host']['boot_id']
ids={(q['pid'],q['start_ticks'])for q in[j['admission']['driver_identity'],*j['cleanup']['identities']]};absences=[]
for pid,start in sorted(ids):
 try:
  now=o.proc(pid);assert now['start_ticks']!=start or now['state']=='Z';absences.append(dict(pid=pid,start_ticks=start,non_live=True))
 except(FileNotFoundError,ProcessLookupError):absences.append(dict(pid=pid,start_ticks=start,non_live=True,absent=True))
print(json.dumps(dict(schema='orbit-poc-tangent-precision-build02-terminal-independent-readback-v1',passed=True,observed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),plan=pin(C/'plan.json'),execution=pin(C/'execution.json'),pipeline=pin(C/'pipeline.json'),result=pin(R/'result.json'),baseline_relinked_sha256=r['baseline_relinked_sha256'],native=r['native'],source_files_verified=1131,python_source_files_verified=384,only_changed_native_header=r['changed_native_file'],candidate_header_sha256=pin(ns/'misc/orbitPoc/sixStateTangent.h')['sha256'],recompiled_objects=27,changed_objects=len(actual_changed),reused_objects=584,pinned_link_inputs_verified=637,compiler_version=r['compiler_version'],owned_identities_non_live=absences,elapsed_seconds=j['elapsed_seconds'],finished_at=j['finished_at'],scope='Native precision-candidate build attribution only. Originala669 baseline,637link inputs/source, installed export hook and cleanup verified. No propagated scientific result or release readiness inferred.'),indent=2))
