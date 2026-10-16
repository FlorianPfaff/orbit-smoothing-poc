"""Copy exactly the20 verified cached products; no downloads or acquisition claims."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,shutil,sys,datetime

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def save(p,v):
 with Path(p).open('x') as f:json.dump(v,f,indent=2);f.write('\n')
def main(argv=None):
 a=argparse.ArgumentParser();a.add_argument('--execution',type=Path,required=True);a.add_argument('--sha256',required=True);a.add_argument('--destination',type=Path,required=True);a.add_argument('--receipt',type=Path,required=True);q=a.parse_args(argv)
 if sha(q.execution)!=q.sha256:raise ValueError('Execution identity changed')
 e=json.loads(q.execution.read_text());source=Path(e['paths']['source']);driver=Path(e['paths']['control'])/'owned_driver09.py';spec=importlib.util.spec_from_file_location('owned',driver);d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d);d.load_execution(q.execution)
 freeze=json.loads((Path(e['paths']['control'])/'source-freeze.json').read_text())
 if d.source_receipt(source)!=freeze['source']:raise ValueError('Frozen source differs before offline cache reuse')
 if q.destination.exists() or q.destination.is_symlink() or q.receipt.exists() or q.receipt.is_symlink():raise ValueError('Fresh destination and receipt required')
 if not q.destination.is_absolute() or '..' in q.destination.parts or any(p.is_symlink() for p in q.destination.parents):raise ValueError('Canonical destination required')
 rows=[]
 for name,record in sorted(e['runtime_artifacts'].items()):
  if not name.startswith('preparation_current_product_record_'):continue
  rp=d.resolved_host_path(record['path'],e)
  if sha(rp)!=record['sha256'] or not rp.name.endswith('.gz.source.json'):raise ValueError('Preserved verification record differs')
  data=json.loads(rp.read_text());original=Path(str(rp)[:-len('.source.json')])
  if original.is_symlink() or sha(original)!=data['sha256'] or original.stat().st_size!=data['bytes']:raise ValueError('Product bytes differ from sealed record')
  rows.append({'key':name,'product':pin(original),'record':pin(rp),'record_data':data})
 if len(rows)!=20 or len({r['product']['path'] for r in rows})!=20:raise ValueError('Expected exact20 cache products')
 q.destination.mkdir(parents=True);sys.path.insert(0,str(source/'src'));from orbit_poc.comparison import data as api
 def forbid_network(*a,**k):raise RuntimeError('Cache staging must never acquire data')
 api.urlopen=forbid_network;out=[]
 for row in rows:
  original=Path(row['product']['path']);oldrecord=Path(row['record']['path']);target=q.destination/original.name;record=target.with_name(target.name+'.source.json')
  shutil.copyfile(original,target);shutil.copyfile(oldrecord,record)
  if sha(target)!=row['product']['sha256'] or sha(record)!=row['record']['sha256']:raise ValueError('Copied cache bytes changed')
  if (target.stat().st_dev,target.stat().st_ino)==(original.stat().st_dev,original.stat().st_ino):raise ValueError('Writable product shares source inode')
  returned=api.fetch_url(row['record_data']['url'],target,row['product']['sha256'],download=False)
  if returned['path']!=str(target.resolve()) or returned['sha256']!=row['product']['sha256'] or sha(record)!=row['record']['sha256']:raise ValueError('Frozen offline reuse changed acquisition record')
  out.append({'source_product':row['product'],'source_record':row['record'],'copied_product':pin(target),'copied_record':pin(record),'copied_record_original_path_field':row['record_data']['path'],'actual_offline_fetch_url_passed':True})
 if d.source_receipt(source)!=freeze['source']:raise ValueError('Frozen source changed during offline cache reuse')
 result={'schema':'orbit-poc-preparation03-product-cache-staging-v1','observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'execution':pin(q.execution),'source_root':str(source),'data_helper':pin(source/'src/orbit_poc/comparison/data.py'),'helper':pin(__file__),'entries':out,'product_count':20,'record_count':20,'network_requests':0,'native_propagations':0,'verification_scope':'Exact byte copies of preserved current-offline verification records and matching products from preparation02. Existing retrieved_utc/path fields are historical metadata, not a new acquisition claim. All20 products exercised through unchanged fetch_url(download=False); no shared writable inodes.'}
 save(q.receipt,result);print(json.dumps({'receipt':pin(q.receipt),'products':20,'records':20,'bytes':sum(Path(x['copied_product']['path']).stat().st_size for x in out)}))
if __name__=='__main__':main()
