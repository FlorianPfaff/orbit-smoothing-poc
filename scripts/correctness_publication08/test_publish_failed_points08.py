"""Small fabricated archival tests; never run native code."""
import importlib.util,json,gzip,hashlib,re
from pathlib import Path
import pytest
P=Path(__file__).with_name('publish_failed_points08.py');S=importlib.util.spec_from_file_location('failed08',P);M=importlib.util.module_from_spec(S);S.loader.exec_module(M)

def make(tmp_path,omit=None,compress_log=False):
 root=tmp_path/'raw';root.mkdir();point='validation-07/objective-log_drag_ou/point-006-direction-1.0-1-repeat';remote='/mnt/seagate10tb/orbit-v31-correctness-08-florianpfaff';p=root/point;p.mkdir(parents=True)
 exe={'returncode':1,'timed_out':False,'native_binary_sha256':'n'*64};files={'profile.xml':b'<xml/>','profile.log':b'failed profiling /home/florianpfaff/example','profile.execution.json':json.dumps(exe).encode()}
 for n in range(1,53):
  for suffix in ['profile.json','factor.json']:files[f'qr.{n}.{suffix}']=b'{}'
  if n<52:files[f'qr.{n}.retention.json']=b'{}'
  files[f'qr.{n}.nuisance_line_search.json']=json.dumps({'schema':'orbit-poc-native-nuisance-line-search-v1','accepted':False,'undamped_maximum_update_m':2e-8,'full_step_prediction':1e-16,'nuisance_floor_limited':False,'floor_rejection':'unresolved','trials':[{}]*17}).encode()
 if omit:files.pop(omit)
 rows=[]
 for name,raw in files.items():
  compress=compress_log and name=='profile.log';stored=gzip.compress(raw,mtime=0) if compress else raw;stored_name=name+'.gz' if compress else name
  (p/stored_name).write_bytes(stored);h=hashlib.sha256(raw).hexdigest();rows.append({'relative':point+'/'+stored_name,'source':remote+'/'+point+'/'+name,'encoding':'gzip' if compress else 'identity','bytes':len(stored),'sha256':hashlib.sha256(stored).hexdigest(),'original_sha256':h,'original_bytes':len(raw)})
 data={'execution_attempt':'08','candidate_control_version':'07','validation_status':'failed','local_match_verified':True,'local_root':str(root),'remote_root':remote,'files':rows,'failed_objective_points':[{'point':point,'execution':exe,'selected_files':[point+'/'+name for name in files]}]}
 m=tmp_path/'transfer.json';m.write_text(json.dumps(data));return m,hashlib.sha256(m.read_bytes()).hexdigest(),p

@pytest.mark.parametrize('compress_log',[False,True])
def test_complete52_generations(tmp_path,compress_log):
 p,h,_=make(tmp_path,compress_log=compress_log);o=tmp_path/'published';r=M.publish(p,h,o);s=json.loads((o/'summary.json').read_bytes())
 assert s['points'][0]['generations']==52 and len(s['points'][0]['iterations'])==52
 assert s['points'][0]['iterations']['52']['retention_receipt_present'] is False
 assert not s['scientific_gate_substitution'] and not s['covariance_authorized']
 for name,row in r['files'].items():
  raw=(o/name).read_bytes();assert len(raw)==row['bytes'] and hashlib.sha256(raw).hexdigest()==row['sha256']
  if name.endswith('.gz'):assert hashlib.sha256(gzip.decompress(raw)).hexdigest()==row['published_expanded_sha256']
 for link in re.findall('href="([^"]+)"',(o/'index.html').read_text()):assert (o/link).is_file()

@pytest.mark.parametrize('name',['qr.51.retention.json','qr.26.nuisance_line_search.json','qr.52.nuisance_line_search.json'])
def test_incomplete_history_rejected(tmp_path,name):
 p,h,_=make(tmp_path,name)
 with pytest.raises(ValueError):M.publish(p,h,tmp_path/'published')
 assert not (tmp_path/'published').exists()

def test_original_byte_tamper_rejected(tmp_path):
 p,h,d=make(tmp_path);(d/'qr.52.factor.json').write_text('changed')
 with pytest.raises(ValueError):M.publish(p,h,tmp_path/'published')

def test_input_manifest_tamper_rejected(tmp_path):
 p,h,_=make(tmp_path);p.write_text(p.read_text()+' ')
 with pytest.raises(ValueError,match='manifest changed'):M.publish(p,h,tmp_path/'published')
