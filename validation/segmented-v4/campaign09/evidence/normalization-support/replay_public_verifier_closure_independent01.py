from pathlib import Path
import json,hashlib,importlib.util,datetime
C=Path('/mnt/d/orbit-segmented-v4/control');S=C/'direct-sealing05-terminal01/sealed';Q=C/'public-verifier-closure-census01'
def pin(p):
 p=Path(p);return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
summary=json.loads((Q/'summary01.json').read_text());assert pin(Q/'summary01.json')['sha256']=='1cf15d472fb1f1cc9e7f89e0b434a2011a34f2a47984fefb151280027ca3da12';assert pin(Q/'stdout01.json')['sha256']=='762a35d6cc8defe753b2989c4dc7ecc6f8901d5470aba2d023805daa9c6ce93b'
census=json.loads((Q/'stdout01.json').read_text());mount=json.loads((S/'mount-plan.json').read_text());allow=json.loads((S/'allowlist.json').read_text())
assert pin(S/'mount-plan.json')['sha256']==census['mount_plan']['sha256'] and pin(S/'allowlist.json')['sha256']==census['allowlist']['sha256']
source=C/'symlink-closure-draft02/plan_segmented_fit_namespace02.py';assert pin(source)['sha256']=='2a00bb3fa57bef3c034e3ab96348c6f720d25af5473e65efb9a5a6dc5a7d68d2';spec=importlib.util.spec_from_file_location('review_planner',source);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
links={x['path']:x['target'] for x in mount['canonical_symlinks']};links.update({'/usr/lib64/'+name:'/usr/lib/x86_64-linux-gnu/'+name for name in ['libc.so.6','libdl.so.2','libm.so.6','libmvec.so.1','libpthread.so.0','libutil.so.1']})
missing=[];different=[];covered=0;required=census['requirements'];assert len({x['path'] for x in required})==len(required)==43961
for r in required:
 resolved=m.links_resolve(r['path'],links);assert r['namespace_resolved']==resolved
 found=mount['verified_file_backings'].get(resolved)
 if found and found['sha256']==r['sha256']:assert r['classification']=='covered';covered+=1;continue
 if found:different.append(r);continue
 assert r['classification']=='namespace_file_absent';missing.append(r)
 for denied in allow['denied_files']:assert r['path'] not in (denied['path'],denied['resolved']) and r['sha256']!=denied['sha256']
 assert not any(row['sha256']==r['sha256'] for row in mount['verified_file_backings'].values())
 assert r['host_matches_expected'] and r['host_bytes']==125584 and r['sha256']==r['host_sha256']=='027f0f0568634f44e7b8ce414dc506b0a9becc338f4e832d45ce25f8065de54b'
 assert all(reason.endswith(':flight_normalization_bias_inputs') for reason in r['reasons'])
assert covered==43958 and len(missing)==3 and not different and missing==census['missing']==summary['missing']
for r in census['sources']:
 relative=r['path'].split('/validation-07/source/',1)[1];local=Path('/mnt/d/orbit-segmented-v4/validation-07-packet/source')/relative;assert pin(local)['sha256']==r['sha256']
new_backings={**mount['verified_file_backings'],**{r['namespace_resolved']:{'sha256':r['sha256']} for r in missing}}
assert all(new_backings[m.links_resolve(r['path'],links)]['sha256']==r['sha256'] for r in required)
result={'schema':'orbit-poc-public-verifier-closure-independent-replay-v1','reviewed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'summary':pin(Q/'summary01.json'),'full_census':pin(Q/'stdout01.json'),'census_helper':pin(Q/'census_remote.py'),'planner':pin(source),'mount_plan':pin(S/'mount-plan.json'),'allowlist':pin(S/'allowlist.json'),'required':43961,'covered':covered,'missing':missing,'different_hash_count':0,'denied_matches':0,'equivalent_mounted_content_matches':0,'required_paths_uncovered_after_exact_three_additions':0,'frozen_sources_verified':census['sources'],'metadata_rows':len(census['metadata_reads']),'scope':'Independent local path-resolution and exact-pin closure replay of captured explicit zero-prefix verifier read graph. No runtime/loader/native execution, new namespace, fitting, or bulk physical-file hashing. Actual new allowlist/mount and real probe remain separate gates.'}
out=C/'public-verifier-closure-independent-replay01.json'
with out.open('x') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
print(json.dumps(pin(out)))
