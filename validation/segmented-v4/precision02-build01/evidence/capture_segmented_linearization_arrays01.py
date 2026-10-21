#!/usr/bin/env python3
"""Copy exact small linearization arrays after the independently guarded capture."""
from pathlib import Path
import argparse,hashlib,json,shutil
METHODS=('log_drag_ou','pulses')
NAMES=('dense-reference.npz','gtsam-original-rows.npz','segments-3600/covariance.npz','segments-14400/covariance.npz')
def need(ok,why):
 if not ok:raise ValueError(why)
def pin(p):
 p=Path(p);return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}
def checked(p):
 q=Path(p['path']);need(q.is_absolute() and not q.is_symlink() and pin(q)==p,'Array/evidence identity changed');return q
def capture(capture_manifest,output):
 original=checked(capture_manifest);manifest=json.loads(original.read_text());need(manifest['schema']=='orbit-poc-v4-terminal-validation-capture-v1' and manifest['final_owned_cleanup_verified'] is True,'Main terminal capture is required')
 checked(manifest['controller']);pipeline=checked(manifest['pipeline']);raw=json.loads(pipeline.read_text());steps={x['name']:x for x in raw['steps']};out=Path(output);need(out.is_absolute() and not out.exists() and not out.is_symlink() and pipeline.parent not in out.parents,'Fresh separate array capture required')
 files=[]
 for method in METHODS:
  step=steps['linearization-'+method];need(step['status']=='passed','Raw linearization must pass before this completed-array appendix')
  root=Path(step['directory'])/'result/comparison';need(root==pipeline.parent/('linearization-'+method)/'result/comparison','Foreign linearization directory')
  discovered=sorted(str(p.relative_to(root)) for p in root.rglob('*.npz'))
  need(discovered==sorted(NAMES),'Expected complete four-array native/GTSAM covariance inventory')
  for name in NAMES:
   p=root/name;need(p.is_file() and not p.is_symlink() and p.stat().st_size<=16*1024*1024,'Invalid/oversized array');files.append((method,name,pin(p)))
 need(sum(p['bytes'] for _,_,p in files)<=64*1024*1024,'Array appendix too large')
 out.mkdir(parents=True);records=[]
 for method,name,p in files:
  destination=out/method/name;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(checked(p),destination);copied=pin(destination);need(copied['sha256']==p['sha256'] and copied['bytes']==p['bytes'],'Array copy differs');records.append({'source':p,'stored':{**copied,'path':str(destination.relative_to(out))}})
 checked(capture_manifest);checked(manifest['controller']);checked(manifest['pipeline'])
 for _,_,p in files:checked(p)
 result={'schema':'orbit-poc-segmented-linearization-array-capture-v1','main_capture':capture_manifest,'pipeline':manifest['pipeline'],'records':records,'helper':pin(__file__),'scope':'Exact eight small native/GTSAM/covariance arrays; no mathematical computation, replacement or scientific promotion; original row/factor spools remain untouched.'}
 with (out/'manifest.json').open('x') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
 return pin(out/'manifest.json')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--capture-manifest',type=Path,required=True);p.add_argument('--sha256',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();v=pin(a.capture_manifest);need(v['sha256']==a.sha256,'Main capture changed');print(json.dumps(capture(v,a.output)))
