import importlib.util,json,hashlib,os,fcntl
from pathlib import Path
import pytest
HERE=Path(__file__).parent
spec=importlib.util.spec_from_file_location('append01',HERE/'apply_original150_interrupted_append01.py'); m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def enc(o):return (json.dumps(o,sort_keys=True,indent=2)+'\n').encode()
def sha(b):return hashlib.sha256(b).hexdigest()
def put(p,o):p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(enc(o));return pin(p)
def pin(p):return {'path':str(p),'sha256':sha(p.read_bytes())}
@pytest.fixture
def fixture(tmp_path):
 root=tmp_path/'benchmark';root.mkdir();(root/'numerics.lock').touch(); proposal_root=tmp_path/'proposal';proposal_root.mkdir()
 native=tmp_path/'native';native.write_bytes(b'native');source=tmp_path/'protocol.py';source.write_bytes(b'archived source')
 attempts=[{'attempt_id':f'a{i}','case_id':'c','profile':'qr_lm_staged_jacobian','order':i} for i in range(150)]
 rt={'native':pin(native),'source_sha256':'source'};manifest={'attempts':attempts,'manifest_hash':'manifest','new_runtime':rt,'cases':[{'case_id':'c','fit_request':{'method':'pulses'},'input_manifest_hash':'input'}]};mp=put(root/'manifest.json',manifest)
 cp=put(tmp_path/'config.json',{'controls':{'maximum_trial_evaluations':96}})
 a=attempts[6];d=root/'attempts'/a['attempt_id'];d.mkdir(parents=True)
 job={'method':'pulses','id':a['attempt_id'],'kind':'fit','split':'numerics','numerics_profile':a['profile'],'numerics_manifest_hash':'manifest','input_manifest_hash':'input','source_hash':'source','protocol_hash':'manifest','backend':{'groops_executable':str(native),'command_timeout_seconds':7200.,'retain_native_diagnostics':True},'expected_native_binary_sha256':pin(native)['sha256'],'numerical_controls':{'maximum_trial_evaluations':96}}
 request=put(d/'request.json',job);put(d/'worker-request.json',job)
 prefix=[]
 for item in attempts[:6]:
  td=root/'attempts'/item['attempt_id'];r=put(td/'result.json',{'status':'timeout'});i=put(td/'result-record.json',{'result':r});prefix.append({'attempt_id':item['attempt_id'],'result':r,'index':i})
 obs={'current_boot_id':m.current_boot(),'boot_changed':True,'new_attempt_after_sixth':a,'terminal_checkpoints':6,'interrupted_without_checkpoint':1,'partial_request_hash':m.canonical(job),'copies':[{'source':pin(d/'request.json')}],'partial_files':[{'relative':p.name,'bytes':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns} for p in d.iterdir()]};op=put(tmp_path/'observation.json',obs)
 receipt={'outcome':'interrupted','numerical_rerun':False,'covariance_authorized':False}; rp=put(proposal_root/m.NAMES[0],receipt)
 result={'status':'interrupted','converged':False,'covariance_valid':False,'elapsed_seconds':None,'final_objective':None,'harness_execution':{k:None for k in ['elapsed_seconds','peak_process_tree_rss_bytes','returncode','pid','minimum_free_output_bytes','minimum_free_physical_backing_bytes']},'artifacts':[{'path':str(d/m.NAMES[0]),'sha256':rp['sha256']}]};fp=put(proposal_root/m.NAMES[1],result)
 index={'attempt_id':a['attempt_id'],'request_hash':m.canonical(job),'status':'interrupted','result':{'path':str(d/m.NAMES[1]),'sha256':fp['sha256']}};ip=put(proposal_root/m.NAMES[2],index)
 proposal={'status':'proposed_not_applied','attempt':a,'observation':op,'manifest':mp,'archived_protocol':pin(source),'configuration':cp,'request':request,'request_hash':m.canonical(job),'expected_six_checkpoint_prefix':prefix,'append_files':[{'destination':str(d/name),'candidate':pin(proposal_root/name)} for name in m.NAMES]};pp=put(proposal_root/'proposal.json',proposal)
 audit=put(tmp_path/'review.json',{'passed':True,'proposal':pp})
 plan={'schema':m.SCHEMA,'helper':pin(Path(m.__file__)),'proposal':pp,'independent_review':audit,'boot_id':m.current_boot(),'benchmark_root':str(root)}; plan_path=tmp_path/'plan.json';put(plan_path,plan)
 def run(apply=False):return m.run(plan_path,sha(plan_path.read_bytes()),apply)
 return {'root':root,'d':d,'p':proposal_root,'plan':plan,'plan_path':plan_path,'run':run,'tmp':tmp_path}
def test_inspection_writes_nothing(fixture):
 f=fixture; r=f['run']();assert r['status']=='verified_not_applied';assert all(not (f['d']/n).exists() for n in m.NAMES)
def test_apply_exact_and_idempotent(fixture):
 f=fixture;r=f['run'](True);assert len(r['written'])==3
 assert all((f['d']/n).read_bytes()==(f['p']/n).read_bytes() for n in m.NAMES);assert f['run'](True)['written']==[]
def test_finish_identical_prefix(fixture):
 f=fixture;(f['d']/m.NAMES[0]).write_bytes((f['p']/m.NAMES[0]).read_bytes());assert len(f['run'](True)['written'])==2
@pytest.mark.parametrize('raw',[b'partial',b'{}\n'])
def test_different_existing_bytes_rejected(fixture,raw):
 f=fixture;(f['d']/m.NAMES[0]).write_bytes(raw)
 with pytest.raises(ValueError):f['run'](True)
 assert not (f['d']/m.NAMES[1]).exists()
def test_nonprefix_append_rejected(fixture):
 f=fixture;(f['d']/m.NAMES[2]).write_bytes((f['p']/m.NAMES[2]).read_bytes())
 with pytest.raises(ValueError):f['run'](True)
def test_lock_conflict_rejected(fixture):
 f=fixture
 with (f['root']/'numerics.lock').open('r+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  with pytest.raises(BlockingIOError):f['run'](True)
@pytest.mark.parametrize('kind',['later_work','prefix','request','native','source','unexpected_partial'])
def test_changed_evidence_rejected(fixture,kind):
 f=fixture
 paths={'later_work':f['root']/'attempts/a7/new','prefix':f['root']/'attempts/a0/result.json','request':f['d']/'request.json','native':f['tmp']/'native','source':f['tmp']/'protocol.py','unexpected_partial':f['d']/'new-output'}
 p=paths[kind];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'changed')
 with pytest.raises(ValueError):f['run'](True)
 assert all(not (f['d']/n).exists() for n in m.NAMES)
@pytest.mark.parametrize('kind',['review_false','review_other','boot','extra_plan'])
def test_wrong_authorization_rejected(fixture,kind):
 f=fixture;plan=f['plan']
 if kind.startswith('review_'):
  audit={'passed':kind!='review_false','proposal':plan['proposal'] if kind!='review_other' else {'path':'/other','sha256':'x'}};plan['independent_review']=put(f['tmp']/'review.json',audit)
 elif kind=='boot':plan['boot_id']='oldboot'
 else:plan['unknown']=True
 put(f['plan_path'],plan)
 with pytest.raises(ValueError):f['run'](True)
@pytest.mark.parametrize('kind',['target','candidate','lock','ancestor'])
def test_symlinks_rejected(fixture,kind):
 f=fixture
 if kind=='target':(f['d']/m.NAMES[0]).symlink_to(f['p']/m.NAMES[0])
 elif kind=='candidate':
  p=f['p']/m.NAMES[0];raw=p.read_bytes();p.unlink();other=f['tmp']/'outside';other.write_bytes(raw);p.symlink_to(other)
 elif kind=='lock':
  p=f['root']/'numerics.lock';p.unlink();other=f['tmp']/'lock';other.touch();p.symlink_to(other)
 else:
  p=f['d'];new=f['tmp']/'moved';p.rename(new);p.symlink_to(new,target_is_directory=True)
 with pytest.raises(ValueError):f['run'](True)
def test_interrupted_partial_file_write_is_not_repaired(fixture,monkeypatch):
 f=fixture;real=m.append_exact;calls=[]
 def stop(path,raw):
  calls.append(path)
  if len(calls)==2:
   path.write_bytes(raw[:19]);raise OSError('simulated interruption')
  return real(path,raw)
 monkeypatch.setattr(m,'append_exact',stop)
 with pytest.raises(OSError):f['run'](True)
 monkeypatch.setattr(m,'append_exact',real)
 with pytest.raises(ValueError):f['run'](True)
 assert (f['d']/m.NAMES[1]).stat().st_size==19 and not (f['d']/m.NAMES[2]).exists()
