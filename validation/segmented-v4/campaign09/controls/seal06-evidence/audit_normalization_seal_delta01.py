from pathlib import Path
import argparse,hashlib,json,importlib.util,datetime
C=Path('/mnt/d/orbit-segmented-v4/control');B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff')
def need(v,m):
 if not v:raise ValueError(m)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def read(p):return json.loads(Path(p).read_text())
def capture(folder,expected):
 m=read(folder/'manifest.json');need(sha(folder/'manifest.json')==expected,'Capture identity changed');files={}
 for r in m['files']:
  p=folder/r['relative_path'];need(p.stat().st_size==r['bytes'] and sha(p)==r['sha256'],'Captured file changed '+str(p));need(r['path'] not in files,'Duplicate remote capture path');files[r['path']]=r
 need(m['status']=='sealed_metadata' and m['fit_attempts']==m['native_executions']==0 and m['owned_live']==[],'Not a clean metadata capture')
 result=read(folder/'sealed/result.json');data={}
 for name,q in result['artifacts'].items():
  need(q['path'] in files and files[q['path']]['sha256']==q['sha256'],'Result artifact/capture mismatch');data[name]=read(folder/'sealed'/name)
 return m,files,result,data
p=argparse.ArgumentParser();p.add_argument('--capture-sha256',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();need(not a.output.exists(),'Preserve prior audit')
oldpath=C/'direct-sealing05-terminal01';newpath=C/'direct-sealing06-terminal01'
# Original successful capture was already independently verified; rehash only the
# original sealed JSON used in this delta, not all source/data/runtime payloads.
om=read(oldpath/'manifest.json');orf=read(oldpath/'sealed/result.json');od={}
for name,q in orf['artifacts'].items():need(sha(oldpath/'sealed'/name)==q['sha256'],'Original artifact changed');od[name]=read(oldpath/'sealed'/name)
nm,nfiles,nrf,nd=capture(newpath,a.capture_sha256)
census=read(C/'public-verifier-closure-census01/summary01.json');need(sha(C/'public-verifier-closure-census01/summary01.json')=='1cf15d472fb1f1cc9e7f89e0b434a2011a34f2a47984fefb151280027ca3da12','Census changed')
add={r['path']:r for r in census['missing']};need(len(add)==3,'Wrong additions')
roots=[str(B/'fit-seal-control-07/sealed-inputs-03'),str(B/'fit-seal-control-07/sealed-inputs-04')]
summary={}
for name,key in [('support-core.json','path'),('support-final.json','path'),('allowlist-core.json','path'),('allowlist.json','path'),('backing-map.json','canonical')]:
 before=od[name]['files'];after=nd[name]['files'];om={r[key]:r for r in before};am={r[key]:r for r in after};need(len(om)==len(before) and len(am)==len(after),'Duplicate rows')
 original={q:r for q,r in om.items() if not q.startswith(roots[0]+'/')};current={q:r for q,r in am.items() if not q.startswith(roots[1]+'/')}
 need(set(current)-set(original)==set(add) and not set(original)-set(current),'Unexpected nonmetadata file delta '+name)
 for q,r in original.items():need(current[q]==r,'Existing nonmetadata identity changed '+q)
 for q,c in add.items():
  r=current[q];actual=r['backing'] if key=='canonical' else r
  need(actual['sha256']==c['sha256'] and actual['bytes']==125584 and actual['device']==c['host_device'] and actual['inode']==c['host_inode'],'Added file identity differs')
  if key=='canonical':need(actual['path']==c['host_backing'],'Added backing changed')
 oldmeta=[Path(r[key]).name for r in before if r[key].startswith(roots[0]+'/')];newmeta=[Path(r[key]).name for r in after if r[key].startswith(roots[1]+'/')];need(oldmeta==newmeta,'Generated metadata membership/order changed')
 summary[name]={'old_rows':len(before),'fresh_rows':len(after),'existing_nonmetadata_rows_exact':len(original),'added_paths':sorted(add),'relocated_metadata_names':oldmeta}
for name in ('allowlist-core.json','allowlist.json'):
 for key in ('denied_files','denied_tree_inventories','directories','writable','native_data_inventories','manifest_hash','known_attitude_scope','required_prelaunch_probes','scope'):
  need(od[name][key]==nd[name][key],'Unrelated allowlist policy changed '+key)
for name in ('safe-tree-00.json','safe-tree-01.json','safe-tree-02.json'):need(orf['artifacts'][name]['sha256']==nrf['artifacts'][name]['sha256'],'Scientific runtime/source inventory changed')
need(od['backing-map.json']['canonical_symlinks']==nd['backing-map.json']['canonical_symlinks'],'Canonical aliases changed')
need(od['mount-plan.json']['writable_mounts']==nd['mount-plan.json']['writable_mounts'],'Writable identities changed')
need(od['probe-spec.json']['denied_paths']==nd['probe-spec.json']['denied_paths'],'Denial paths changed')
need(orf['manifest']==nrf['manifest'] and orf['manifest_hash']==nrf['manifest_hash'],'Scientific manifest changed')
# Secondary execution of the independently reviewed strict comparison on actual
# captured metadata. Remote identities are taken from those captured ledgers,
# never from local extraction inodes.
helper=C/'normalization-recovery-draft01/derive_campaign09_normalization03.py';need(sha(helper)=='c123d89ecc93762df9c4e71cbbcec32326b9691b28726c414803faccca47302a','Reviewed adapter changed')
s=importlib.util.spec_from_file_location('adapter',helper);mod=importlib.util.module_from_spec(s);s.loader.exec_module(mod)
def bundle(root,result,data,folder):
 meta={q['path']:{**q,'bytes':(folder/'sealed'/n).stat().st_size} for n,q in result['artifacts'].items()};meta[root+'/run-skeleton']={'path':root+'/run-skeleton'}
 def visit(v):
  if isinstance(v,list):
   for x in v:visit(x)
  elif isinstance(v,dict):
   if v.get('path') in meta:
    r=meta[v['path']]
    for k in ('sha256','bytes','device','inode','mode'):
     if k in v:
      need(k not in r or r[k]==v[k],'Inconsistent captured metadata identity');r[k]=v[k]
   for x in v.values():visit(x)
 for v in data.values():visit(v)
 return {'root':root,'result':result,'data':{n:v for n,v in data.items() if not n.startswith('safe-tree-')},'metadata':meta}
delta=mod.compare_seals(bundle(roots[0],orf,od,oldpath),bundle(roots[1],nrf,nd,newpath),census)
# Local skeleton capture contains no scientific values: validate exact membership
# and zero-sized files against the planner's deterministic skeleton specification.
sk=read(newpath/'capture/skeleton-inventory.json')
result={'schema':'orbit-poc-normalization-seal-independent-delta-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'passed_captured_metadata_delta','capture':pin(newpath/'manifest.json'),'old_result':orf['artifacts'].get('result.json',{'path':roots[0]+'/result.json','sha256':sha(oldpath/'sealed/result.json')}),'fresh_result':{'path':roots[1]+'/result.json','sha256':sha(newpath/'sealed/result.json')},'capture_files_verified':len(nfiles),'capture_bytes_verified':sum(r['bytes'] for r in nfiles.values()),'raw_nonmetadata_comparisons':summary,'strict_adapter_comparison':delta,'census':pin(C/'public-verifier-closure-census01/summary01.json'),'result_counts':{'allowed_files':nrf['files'],'denied_files':nrf['denied_files'],'correspondence':nrf['conditional_host_correspondence']},'fit_attempts':0,'native_executions':0,'actual_full_namespace_probe_passed':False}
with a.output.open('x') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
print(json.dumps(pin(a.output)))
