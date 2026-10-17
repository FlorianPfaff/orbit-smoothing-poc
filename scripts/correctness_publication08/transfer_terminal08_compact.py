"""Read-only bounded transfer after both execution08 journals are terminal."""
from pathlib import Path
import subprocess,json,base64,hashlib,gzip
BASE=Path('/mnt/d/orbit-numerics-v3.1/correctness');CONTROL=BASE/'control';OUT=BASE/'remote-recovery-08-terminal-01'
remote=r'''
from pathlib import Path
import json,hashlib,gzip,base64,socket,datetime
root=Path('/mnt/seagate10tb/orbit-v31-correctness-08-florianpfaff');post=root/'postprocess-07-01';run=root/'validation-07'
pipeline_raw=(run/'pipeline.json').read_bytes();post_raw=(post/'pipeline.json').read_bytes()
pipeline=json.loads(pipeline_raw);finished=json.loads(post_raw)
assert pipeline['status'] in ('passed','failed') and pipeline['finished_at'] and pipeline['final_cleanup']['verified'] is True
assert finished['status'] in ('completed','failed') and finished['finished_at'] and len(finished['steps'])==3 and all(x['cleanup_verified'] for x in finished['steps'])
assert finished['validation_pipeline']['sha256']==hashlib.sha256(pipeline_raw).hexdigest()
assert pipeline['execution']['path']==str(root/'control/candidate07-execution.json')
paths=[p for p in (root/'control').iterdir() if p.is_file() and p.suffix in ('.py','.json','.log')]
paths += [p for p in run.iterdir() if p.is_file() and p.suffix in ('.json','.log','.xml')]
for pattern in ('*/result.json','objective-*/validation.json','nuisance-replay*/receipt.json'):
 paths+=list(run.glob(pattern))
# A failed point is omitted from the objective's completed-profile list.
# Preserve its complete compact iteration evidence separately, without row spools.
failed_points=[]
for receipt in sorted(run.glob('objective-*/point-*/profile.execution.json')):
 execution=json.loads(receipt.read_bytes())
 if execution.get('returncode')!=0 or execution.get('timed_out'):
  point=receipt.parent;selected=list(point.glob('*.json'))
  selected += [point/name for name in ('profile.xml','profile.log') if (point/name).is_file()]
  paths += selected
  external=[]
  for path in sorted(point.glob('qr.*')):
   if path.is_file() and (path.name.endswith(('.R.bin','.z.bin','.rhs.bin','.rows.tsv','.rows.tsv.gz'))):
    h=hashlib.sha256()
    with path.open('rb') as stream:
     for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    external.append({'path':str(path),'bytes':path.stat().st_size,'sha256':h.hexdigest(),'storage':'external_only_not_transferred'})
  failed_points.append({'point':str(point.relative_to(root)),'execution':execution,'selected_files':[str(p.relative_to(root)) for p in sorted(selected)],'external_native_artifacts':external,'row_spools_transferred':False})
# Preserve the generated report/audit and failed collector journal, without recopying a partial publication subtree.
paths += [p for p in post.rglob('*') if p.is_file() and 'publication' not in p.relative_to(post).parts]
partial=post/'publication'
partial_inventory=[{'path':str(p.relative_to(root)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size} for p in sorted(partial.rglob('*')) if p.is_file()] if partial.exists() else []
rows=[];raw_total=0;packed_total=0
for path in sorted(set(paths)):
 assert not path.is_symlink() and path.stat().st_size<=64*1024*1024
 raw=path.read_bytes();raw_total+=len(raw);name=str(path.relative_to(root));encoding='identity';packed=raw
 if name in ('postprocess-07-01/independent-audit.json','postprocess-07-01/report/summary.json','postprocess-07-01/report/index.html') or len(raw)>16*1024*1024:
  packed=gzip.compress(raw,mtime=0);encoding='gzip';name+='.gz'
 assert len(packed)<=16*1024*1024;packed_total+=len(packed);assert packed_total<=64*1024*1024
 rows.append({'source':str(path),'relative':name,'original_sha256':hashlib.sha256(raw).hexdigest(),'original_bytes':len(raw),'encoding':encoding,'sha256':hashlib.sha256(packed).hexdigest(),'bytes':len(packed),'base64':base64.b64encode(packed).decode()})
assert (run/'pipeline.json').read_bytes()==pipeline_raw and (post/'pipeline.json').read_bytes()==post_raw
print(json.dumps({'schema':'orbit-poc-terminal08-bounded-transfer-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'hostname':socket.gethostname(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'execution_attempt':'08','candidate_control_version':'07','remote_root':str(root),'raw_bytes':raw_total,'transfer_bytes':packed_total,'files':rows,'validation_status':pipeline['status'],'postprocess_status':finished['status'],'native':pipeline.get('native'),'failed_objective_points':failed_points,'partial_collector_publication_inventory':partial_inventory,'partial_collector_publication_transferred':False,'scope':'Terminal original controls, full generated audit/report and all failed-point compact iteration receipts retained. No row spools, native binaries or partial collector duplicate trees transferred.'}))
'''
if __name__=='__main__':
 envelope=CONTROL/'terminal08-transfer-envelope.json';assert not OUT.exists()
 with envelope.open('xb') as stream:
  result=subprocess.run(['/mnt/c/Windows/System32/OpenSSH/ssh.exe','-o','ConnectTimeout=10','gpuserver4090','/usr/bin/python3','-'],input=remote.encode(),stdout=stream,stderr=subprocess.PIPE)
 if result.returncode:raise RuntimeError('Remote transfer failed: '+result.stderr.decode())
 value=json.loads(envelope.read_bytes());OUT.mkdir();manifest=[]
 for row in value['files']:
  relative=Path(row['relative']);assert not relative.is_absolute() and '..' not in relative.parts
  raw=base64.b64decode(row['base64'],validate=True);assert len(raw)==row['bytes'] and hashlib.sha256(raw).hexdigest()==row['sha256']
  original=gzip.decompress(raw) if row['encoding']=='gzip' else raw
  assert len(original)==row['original_bytes'] and hashlib.sha256(original).hexdigest()==row['original_sha256']
  path=OUT/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
  manifest.append({k:v for k,v in row.items() if k!='base64'})
 value['files']=manifest;value['local_root']=str(OUT);value['local_match_verified']=True
 path=CONTROL/'terminal08-transfer-manifest.json';path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
 print(json.dumps({'output':str(OUT),'manifest_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'files':len(manifest),'raw_bytes':value['raw_bytes'],'transfer_bytes':value['transfer_bytes']}))
