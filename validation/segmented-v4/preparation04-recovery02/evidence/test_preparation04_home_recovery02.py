import copy, importlib.util, json, os, pathlib, subprocess, sys, time, types
import pytest
C=pathlib.Path(__file__).parent
def module(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
m=module('recovery',C/'recover_preparation04_startup02.py')
@pytest.fixture
def envspec(tmp_path):
 return {'PATH':'/usr/bin:/bin','HOME':str(tmp_path),'PYTHONDONTWRITEBYTECODE':'1'}
def account(envspec):return {'uid':os.getuid(),'username':'fixture','home':envspec['HOME']}
def actual(envspec):return types.SimpleNamespace(pw_name='fixture',pw_dir=envspec['HOME'])
def test_proper_passwd_home(envspec):assert m.environment_for(account(envspec),envspec,actual(envspec))==envspec
@pytest.mark.parametrize('change',[{'HOME':'/tmp/scratch'},{'PATH':'/evil/bin'},{'LD_PRELOAD':'evil.so'},{'PYTHONDONTWRITEBYTECODE':'0'}])
def test_reject_environment_changes(envspec,change):
 env=dict(envspec,**change)
 with pytest.raises(RuntimeError):m.environment_for(account(envspec),env,actual(envspec))
def test_reject_account_mismatch(envspec):
 with pytest.raises(RuntimeError):m.environment_for(dict(account(envspec),uid=os.getuid()+1),envspec,actual(envspec))
def test_reject_symlink_home(tmp_path,envspec):
 link=tmp_path/'alias';link.symlink_to(tmp_path);envspec['HOME']=str(link)
 with pytest.raises(RuntimeError):m.environment_for(account(envspec),envspec,actual(envspec))
@pytest.mark.parametrize('raises',[False,True])
def test_contaminated_parent_environment_is_replaced_and_restored(monkeypatch,envspec,raises):
 monkeypatch.setenv('HOME','/wrong/control');monkeypatch.setenv('LD_PRELOAD','evil.so');old=dict(os.environ)
 try:
  with m.controlled_environment(envspec):
   assert dict(os.environ)==envspec
   if raises:raise ValueError('fixture')
 except ValueError:pass
 assert dict(os.environ)==old

def test_unchanged_smoke_passes_proper_home_to_child(tmp_path,monkeypatch,envspec):
 s=module('old_smoke',C/'smoke_segmented_preparation01.py');root=tmp_path/'scratch';result=root/'temporary/probe-result/result.json';record={}
 e={'paths':{'source':str(tmp_path),'prefix':str(tmp_path),'wrapper':'/unused','python':sys.executable},'runtime_artifacts':{'control_python':{'path':sys.executable}}}
 p={'execution':{'path':str(tmp_path/'e.json')},'driver':{'path':'unused'},'output':str(root),'global_lock':str(tmp_path/'lock'),'probe_plan':{'path':'unused','sha256':'x'},'helper':{}}
 q={'helper':{'path':'unused'},'output':str(result.parent),'config':{'path':'same','sha256':'same'},'source_sha256':'same'}
 def save(path,value):pathlib.Path(path).write_text(json.dumps(value))
 def supervise(command,**kw):
  record['env']=kw['env'];child=subprocess.run([sys.executable,'-c','import os,json;print(json.dumps({k:os.environ[k] for k in ("HOME","PATH","PYTHONDONTWRITEBYTECODE")}))'],env=kw['env'],capture_output=True,text=True,check=True);record['child']=json.loads(child.stdout);result.parent.mkdir(parents=True);save(result,{'status':'passed','physical_propagations':0,'benchmark_fits':0,'config':q['config'],'source_sha256':'same'});return 0
 d=types.SimpleNamespace(load_execution=lambda _:e,admission=lambda *a:{'status':'admitted'},save=save,prepare_writable_directories=lambda _:None,artifact=lambda p:{'path':str(p),'sha256':'fixture'},supervise=supervise,cleanup_signals=lambda:m.contextlib.nullcontext(),stamp=lambda:'fixture',interrupted=lambda *a:None)
 monkeypatch.setattr(s,'inspect',lambda *a:(p,e,q));monkeypatch.setattr(s,'load',lambda *a:d);monkeypatch.setattr(s,'checked',lambda *a:None)
 monkeypatch.setenv('HOME','/wrong/control');monkeypatch.setenv('LD_PRELOAD','evil.so')
 with m.controlled_environment(envspec):assert s.main(['--plan',str(tmp_path/'plan'),'--sha256','fixture'])==0
 assert record['child']==envspec and 'LD_PRELOAD' not in record['env']

def test_unchanged_durable_launcher_passes_proper_home_to_actual_child(tmp_path,monkeypatch,envspec):
 s=module('old_launcher',C/'launch_segmented_preparation01.py');driver=tmp_path/'run_segmented_preparation01.py';output=tmp_path/'child-env.json'
 driver.write_text('import os,json,time\nfrom pathlib import Path\nPath('+repr(str(output))+').write_text(json.dumps({k:os.environ[k] for k in ("HOME","PATH","PYTHONDONTWRITEBYTECODE")}))\ntime.sleep(30)\n')
 plan=tmp_path/'plan.json';plan.write_text(json.dumps({'control_root':str(tmp_path)}));execution=tmp_path/'execution.json';execution.write_text(json.dumps({'paths':{'source':str(tmp_path)},'runtime_artifacts':{'control_python':{'path':sys.executable}}}));pins=tmp_path/'pins.json';pins.write_text(json.dumps({'control_root':str(tmp_path),'driver_sha256':m.sha(driver),'execution_sha256':m.sha(execution),'plan':{'path':str(plan),'sha256':m.sha(plan)}}))
 original=subprocess.Popen;children=[]
 def start(*a,**kw):
  child=original(*a,**kw);children.append(child);return child
 monkeypatch.setattr(s.subprocess,'Popen',start);monkeypatch.setattr(sys,'argv',['launcher','--execution',str(execution),'--pins',str(pins),'--pins-sha256',m.sha(pins)]);monkeypatch.setenv('HOME','/wrong/control');monkeypatch.setenv('LD_PRELOAD','evil.so')
 try:
  with m.controlled_environment(envspec):s.main()
  deadline=time.monotonic()+5
  while not output.exists() and time.monotonic()<deadline:time.sleep(.01)
  assert json.loads(output.read_text())==envspec
  receipt=json.loads((tmp_path/'preparation-launch.json').read_text());assert receipt['launch_committed'] and receipt['driver_process']['pid']==children[0].pid
 finally:
  for child in children:
   if child.poll() is None:child.terminate()
   child.wait(timeout=5)

def controls():
 a={'output':'/root/staging/preparation-04/startup-01','probe_plan':{'path':'old','sha256':'old'},'execution':'fixed'};b={'output':a['output']+'/temporary/probe-result','helper':'fixed'};c=dict(a,output='/root/staging/preparation-04/startup-02',probe_plan={'path':'new','sha256':'new'});d=dict(b,output=c['output']+'/temporary/probe-result');return a,b,c,d
def test_only_new_output_and_probe_pin_delta():m.validate_delta(*controls(),'/root')
@pytest.mark.parametrize('target,key,value',[(2,'execution','changed'),(3,'helper','changed'),(2,'output','/root/staging/preparation-04/startup-01'),(3,'extra',True)])
def test_reject_other_startup_delta(target,key,value):
 values=list(controls());values[target][key]=value
 with pytest.raises(RuntimeError):m.validate_delta(*values,'/root')

def receipt():
 p={'smoke':{'path':'smoke','sha256':'a'},'probe':{'path':'probe','sha256':'b'},'execution':{'path':'execution','sha256':'c'}}
 r={'status':'passed','physical_propagations':0,'benchmark_fits':0,'plan':p['smoke'],'probe_plan':p['probe'],'execution':p['execution'],'final_cleanup':{'verified':True,'errors':[],'commands':[{'verified':True,'live_owned_processes':[],'identities':[{'pid':1,'start_ticks':2}]}]},'result':{'path':'result','sha256':'d'}};return p,r
@pytest.mark.parametrize('bad',['status','fits','cleanup','live','attribution','result'])
def test_reject_bad_actual_startup(monkeypatch,bad):
 p,r=receipt();result={'status':'passed','physical_propagations':0,'benchmark_fits':0}
 if bad=='status':r['status']='failed'
 if bad=='fits':r['benchmark_fits']=1
 if bad=='cleanup':r['final_cleanup']['verified']=False
 if bad=='attribution':r['execution']={'path':'different','sha256':'c'}
 if bad=='result':result['status']='failed'
 monkeypatch.setattr(m,'read',lambda _:result)
 with pytest.raises(RuntimeError):m.check_startup(r,p,live=lambda _:bad=='live')
def test_accept_actual_clean_startup(monkeypatch):
 p,r=receipt();monkeypatch.setattr(m,'read',lambda _:{'status':'passed','physical_propagations':0,'benchmark_fits':0});m.check_startup(r,p,live=lambda _:False)
def test_precommit_failure_records_no_handoff(tmp_path):
 j={'handoff_committed':False};m.failure_status(j,RuntimeError('before spawn'),tmp_path/'absent.json');assert j['status']=='failed' and j['handoff_committed'] is False

def test_postcommit_readback_failure_preserves_exact_live_ownership(tmp_path):
 p=tmp_path/'launch.json';identity={'pid':123,'start_ticks':456,'boot_id':'boot'};p.write_text(json.dumps({'launch_committed':True,'driver_process':identity}));j={'handoff_committed':False};m.failure_status(j,PermissionError('/proc read'),p)
 assert j['status']=='handoff_committed_verification_failed' and j['handoff_committed'] is True and j['owned_driver_process']==identity
 assert j['preparation_launch']=={'path':str(p),'sha256':m.sha(p)} and 'Do not relaunch' in j['recovery_policy']

def test_malformed_receipt_is_unresolved_not_no_launch(tmp_path):
 p=tmp_path/'launch.json';p.write_text('{');j={'handoff_committed':False};m.failure_status(j,RuntimeError('readback'),p);assert j['status']=='handoff_identity_unresolved' and j['handoff_committed']=='unresolved' and j['preparation_launch']['sha256']==m.sha(p)
