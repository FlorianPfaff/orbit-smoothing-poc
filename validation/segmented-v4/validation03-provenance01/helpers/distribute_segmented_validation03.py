#!/usr/bin/env python3
"""Derive a Git-sized distribution; retain exact numerical arrays externally."""
from pathlib import Path
import argparse,gzip,hashlib,io,json,shutil
MAX_FILE=16*1024*1024;MAX_EXPANDED=64*1024*1024;MAX_TOTAL=64*1024*1024
ARRAY_SUFFIXES={'.npz','.npy','.bin','.jsonl','.tsv'}
TEXT_SUFFIXES={'.json','.xml','.log','.html','.txt','.md'}
ARRAY_KEYS={'epoch_conditionals','conditionals','design_matrix','weighted_design_matrix'}
def need(ok,msg):
 if not ok:raise ValueError(msg)
def pin(p):
 p=Path(p);b=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
def read_pin(v):
 p=Path(v['path']);need(p.is_absolute() and p.is_file() and not p.is_symlink(),'Expected exact regular file');b=p.read_bytes();need(len(b)==v['bytes'] and hashlib.sha256(b).hexdigest()==v['sha256'],'Pinned bytes changed');return p,b
def relative(s):
 p=Path(s);need(not p.is_absolute() and '..' not in p.parts and str(p) not in ('','.','manifest.json'),'Unsafe member path');return p
def has_array_payload(v):
 if isinstance(v,dict):return any((k in ARRAY_KEYS and isinstance(x,(list,dict)) and bool(x)) or has_array_payload(x) for k,x in v.items())
 if isinstance(v,list):return any(has_array_payload(x) for x in v)
 return False
def classification(path,raw):
 logical=Path(path)
 if logical.suffix=='.gz':
  with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f:raw=f.read(MAX_EXPANDED+1)
  need(len(raw)<=MAX_EXPANDED,'Expanded file exceeds bound');logical=logical.with_suffix('')
 if logical.suffix in ARRAY_SUFFIXES:return 'external','Numerical array, binary or row archive; retained outside Git'
 need(logical.suffix in TEXT_SUFFIXES,'Unclassified evidence type requires explicit review: '+str(logical))
 text=raw.decode('utf-8')
 if logical.suffix=='.json' and has_array_payload(json.loads(text)):return 'external','Raw numerical conditional/design payload in JSON; retained outside Git'
 return 'included','Exact text audit/provenance/diagnostic evidence'
def inspect(manifest):
 mp,mb=read_pin(manifest);v=json.loads(mb);root=mp.parent
 need(v.get('schema')=='orbit-poc-segmented-validation-publication-v1' and v.get('benchmark_attempts_executed')==0 and v.get('release_ready') is False,'Wrong external publication scope')
 entries={};total=0
 for row in v['files']:
  name=str(relative(row['path']));need(name not in entries,'Duplicate member');p=root/name;need(not p.is_symlink() and p.is_file(),'Missing exact external evidence');b=p.read_bytes();need(len(b)<=MAX_FILE and len(b)==row['bytes'] and hashlib.sha256(b).hexdigest()==row['sha256'],'External evidence changed: '+name);total+=len(b);need(total<=MAX_TOTAL,'External publication exceeds bound');kind,reason=classification(name,b);entries[name]={'identity':row,'disposition':kind,'reason':reason}
 need({str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and p!=mp}==set(entries),'External publication membership changed')
 # Preserve exact canonical remote-source references for every omitted capture member.
 origins={}
 for prefix in ('raw-capture','raw-linearization-arrays'):
  cap=json.loads((root/prefix/'manifest.json').read_bytes())
  for r in cap['records']:origins[prefix+'/'+r['stored']['path']]={'source':r['source'],'stored':r['stored'],'encoding':r.get('encoding','identity')}
 external=[]
 for name,e in entries.items():
  if e['disposition']=='external':
   need(name in origins,'Numerical payload lacks exact external capture attribution');external.append({'path':name,**{k:e['identity'][k] for k in ('sha256','bytes')},'reason':e['reason'],'external_artifact':{'path':str(root/name),**{k:e['identity'][k] for k in ('sha256','bytes')}},'capture':origins[name]})
 need(external and sum(x['path'].endswith('.npz') for x in external)==8,'Expected exact eight retained array files')
 return root,v,entries,external

def distribute(manifest,output):
 root,original,entries,external=inspect(manifest);output=Path(output);need(output.is_absolute() and not output.exists(),'Use a fresh distribution directory');output.mkdir(parents=True)
 for name,e in entries.items():
  if e['disposition']!='included':continue
  target=output/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/name,target);got=pin(target);need(all(got[k]==e['identity'][k] for k in ('sha256','bytes')),'Copied text differs')
 p,b=read_pin(manifest);(output/'external-full-publication-manifest.json').write_bytes(b)
 inventory={'schema':'orbit-poc-segmented-external-numerical-evidence-v1','source_publication':manifest,'files':external,'scope':'Exact preserved files remain in the full external evidence tree and at the captured canonical execution paths. No NPZ, binary row archive, weighted design or raw numerical conditional payload is distributed in Git. Absence here is intentional and never changes any gate status.'}
 (output/'external-evidence.json').write_text(json.dumps(inventory,sort_keys=True,indent=2)+'\n')
 original_html=(output/'index.html').read_text();(output/'presentation-original-index.html').write_text(original_html)
 notice='<p><strong>Git distribution:</strong> raw numerical arrays, weighted rows and conditional matrices remain outside Git. <a href="external-evidence.json">Exact external paths, checksums and sizes</a> and the <a href="external-full-publication-manifest.json">full preserved evidence manifest</a> make every intentional omission explicit. All scalar audit metrics and gate statuses below are unchanged. The preceding <a href="../validation02/index.html">validation02 deployment failure</a> remains a separate record.</p>'
 need('<h1>Segmented v4: terminal validation</h1>' in original_html,'Unexpected original presentation');(output/'index.html').write_text(original_html.replace('<h1>Segmented v4: terminal validation</h1>','<h1>Segmented v4: terminal validation</h1>'+notice,1))
 files=[]
 for p in sorted(output.rglob('*')):
  if p.is_file():
   raw=p.read_bytes();kind,_=classification(str(p.relative_to(output)),raw);need(kind=='included','Numerical payload entered Git distribution');got=pin(p);files.append({'path':str(p.relative_to(output)),**{k:got[k] for k in ('sha256','bytes')}})
 for record in external:read_pin(record['external_artifact'])
 need({str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and p!=root/'manifest.json'}==set(entries),'External membership changed during distribution')
 need(sum(x['bytes'] for x in files)<=MAX_TOTAL and all(x['bytes']<=MAX_FILE for x in files),'Distribution exceeds bounds')
 result={'schema':'orbit-poc-segmented-validation-git-distribution-v1','files':files,'bytes':sum(x['bytes'] for x in files),'source_publication':manifest,'external_not_distributed':external,'scientific_status':original['scientific_status'],'benchmark_attempts_executed':0,'release_ready':False,'fit_covariance_authorized':False,'helper':pin(__file__),'original_capture_membership':'Raw capture inventories are exact originals, including explicitly external members; consult external-evidence.json for the complete omitted set.'};(output/'manifest.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');return result

def main():
 a=argparse.ArgumentParser();a.add_argument('--manifest',type=Path,required=True);a.add_argument('--sha256',required=True);a.add_argument('--output',type=Path,required=True);v=a.parse_args();p=pin(v.manifest);need(p['sha256']==v.sha256,'Manifest pin differs');out=distribute(p,v.output);print(json.dumps({'manifest':pin(v.output/'manifest.json'),'files':len(out['files']),'external':len(out['external_not_distributed'])}))
if __name__=='__main__':main()
