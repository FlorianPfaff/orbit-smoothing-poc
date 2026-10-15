from pathlib import Path
import json,hashlib,subprocess,datetime,gzip
base=Path('/mnt/c/users/emper/documents/codex/2026-10-13/i-x20')
root=Path('/mnt/d/orbit-segmented-v4');out=root/'control/prior-seed-scan-01';out.mkdir(exist_ok=False)
roots={'v2_archived_runs':base/'outputs/orbit-poc/runs/v2','v2_published_runs':root/'source/runs','v3_local':base/'work/v3','v3_mirror':Path('/mnt/d/orbit-numerics-v3.1-mirror/remote-root/mnt/seagate10tb/orbit-comparison-v3-20261013-florianpfaff'),'v3_published':root/'source/validation/comparison-v3','v31_original_benchmark':Path('/mnt/d/orbit-numerics-v3.1/benchmark-d-volume/benchmark-01'),'v31_published_freeze':root/'source/validation/numerics-v3.1/benchmark-freeze'}
# Read metadata only. Runtime package trees and generated physical trajectory arrays are not protocol archives.
patterns=['manifest.json','protocol*.json','plan.json','config*.json','request.json','generation.json','dataset.json','*protocol*.json.gz','manifest.json.gz']
records=[];memberships={};used=set();errors=[]
def seeds(v):
 found=set()
 def visit(x):
  if isinstance(x,dict):
   for k,z in x.items():
    if k=='seed' and type(z) is int:found.add(z)
    if 'seeds' in k:
     col=z.values() if isinstance(z,dict) else z if isinstance(z,list) else []
     found.update(y for y in col if type(y) is int)
    visit(z)
  elif isinstance(x,list):
   for z in x:visit(z)
 visit(v);return sorted(found)
for label,directory in roots.items():
 if not directory.is_dir():raise RuntimeError('Missing archive '+str(directory))
 args=['rg','--files','--hidden']
 for pat in patterns:args+=['-g',pat]
 for part in ['mamba-root','native-env','native-source','native-build','groops-source','python','env','tudat-env','.git']:args+=['-g','!**/'+part+'/**']
 args += [str(directory)]
 result=subprocess.run(args,capture_output=True,text=True,check=False)
 if result.returncode not in (0,1):raise RuntimeError(result.stderr)
 paths=sorted(set(result.stdout.splitlines()));memberships[label]={'root':str(directory),'metadata_files':len(paths),'paths':paths}
 for name in paths:
  path=Path(name)
  try:
   raw=path.read_bytes();decoded=gzip.decompress(raw) if path.suffix=='.gz' else raw;value=json.loads(decoded);values=seeds(value);used.update(values)
   records.append({'archive':label,'path':name,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'seeds':values})
  except Exception as exc:errors.append({'path':name,'error':str(exc)})
value={'schema':'orbit-poc-prior-seed-archive-scan-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'requested_fresh_seeds':[610000,610001],'observed_seeds':sorted(used),'overlap':sorted(used&{610000,610001}),'status':'passed' if not errors and not used&{610000,610001} else 'failed','archives':memberships,'metadata_patterns':patterns,'exclusions':['native/runtime package directories; no scientific metadata excluded by size'],'files':records,'errors':errors,'scope':'All matching archived protocol/config/manifest/request metadata in the listed v2, v3 and v3.1 roots; exact files and directory membership recorded before preparation.'}
(out/'scan.json').write_text(json.dumps(value,sort_keys=True,indent=2)+'\n');print(json.dumps({'path':str(out/'scan.json'),'sha256':hashlib.sha256((out/'scan.json').read_bytes()).hexdigest(),'count':len(records),'seeds':sorted(used),'errors':len(errors),'overlap':value['overlap'],'archives':{k:v['metadata_files'] for k,v in memberships.items()}}))
if errors or value['overlap']:raise SystemExit(1)
