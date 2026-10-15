"""Bounded preservation of the failed execution08 second original replay."""
from pathlib import Path
import argparse,base64,datetime,gzip,hashlib,html,importlib.util,json,re,subprocess
HERE=Path(__file__).parent
HELPER=HERE/'publish_bounded_retry.py'
HELPER_SHA='0a2a33dde1906981dae09fce1dae1683e1c60783adad8c3d38d9af3545ccebf5'
assert hashlib.sha256(HELPER.read_bytes()).hexdigest()==HELPER_SHA
spec=importlib.util.spec_from_file_location('bounded_replay08',HELPER);M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
ROOT='/mnt/seagate10tb/orbit-v31-correctness-08-florianpfaff'
REPLAY='validation-07/nuisance-replay-candidate1-point012'
REMOTE=r'''
from pathlib import Path
import json,hashlib,base64,sys
plan=json.load(sys.stdin);root=Path(plan['root']);point=root/plan['replay'];records=[];external=[]
for rel,expected in plan['journals'].items():assert hashlib.sha256((root/rel).read_bytes()).hexdigest()==expected
pipeline=json.loads((root/'validation-07/pipeline.json').read_bytes());post=json.loads((root/'postprocess-07-01/pipeline.json').read_bytes())
assert pipeline['status']=='failed' and pipeline['final_cleanup']['verified'] is True
assert post['status'] in ('failed','completed') and post['finished_at'] and all(s['cleanup_verified'] for s in post['steps'])
step=[s for s in pipeline['steps'] if s['name']=='nuisance-replay-candidate1-point012'];assert len(step)==1 and step[0]['returncode']==1
for p in sorted(point.iterdir()):
 if p.is_file() and (p.suffix=='.json' or p.name in ('profile.xml','profile.log')):
  assert not p.is_symlink() and p.stat().st_size<=16*1024*1024
  raw=p.read_bytes();records.append({'name':p.name,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'base64':base64.b64encode(raw).decode()})
 elif p.is_file() and p.name.endswith(('.R.bin','.z.bin','.rhs.bin','.rows.tsv','.rows.tsv.gz')):
  h=hashlib.sha256()
  with p.open('rb') as f:
   for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
  external.append({'name':p.name,'sha256':h.hexdigest(),'bytes':p.stat().st_size,'storage':'external_only_not_transferred'})
assert sum(r['bytes'] for r in records)<=32*1024*1024
for rel,expected in plan['journals'].items():assert hashlib.sha256((root/rel).read_bytes()).hexdigest()==expected
print(json.dumps({'schema':'orbit-poc-failed-replay08-transfer-v1','root':str(root),'replay':plan['replay'],'journals':plan['journals'],'files':records,'external':external,'step':{k:step[0][k] for k in ('name','status','returncode','elapsed_seconds','started_at','finished_at')},'cleanup_verified':True}))
'''
def inspect(value, main):
 M.require(value['schema']=='orbit-poc-failed-replay08-transfer-v1' and value['root']==ROOT and value['replay']==REPLAY,'Wrong replay attribution')
 M.require(main['execution_attempt']=='08' and main['candidate_control_version']=='07' and main['validation_status']=='failed' and main['local_match_verified'] is True,'Wrong terminal transfer')
 by_source={r['source']:r for r in main['files']}
 expected={rel:by_source[ROOT+'/'+rel]['original_sha256'] for rel in ('validation-07/pipeline.json','postprocess-07-01/pipeline.json')}
 M.require(value['journals']==expected and value['cleanup_verified'] is True,'Terminal journal mismatch')
 M.require(value['step']['name']=='nuisance-replay-candidate1-point012' and value['step']['returncode']==1 and value['step']['status']=='failed','Failed step missing')
 files={};generations={}
 for record in value['files']:
  name=record['name'];M.require(name==Path(name).name and name not in files and (name.endswith('.json') or name in ('profile.xml','profile.log')),'Unexpected or duplicate evidence file')
  raw=base64.b64decode(record['base64'],validate=True);M.require(len(raw)==record['bytes']<=16*1024*1024 and M.digest(raw)==record['sha256'],'Evidence bytes changed');files[name]=raw
  match=re.fullmatch(r'qr\.(\d+)\.nuisance_line_search\.json',name)
  if match:
   n=int(match[1]);d=M.decode(raw);M.require(d['schema']=='orbit-poc-native-nuisance-line-search-v1' and ('generation' not in d or d['generation']==n),'Invalid line-search identity');generations[n]=d
 M.require(sorted(generations)==list(range(1,15)),'Expected complete fourteen-generation replay')
 for n in generations:
  for suffix in ('profile.json','factor.json'):M.require(f'qr.{n}.{suffix}' in files,'Missing factor/profile')
  if n<14:M.require(f'qr.{n}.retention.json' in files,'Missing superseded factor retention')
 for name in ('receipt.json','profile.xml','profile.log'):M.require(name in files,'Missing replay context')
 original=by_source[ROOT+'/'+REPLAY+'/receipt.json'];M.require(M.digest(files['receipt.json'])==original['original_sha256'] and len(files['receipt.json'])==original['original_bytes'],'Replay receipt differs from terminal transfer')
 M.require(generations[14]['accepted'] is False,'Final line search is not failed')
 M.require(sum(map(len,files.values()))<=32*1024*1024,'Bound exceeded')
 return files,generations

def publish(value,main,main_sha,output):
 files,generations=inspect(value,main);M.require(output.is_absolute() and not output.exists(),'New output required')
 packed={};inventory={}
 for name,raw in files.items():
  cleaned=M.scrub(raw.decode()).encode();stored=gzip.compress(cleaned,mtime=0);packed[name+'.gz']=stored;inventory[name+'.gz']={'sha256':M.digest(stored),'bytes':len(stored),'original_sha256':M.digest(raw),'original_bytes':len(raw),'published_expanded_sha256':M.digest(cleaned),'published_expanded_bytes':len(cleaned)}
 rows=[];details={}
 for n,d in generations.items():
  details[n]={k:d.get(k) for k in ('accepted','undamped_maximum_update_m','full_step_prediction','nuisance_floor_limited','floor_rejection')};details[n]['trials']=len(d.get('trials',[]))
  links=' '.join('<a href="qr.'+str(n)+'.'+suffix+'.gz">'+label+'</a>' for suffix,label in [('nuisance_line_search.json','search'),('profile.json','profile'),('factor.json','factor')]+([('retention.json','retention')] if n<14 else []))
  rows.append('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in (n,d.get('undamped_maximum_update_m'),d.get('accepted'),len(d.get('trials',[]))))+'<td>'+links+'</td></tr>')
 summary={'schema':'orbit-poc-failed-replay08-publication-summary-v1','execution_attempt':'08','candidate_control_version':'07','replay':REPLAY,'terminal_transfer_sha256':main_sha,'step':value['step'],'iterations':details,'external_native_artifacts':value['external'],'scientific_gate_substitution':False,'covariance_authorized':False,'final_retention_receipt_present':'qr.14.retention.json' in files}
 packed['summary.json']=M.encoded(M.decode(M.scrub(M.encoded(summary).decode())))
 packed['index.html']=('<!doctype html><html lang="en"><meta charset="utf-8"><title>Execution08 failed second original replay</title><style>body{font:16px system-ui;max-width:1000px;margin:2rem auto}td,th{border:1px solid #ccd;padding:.4rem}table{border-collapse:collapse}</style><h1>Execution08 failed second original replay</h1><p>The prescribed candidate1 point012 replay failed at generation14. All fourteen compact iteration histories are preserved; the final factor has no superseding-factor retention receipt. These are recorded native fields, not a new gate or convergence decision. The failed required gate remains failed and cannot authorize covariance.</p><p><a href="receipt.json.gz">Original replay receipt</a>; <a href="profile.xml.gz">exact profile XML</a>; <a href="profile.log.gz">complete native log</a>; <a href="summary.json">summary</a>; <a href="manifest.json">manifest</a>.</p><table><tr><th>Generation</th><th>Undamped maximum update (m)</th><th>Accepted</th><th>Trials</th><th>Receipts</th></tr>'+''.join(rows)+'</table><p>Private paths are tokenized; original and transformed hashes are retained. Row spools and binary factors remain external.</p></html>').encode()
 for name in ('summary.json','index.html'):inventory[name]={'sha256':M.digest(packed[name]),'bytes':len(packed[name]),'transformation':'presentation of recorded fields'}
 manifest={'schema':'orbit-poc-failed-replay08-publication-v1','execution_attempt':'08','terminal_transfer_sha256':main_sha,'transfer_sha256':M.digest(M.encoded(value)),'helper_sha256':M.digest(Path(__file__).read_bytes()),'files':inventory,'bytes':sum(map(len,packed.values())),'scientific_gate_substitution':False}
 output.mkdir(parents=True)
 for name,raw in packed.items():(output/name).write_bytes(raw)
 (output/'manifest.json').write_bytes(M.encoded(manifest));return manifest

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--manifest-sha256',required=True);p.add_argument('--raw-output',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();raw=a.manifest.read_bytes();M.require(M.digest(raw)==a.manifest_sha256,'Terminal transfer pin changed');main=M.decode(raw)
 M.require(not a.raw_output.exists() and not a.output.exists(),'New outputs required')
 source={x['source']:x for x in main['files']};plan={'root':ROOT,'replay':REPLAY,'journals':{rel:source[ROOT+'/'+rel]['original_sha256'] for rel in ('validation-07/pipeline.json','postprocess-07-01/pipeline.json')}}
 command='/usr/bin/python3 -c '+__import__('shlex').quote(REMOTE)
 result=subprocess.run(['/mnt/c/Windows/System32/OpenSSH/ssh.exe','-o','ConnectTimeout=10','gpuserver4090',command],input=json.dumps(plan).encode(),capture_output=True,check=True)
 value=M.decode(result.stdout);files,_=inspect(value,main);a.raw_output.mkdir(parents=True)
 (a.raw_output/'transfer.json').write_bytes(M.encoded(value))
 for name,data in files.items():(a.raw_output/name).write_bytes(data)
 report=publish(value,main,a.manifest_sha256,a.output);print(json.dumps({'files':len(report['files']),'bytes':report['bytes'],'manifest_sha256':M.digest((a.output/'manifest.json').read_bytes())}))
