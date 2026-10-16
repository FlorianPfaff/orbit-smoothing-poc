from pathlib import Path
import json,hashlib,datetime,importlib.util
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');D=B/'tangent-capture-03';C=D/'control';R=D/'run/build-result'
def pin(p):
 p=Path(p);h=hashlib.sha256()
 with p.open('rb')as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return dict(path=str(p),sha256=h.hexdigest(),bytes=p.stat().st_size)
def read(p):return json.loads(Path(p).read_text())
p=read(C/'plan.json');e=read(C/'execution.json');j=read(C/'pipeline.json');r=read(R/'result.json')
assert pin(C/'plan.json')['sha256']=='98f9cc2e933b55581c4efeb0484b5f45f6e965a6d1d138126af4a893c3cc9220'
assert pin(C/'execution.json')['sha256']=='20012eee20f71df16277ec24baa8fbc59ef96a7d0e2ff29f4530dcac35bb958a'
assert j['status']=='passed_diagnostic' and j['returncode']==0 and j['final_cleanup']['verified'] and not j['final_cleanup']['errors']
assert r['status']=='built_diagnostic_only' and r['fit_attempts']==0 and r['release_evidence']is False
assert r['baseline_relinked_sha256']==p['native']['sha256']=='a66949456ad67b816d09f2f14df792c68c2685f5304139499e4d90092fd75b22'
assert pin(r['native']['path'])['sha256']==r['native']['sha256']=='e444cec3fc972fac1800ab0d41e223dfc9eaee761c8d85b34588cec1702b897c'
assert pin(r['reader']['path'])['sha256']==r['reader']['sha256']=='c1829b65dc7115297a273e7269cccb4e803e899267bfbd40e5d34f905fd90cd5'
spec=importlib.util.spec_from_file_location('owned',p['driver']['path']);o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o)
for item in p['inputs'].values():assert pin(o.resolved_host_path(item['path'],e))['sha256']==item['sha256']
assert pin(p['native']['path'])['sha256']==p['native']['sha256']
manifest=read(p['inputs']['original_build_manifest']['path']);assert {'source/'+k:v for k,v in r['source_before'].items()}==manifest['patched_source']['files']
changed={k for k,v in r['source_after'].items()if v!=r['source_before'][k]};assert changed=={'misc/orbitPoc/stagedVariationalBody.h'}
ns=D/'native_source/source';actual={str(q.relative_to(ns)):pin(q)['sha256']for q in ns.rglob('*')if q.is_file()};assert actual==r['source_after']
old=(B/'engineering-02/groops-source/source/misc/orbitPoc/stagedVariationalBody.h').read_bytes();new=(ns/'misc/orbitPoc/stagedVariationalBody.h').read_bytes();block=Path(p['inputs']['capture_block']['path']).read_bytes();assert new.count(block)==1 and new.replace(block,b'')==old
assert hashlib.sha256(old).hexdigest()=='1cace042d5deffac657cc68b9be08de4dc607fba2f8028ac1440e4446fb5d500'
assert r['reused_object_count']==610 and len(r['original_object_sha256'])==611 and len(r['all_original_link_inputs'])==637
inspection=read(p['inputs']['recipe_inspection']['path']);assert {q['path']:q['sha256']for q in inspection['original_link_input_pins']}==r['all_original_link_inputs']
assert set(r['source_before'])==set(r['source_after']) and len(actual)==1131
assert r['compile_command'][0]==r['reader_compile_command'][0] and all(flag in r['compile_command'] and flag in r['reader_compile_command']for flag in ('-O3','-DNDEBUG','-std=gnu++17'))
assert o.source_receipt(D/'source')==read(p['source_freeze']['path'])['source']
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==j['admission']['boot_id']==e['host']['boot_id']
ids={(q['pid'],q['start_ticks'])for q in[j['admission']['driver_identity'],*j['cleanup']['identities']]};absences=[]
for pid,start in sorted(ids):
 try:
  now=o.proc(pid);assert now['start_ticks']!=start or now['state']=='Z';absences.append(dict(pid=pid,start_ticks=start,non_live=True))
 except(FileNotFoundError,ProcessLookupError):absences.append(dict(pid=pid,start_ticks=start,non_live=True,absent=True))
print(json.dumps(dict(schema='orbit-poc-tangent-capture-build03-terminal-independent-readback-v1',passed=True,observed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),plan=pin(C/'plan.json'),execution=pin(C/'execution.json'),pipeline=pin(C/'pipeline.json'),result=pin(R/'result.json'),baseline_relinked_sha256=r['baseline_relinked_sha256'],native=r['native'],reader=r['reader'],source_files_verified=1131,python_source_files_verified=384,only_changed_native_header=r['changed_native_file'],installed_original_header_sha256=hashlib.sha256(old).hexdigest(),candidate_header_sha256=hashlib.sha256(new).hexdigest(),reused_objects=610,pinned_link_inputs=637,compiler_version=r['compiler_version'],native_compile_command=r['compile_command'],reader_compile_command=r['reader_compile_command'],reader_libraries=r['reader_libraries'],owned_identities_non_live=absences,elapsed_seconds=j['elapsed_seconds'],finished_at=j['finished_at'],scope='Diagnostic build attribution only. Exact original baseline relink,installed-hook preservation,reader/compiler provenance and owned cleanup verified. No propagated scientific result or release readiness inferred.'),indent=2))
