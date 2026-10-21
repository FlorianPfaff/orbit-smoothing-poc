#!/usr/bin/env python3
"""Apply one independently approved data-only original150 interruption append."""
from pathlib import Path
import argparse,fcntl,hashlib,json,os,stat
SCHEMA='orbit-poc-original150-interruption-append-plan-v3'
NAMES=('controller-boot-interruption.json','result.json','result-record.json')
def need(value,message):
 if not value: raise ValueError(message)
def digest(raw):return hashlib.sha256(raw).hexdigest()
def file_digest(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
 return h.hexdigest()
def no_symlink(path):
 p=Path(path); need(p.is_absolute(),'Path must be absolute')
 for x in [p,*p.parents]:need(not x.is_symlink(),'Symlink path rejected: '+str(x))
 return p
def checked(item):
 need(set(item) in ({'path','sha256'},{'path','sha256','bytes'}),'Unknown pin fields')
 p=no_symlink(item['path']); need(p.is_file(),'Missing pinned file: '+str(p)); raw=p.read_bytes()
 need(digest(raw)==item['sha256'],'Changed pinned bytes: '+str(p))
 if 'bytes' in item:need(len(raw)==item['bytes'],'Changed pinned length')
 return p,raw
def read(item):return json.loads(checked(item)[1])
def canonical(x):return digest(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def current_boot():return Path('/proc/sys/kernel/random/boot_id').read_text().strip()
def inspect(plan):
 need(set(plan)=={'schema','helper','proposal','independent_review','boot_id','benchmark_root','alias_inventory','alias_review'},'Unknown plan fields')
 need(plan['schema']==SCHEMA,'Wrong plan schema'); need(current_boot()==plan['boot_id'],'Host boot changed')
 checked(plan['helper']); need(Path(plan['helper']['path'])==Path(__file__).absolute(),'Wrong helper')
 root=no_symlink(plan['benchmark_root']); need(root.is_dir(),'Missing benchmark root')
 proposal=read(plan['proposal']); review=read(plan['independent_review'])
 need(review.get('passed') is True,'Independent review did not pass')
 need(review.get('proposal',{}).get('path')==plan['proposal']['path'] and review.get('proposal',{}).get('sha256')==plan['proposal']['sha256'],'Review does not bind exact proposal')
 need(proposal['status']=='proposed_not_applied','Wrong proposal state')
 obs=read(proposal['observation']); need(obs['current_boot_id']==plan['boot_id'] and obs['boot_changed'],'Wrong interruption observation')
 manifest=read(proposal['manifest']); need(Path(proposal['manifest']['path'])==root/'manifest.json','Wrong frozen root')
 need(len(manifest['attempts'])==150,'Wrong campaign cardinality'); a=manifest['attempts'][17]; need(a['order']==17,'Wrong frozen interrupted order')
 need(proposal['attempt']==a==obs['interrupted_attempt'],'Wrong interrupted attempt')
 need(obs['terminal_checkpoints']==17 and obs['interrupted_without_checkpoint']==1,'Wrong observed prefix')
 checked(proposal['archived_protocol']); config=read(proposal['configuration']); checked(proposal['request'])
 d=no_symlink(root/'attempts'/a['attempt_id']); need(d.is_dir(),'Missing partial attempt')
 case=next(x for x in manifest['cases'] if x['case_id']==a['case_id']); rt=manifest['new_runtime']; checked(rt['native'])
 job={**case['fit_request'],'id':a['attempt_id'],'kind':'fit','split':'numerics','numerics_profile':a['profile'],'numerics_manifest_hash':manifest['manifest_hash'],'input_manifest_hash':case['input_manifest_hash'],'source_hash':rt['source_sha256'],'protocol_hash':manifest['manifest_hash'],'backend':{'groops_executable':rt['native']['path'],'command_timeout_seconds':7200.,'retain_native_diagnostics':True},'expected_native_binary_sha256':rt['native']['sha256'],'numerical_controls':config['controls']}
 need(json.loads((d/'request.json').read_text())==job==json.loads((d/'worker-request.json').read_text()),'Frozen attempt request changed')
 need(canonical(job)==proposal['request_hash']==obs['partial_request_hash'],'Wrong canonical request hash')
 need(len(proposal['expected_checkpoint_prefix'])==17,'Wrong preserved prefix length')
 for i,row in enumerate(proposal['expected_checkpoint_prefix']):
  need(row['attempt_id']==manifest['attempts'][i]['attempt_id'],'Wrong prefix order'); checked(row['result']); checked(row['index'])
 for copied in obs['copies']:checked(copied['source'])
 for later in manifest['attempts'][18:]:
  path=no_symlink(root/'attempts'/later['attempt_id']); need(not path.exists() or (path.is_dir() and not any(path.iterdir())),'Later work already exists')
 alias=read(plan['alias_inventory']); alias_review=read(plan['alias_review'])
 need(alias_review.get('passed') is True,'Alias inventory review did not pass')
 need(alias_review.get('alias_inventory',{}).get('path')==plan['alias_inventory']['path'] and alias_review.get('alias_inventory',{}).get('sha256')==plan['alias_inventory']['sha256'],'Alias review does not bind exact inventory')
 need(alias['schema']=='orbit-poc-original150-existing-input-alias-inventory-v1' and alias['attempt_directory']==str(d),'Wrong alias inventory')
 need(alias['request']['path']==proposal['request']['path'] and alias['request']['sha256']==proposal['request']['sha256'],'Alias inventory belongs to another request')
 aliases={x['relative']:x for x in alias['entries']}; need(len(aliases)==alias['alias_count']==len(alias['entries']),'Repeated alias inventory entry')
 actual_aliases={str(p.relative_to(d)):p for p in d.rglob('*') if p.is_symlink()}
 need(set(actual_aliases)==set(aliases),'Added or missing input alias')
 for rel,item in aliases.items():
  relative=Path(rel);need(not relative.is_absolute() and '..' not in relative.parts and rel not in NAMES,'Invalid input alias path')
  p=actual_aliases[rel]; no_symlink(p.parent); st=p.lstat()
  need(os.readlink(p)==item['target'] and st.st_size==item['lstat_size'] and st.st_mtime_ns==item['lstat_mtime_ns'],'Retargeted or replaced input alias')
 expected={x['relative']:x for x in obs['partial_files']}; actual={str(p.relative_to(d)):p for p in d.rglob('*') if p.is_file() and not p.is_symlink()}
 need(set(actual)-set(NAMES)==set(expected),'Partial output membership changed')
 for rel,item in expected.items():
  p=no_symlink(actual[rel]); s=p.stat(); need(s.st_size==item['bytes'] and s.st_mtime_ns==item['mtime_ns'],'Partial output stat identity changed')
  need(file_digest(p)==item['sha256'],'Partial output bytes changed')
 need(len(proposal['append_files'])==3,'Wrong append cardinality'); candidates=[]; found_absent=False
 for name,item in zip(NAMES,proposal['append_files']):
  target=no_symlink(item['destination']); need(target==d/name,'Wrong append destination')
  candidate,raw=checked(item['candidate']); need(candidate==Path(plan['proposal']['path']).parent/name,'Wrong candidate path')
  if target.exists():
   need(not found_absent,'Nonprefix partial append'); need(target.is_file() and target.read_bytes()==raw,'Existing append differs')
  else:found_absent=True
  candidates.append((target,raw))
 receipt,result,index=[json.loads(raw) for _,raw in candidates]
 need(receipt['outcome']=='interrupted' and receipt['numerical_rerun'] is False and receipt['covariance_authorized'] is False,'Unsafe recovery receipt')
 need(result['status']=='interrupted' and result['converged'] is False and result['covariance_valid'] is False,'Unsafe result status')
 need(result['elapsed_seconds'] is None and result['final_objective'] is None,'Fabricated final measurement')
 for key in ['elapsed_seconds','peak_process_tree_rss_bytes','returncode','pid','minimum_free_output_bytes','minimum_free_physical_backing_bytes']:need(result['harness_execution'][key] is None,'Fabricated parent metric')
 need(index['attempt_id']==a['attempt_id'] and index['request_hash']==proposal['request_hash'] and index['status']=='interrupted','Wrong result index')
 need(index['result']=={'path':str(candidates[1][0]),'sha256':digest(candidates[1][1])},'Wrong result binding')
 future={str(p):raw for p,raw in candidates}
 for art in result['artifacts']:
  if art['path'] in future:need(digest(future[art['path']])==art['sha256'],'Wrong future artifact binding')
  else:checked({k:art[k] for k in ('path','sha256')})
 return candidates

def append_exact(path,raw):
 no_symlink(path)
 if path.exists():need(path.is_file() and path.read_bytes()==raw,'Existing append differs');return False
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
 with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
 parent=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
 try:os.fsync(parent)
 finally:os.close(parent)
 return True

def run(plan_path,sha256,apply=False):
 plan=read({'path':str(Path(plan_path).absolute()),'sha256':sha256})
 root=no_symlink(plan['benchmark_root']); lock=no_symlink(root/'numerics.lock')
 need(lock.is_file(),'Existing campaign lock required')
 fd=os.open(lock,os.O_RDWR|os.O_NOFOLLOW)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  candidates=inspect(plan); written=[]
  if apply:
   for target,raw in candidates:
    need(current_boot()==plan['boot_id'],'Host boot changed during append')
    if append_exact(target,raw):written.append(str(target))
   inspect(plan)
  return {'schema':'orbit-poc-original150-interruption-append-result-v1','status':'applied_exact_approved_bytes' if apply else 'verified_not_applied','proposal':plan['proposal'],'independent_review':plan['independent_review'],'boot_id':plan['boot_id'],'written':written,'append_files':[{'path':str(p),'sha256':digest(raw),'bytes':len(raw)} for p,raw in candidates],'numerical_rerun':False,'native_launch':False,'old_outputs_modified':False,'covariance_authorized':False}
 finally:os.close(fd)

def main():
 p=argparse.ArgumentParser();p.add_argument('--plan',required=True);p.add_argument('--sha256',required=True);p.add_argument('--apply',action='store_true');args=p.parse_args()
 print(json.dumps(run(args.plan,args.sha256,args.apply),sort_keys=True,indent=2))
if __name__=='__main__':main()
