from pathlib import Path
import hashlib,importlib.util,json,datetime
C=Path('/mnt/d/orbit-segmented-v4/control');D=C/'direct-sealing04-terminal01'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
p=C/'symlink-closure-draft02/plan_segmented_fit_namespace02.py';assert sha(p)=='2a00bb3fa57bef3c034e3ab96348c6f720d25af5473e65efb9a5a6dc5a7d68d2'
s=importlib.util.spec_from_file_location('candidate_planner',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
a=json.loads((D/'sealed/allowlist.json').read_text());mapping=json.loads((D/'sealed/backing-map.json').read_text());host=json.loads((C/'symlink-closure-independent-host-link01.json').read_text())
assert host['boot_id']=='95156dd4-0d4c-499d-a214-8883a2d650fa'
links={r['path']:r['target'] for r in mapping['canonical_symlinks']};assert host['path'] not in links
links[host['path']]=host['target'];rows={r['path']:r for r in a['files']};used=set();required=set(a['directories']);trees={r['root'] for r in a['verified_safe_trees']};ninv=0
for r in a['files']:
 assert m.links_resolve(r['path'],links,used)==r['resolved']
 if r['link_target'] is not None:assert links[r['path']]==r['link_target']
for inv in [json.loads((D/f'sealed/safe-tree-{i:02d}.json').read_text()) for i in range(3)]+a['native_data_inventories']:
 for e in inv['entries']:
  name=inv['root']+'/'+e['relative'];ninv+=1
  required.add(name if e['kind']=='directory' else str(Path(name).parent))
  assert m.links_resolve(name,links,used)==e['resolved']
  if e['link_target'] is not None:assert links[name]==e['link_target']
requested=set(rows)|required|trees
for name in requested:m.links_resolve(name,links,used)
assert all(name in used or any(m.within(x,name) for x in requested) for name in links)
placements=m.symlink_placements(links)
external={name:target for name,target in placements.items() if not any(m.within(name,root) for root in trees)}
assert '/lib64/ld-linux-x86-64.so.2' not in placements
assert external[host['path']]==host['target']
oldroots={r['root'] for r in a['verified_safe_trees']};oldexternal={r['path']:r['target'] for r in mapping['canonical_symlinks'] if not any(m.within(r['path'],root) for root in oldroots)}
added=set(external)-set(oldexternal);removed=set(oldexternal)-set(external)
assert added=={host['path']} and removed=={'/lib64/ld-linux-x86-64.so.2'}
v={'schema':'orbit-poc-symlink-closure-independent-actual-replay-v1','status':'passed_metadata_topology_replay','reviewed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'planner_sha256':sha(p),'allowlist_sha256':sha(D/'sealed/allowlist.json'),'backing_map_sha256':sha(D/'sealed/backing-map.json'),'host_link_readback_sha256':sha(C/'symlink-closure-independent-host-link01.json'),'file_rows_checked':len(rows),'inventory_entries_checked':ninv,'original_declared_links':len(mapping['canonical_symlinks']),'closed_declared_links':len(links),'normalized_placements':len(placements),'external_placements':len(external),'external_added':sorted(added),'external_removed':sorted(removed),'fit_attempts':0,'native_executions':0,'scope':'Captured metadata topology only; no bulk backing rehash, no production namespace execution or runtime support certification.'}
out=C/'symlink-closure-independent-actual01.json'
with out.open('x') as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
print(json.dumps(v,indent=2));print(sha(out))
