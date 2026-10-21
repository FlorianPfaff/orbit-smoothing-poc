#!/usr/bin/env python3
"""Recheck the independently audited complete required-file graph against a captured fresh map."""
from pathlib import Path
import argparse,datetime,hashlib,importlib.util,json
C=Path('/mnt/d/orbit-segmented-v4/control')
def need(v,m):
 if not v:raise ValueError(m)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def main():
 a=argparse.ArgumentParser();a.add_argument('--capture',type=Path,required=True);a.add_argument('--output',type=Path,required=True);o=a.parse_args()
 need(not o.output.exists(),'Fresh replay receipt required')
 census=C/'public-verifier-closure-census01/stdout01.json';need(sha(census)=='762a35d6cc8defe753b2989c4dc7ecc6f8901d5470aba2d023805daa9c6ce93b','Original full census changed');old=json.loads(census.read_text())
 planner=C/'symlink-closure-draft02/plan_segmented_fit_namespace02.py';need(sha(planner)=='2a00bb3fa57bef3c034e3ab96348c6f720d25af5473e65efb9a5a6dc5a7d68d2','Planner changed')
 spec=importlib.util.spec_from_file_location('exact_planner',planner);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 capfile=o.capture/'manifest.json';cap=json.loads(capfile.read_text());need(cap['status']=='sealed_metadata' and cap['fit_attempts']==cap['native_executions']==0 and not cap['owned_live'],'Clean terminal capture required')
 records={r['relative_path']:r for r in cap['files']}
 for name in ('sealed/mount-plan.json','sealed/allowlist.json','sealed/result.json'):
  need(sha(o.capture/name)==records[name]['sha256'],'Changed actual capture '+name)
 mount=json.loads((o.capture/'sealed/mount-plan.json').read_text());allow=json.loads((o.capture/'sealed/allowlist.json').read_text());result=json.loads((o.capture/'sealed/result.json').read_text())
 need(result['artifacts']['mount-plan.json']['sha256']==records['sealed/mount-plan.json']['sha256'] and result['artifacts']['allowlist.json']['sha256']==records['sealed/allowlist.json']['sha256'],'Actual result correspondence')
 links={r['path']:r['target'] for r in mount['canonical_symlinks']};links.update({'/usr/lib64/'+n:'/usr/lib/x86_64-linux-gnu/'+n for n in ('libc.so.6','libdl.so.2','libm.so.6','libmvec.so.1','libpthread.so.0','libutil.so.1')})
 missing=[];different=[];resolved_ledger=[]
 for row in old['requirements']:
  resolved=m.links_resolve(row['path'],links);back=mount['verified_file_backings'].get(resolved)
  entry={'path':row['path'],'sha256':row['sha256'],'resolved':resolved}
  if back is None:missing.append(entry)
  elif back['sha256']!=row['sha256']:different.append({**entry,'actual_sha256':back['sha256']})
  else:resolved_ledger.append(entry)
 need(len(old['requirements'])==old['required_file_count']==43961,'Original census size differs')
 v={'schema':'orbit-poc-public-verifier-fresh-seal-replay-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'passed' if not missing and not different else 'failed','census':pin(census),'capture':pin(capfile),'mount_plan':result['artifacts']['mount-plan.json'],'allowlist':result['artifacts']['allowlist.json'],'result':{'path':str(o.capture/'sealed/result.json'),'sha256':records['sealed/result.json']['sha256']},'required_file_count':43961,'covered_count':len(resolved_ledger),'missing_count':len(missing),'different_hash_count':len(different),'missing':missing,'different_hash':different,'resolved_ledger_sha256':hashlib.sha256(json.dumps(resolved_ledger,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'denied_count':len(allow['denied_files']),'native_executions':0,'fit_attempts':0,'scope':'All original independent required paths resolved against exact fresh captured namespace metadata; no new namespace, verifier execution, data rehash or scientific workload.'}
 o.output.write_text(json.dumps(v,indent=2,sort_keys=True)+'\n');print(json.dumps({'result':pin(o.output),'status':v['status'],'covered':len(resolved_ledger),'missing':len(missing),'different':len(different)}));need(v['status']=='passed','Required closure incomplete')
if __name__=='__main__':main()
