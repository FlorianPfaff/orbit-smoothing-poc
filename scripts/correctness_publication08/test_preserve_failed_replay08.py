import base64,copy,importlib.util,json
from pathlib import Path
import pytest
p=Path(__file__).with_name('preserve_failed_replay08.py');s=importlib.util.spec_from_file_location('replay08',p);A=importlib.util.module_from_spec(s);s.loader.exec_module(A)
def fixture():
 files={'receipt.json':b'{"status":"failed"}','profile.xml':b'<profile/>','profile.log':b'failed'}
 for n in range(1,15):
  files[f'qr.{n}.nuisance_line_search.json']=json.dumps({'schema':'orbit-poc-native-nuisance-line-search-v1','accepted':n<14,'undamped_maximum_update_m':3.25e-8,'trials':[]}).encode()
  for suffix in ('profile.json','factor.json')+(('retention.json',) if n<14 else ()):files[f'qr.{n}.{suffix}']=b'{}'
 rows=[{'name':n,'sha256':A.M.digest(raw),'bytes':len(raw),'base64':base64.b64encode(raw).decode()} for n,raw in files.items()]
 journals={'validation-07/pipeline.json':'a'*64,'postprocess-07-01/pipeline.json':'b'*64}
 main={'execution_attempt':'08','candidate_control_version':'07','validation_status':'failed','local_match_verified':True,'files':[{'source':A.ROOT+'/'+r,'original_sha256':h} for r,h in journals.items()]+[{'source':A.ROOT+'/'+A.REPLAY+'/receipt.json','original_sha256':A.M.digest(files['receipt.json']),'original_bytes':len(files['receipt.json'])}]}
 value={'schema':'orbit-poc-failed-replay08-transfer-v1','root':A.ROOT,'replay':A.REPLAY,'journals':journals,'cleanup_verified':True,'step':{'name':'nuisance-replay-candidate1-point012','returncode':1,'status':'failed'},'files':rows,'external':[]}
 return value,main

def test_full_fourteen_generations(tmp_path):
 value,main=fixture();report=A.publish(value,main,'c'*64,tmp_path/'out');assert report['scientific_gate_substitution'] is False
 summary=json.loads((tmp_path/'out/summary.json').read_text());assert len(summary['iterations'])==14 and summary['final_retention_receipt_present'] is False and summary['covariance_authorized'] is False
 for n,pin in report['files'].items():assert A.M.digest((tmp_path/'out'/n).read_bytes())==pin['sha256']

@pytest.mark.parametrize('case',range(10))
def test_reject_changed_identity_or_history(case,tmp_path):
 v,m=fixture()
 if case==0:v['replay']='validation-07/nuisance-replay'
 elif case==1:v['journals']['validation-07/pipeline.json']='z'*64
 elif case==2:v['cleanup_verified']=False
 elif case==3:v['step']['returncode']=0
 elif case==4:v['files']=[r for r in v['files'] if r['name']!='qr.8.nuisance_line_search.json']
 elif case==5:v['files']=[r for r in v['files'] if r['name']!='qr.13.retention.json']
 elif case==6:v['files'][0]['base64']=base64.b64encode(b'tamper').decode()
 elif case==7:v['files'].append(copy.deepcopy(v['files'][0]))
 elif case==8:m['files'][-1]['original_sha256']='q'*64
 elif case==9:m['execution_attempt']='07'
 with pytest.raises((ValueError,KeyError)):A.publish(v,m,'c'*64,tmp_path/'out')
 assert not (tmp_path/'out').exists()

def test_no_overwrite(tmp_path):
 v,m=fixture();out=tmp_path/'out';out.mkdir()
 with pytest.raises(ValueError):A.publish(v,m,'c'*64,out)
