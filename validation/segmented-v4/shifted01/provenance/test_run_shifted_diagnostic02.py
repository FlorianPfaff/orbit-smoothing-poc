from pathlib import Path
import importlib.util,json,inspect,pytest
spec=importlib.util.spec_from_file_location('runner',Path(__file__).with_name('run_shifted_diagnostic02.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def save(p,v):p.write_text(json.dumps(v));return {'path':str(p),'sha256':m.sha(p)}
@pytest.fixture
def fixture(tmp_path):
 f=tmp_path/'artifact';f.write_text('sealed');generic={'path':str(f),'sha256':m.sha(f)}
 validations={k:save(tmp_path/(k+'.json'),{'passed':True}) for k in m.METHODS}
 pp=save(tmp_path/'pipeline.json',{'status':'passed','steps':[{'name':n,'status':'passed','evidence':{'result':validations[n.removeprefix('linearization-')]}} if n.startswith('linearization-') else {'name':n,'status':'passed'} for n in m.STAGES]})
 cp=save(tmp_path/'controller.json',{'status':'passed','final_cleanup':{'verified':True},'cli_validation':{'pipeline':pp}})
 source=save(tmp_path/'source.json',{'comparison_source':{'sha256':'source'},'source':{}})
 p={k:dict(generic) for k in m.PINKEYS};p.update(schema='orbit-poc-shifted-diagnostic-owned-plan-v1',validations=validations,global_lock='/tmp/lock',wall_limit_seconds=1800,controller=cp,pipeline=pp,source_freeze=source)
 path=tmp_path/'plan.json';save(path,p);return path,p

def test_plan_accepted(fixture):
 path,p=fixture;assert m.load_plan(path,m.sha(path))==p
@pytest.mark.parametrize('kind',['schema','extra','bound','lock','method','digest','active','cleanup','pipeline_identity','gate_missing','gate_failed','gate_order','gate_result'])
def test_invalid_plan_rejected(fixture,kind):
 path,p=fixture
 if kind=='schema':p['schema']='bad'
 elif kind=='extra':p['extra']=1
 elif kind=='bound':p['wall_limit_seconds']=3600
 elif kind=='lock':p['global_lock']='relative'
 elif kind=='method':p['validations'].pop('pulses')
 elif kind=='digest':p['diagnostic']['sha256']='0'*64
 elif kind in ('active','cleanup','pipeline_identity'):
  cp=Path(p['controller']['path']);v=json.loads(cp.read_text())
  if kind=='active':v['status']='running'
  if kind=='cleanup':v['final_cleanup']['verified']=False
  if kind=='pipeline_identity':v['cli_validation']['pipeline']['sha256']='bad'
  p['controller']=save(cp,v)
 else:
  pp=Path(p['pipeline']['path']);v=json.loads(pp.read_text())
  if kind=='gate_missing':v['steps'].pop()
  if kind=='gate_failed':v['steps'][0]['status']='failed'
  if kind=='gate_order':v['steps'].reverse()
  if kind=='gate_result':v['steps'][-1]['evidence']['result']['sha256']='bad'
  p['pipeline']=save(pp,v);cp=Path(p['controller']['path']);v=json.loads(cp.read_text());v['cli_validation']['pipeline']=p['pipeline'];p['controller']=save(cp,v)
 save(path,p)
 with pytest.raises(RuntimeError):m.load_plan(path,m.sha(path))
def test_exact_command_scope(fixture):
 _,p=fixture;e={'paths':{'wrapper':'/wrapper','python':'/python','source':'/source','run':'/run'},'runtime_artifacts':{'control_python':{'path':'/control-python'}}};v=m.command(e,p,'pulses')
 assert v[:11]==['/control-python','/wrapper','--execution',p['execution']['path'],'--execution-sha256',p['execution']['sha256'],'--','/usr/bin/taskset','-c','24','/usr/bin/prlimit']
 assert '--as=8589934592' in v and v[v.index('--output')+1]=='/run/pulses'
 assert v[v.index('--validation')+1]==p['validations']['pulses']['path'] and v[v.index('--source-sha256')+1]=='source'
 assert not any(x in v for x in ('prepare','fit','run','groops'))
def test_owned_supervision_cleanup_and_guard_preserved():
 s=inspect.getsource(m.main)
 for token in ('d.supervise(', 'd.admission(e,registry)', 'with d.cleanup_signals()', 'signal.signal(sig,d.interrupted)', 'child.cleanup(force=child.child.poll() is None)', "d.source_receipt(paths['source'])==freeze['source']",'fcntl.LOCK_EX|fcntl.LOCK_NB','load_plan(a.plan,a.sha256)==p'):
  assert token in s
 assert "'physical_evaluations':0" in s and "'benchmark_attempts':0" in s and "'release_ready':False" in s
@pytest.mark.parametrize('mode',['passed','coverage','interrupt','cleanup_failure'])
def test_main_owned_lifecycle(tmp_path,monkeypatch,mode):
 import types,contextlib,signal
 root=tmp_path/'diagnostic';control=root/'control';control.mkdir(parents=True);source=tmp_path/'source';source.mkdir();prefix=tmp_path/'prefix';prefix.mkdir()
 paths={k:str(root/k) for k in ('native_source','build','binaries','run','temporary')};paths.update(root=str(root),control=str(control),source=str(source),prefix=str(prefix),wrapper='/wrapper',python='/python')
 sealed=tmp_path/'sealed';sealed.write_text('runtime');runtime={'control_python':{'path':str(sealed),'sha256':m.sha(sealed)}}
 e={'paths':paths,'fit_cpu':24,'runtime_artifacts':runtime};ep=save(tmp_path/'execution.json',e);sf=save(tmp_path/'freeze.json',{'source':{'frozen':True},'comparison_source':{'sha256':'source'}})
 pin={'path':str(sealed),'sha256':m.sha(sealed)};p={k:dict(pin) for k in m.PINKEYS};p.update(execution=ep,source_freeze=sf,runner={'path':m.__file__,'sha256':m.sha(m.__file__)},global_lock=str(tmp_path/'global.lock'),wall_limit_seconds=1800,validations={k:dict(pin) for k in m.METHODS})
 planpath=tmp_path/'plan.json';save(planpath,p);monkeypatch.setattr(m,'load_plan',lambda *_:p)
 cleaned=[]
 class Child:
  child=types.SimpleNamespace(poll=lambda:0);last_cleanup={'verified':True}
  def cleanup(self,force):
   cleaned.append(force)
   if mode=='cleanup_failure':raise RuntimeError('cleanup rejected')
 def supervise(argv,**kw):
  kw['registry'].append(Child());kw['on_started'](12)
  if mode=='interrupt':raise KeyboardInterrupt('fixture interrupt')
  method=Path(argv[argv.index('--output')+1]);method.mkdir();save(method/'validation.json',{'physical_evaluations':0,'nuisance_profile_evaluations':0,'fit_covariance_authorized':False,'passed':mode!='coverage','status':'passed' if mode!='coverage' else 'coverage_inadequate'})
  kw['on_finished']({'cleanup':{'verified':True}});return 0 if mode!='coverage' else 1
 def dirs(paths):
  for k in ('native_source','build','binaries','run','temporary'):Path(paths[k]).mkdir()
 d=types.SimpleNamespace(load_execution=lambda _:e,source_receipt=lambda _: {'frozen':True},resolved_host_path=lambda path,_:path,admission=lambda *_:{'status':'admitted'},prepare_writable_directories=dirs,save=lambda path,v:save(path,v),stamp=lambda:'time',artifact=lambda path:{'path':str(path),'sha256':m.sha(path)},proc=lambda pid:{'pid':pid},interrupted=lambda *_:None,supervise=supervise,cleanup_signals=contextlib.nullcontext)
 original_spec=m.importlib.util.spec_from_file_location;original_module=m.importlib.util.module_from_spec
 class Loader:
  def exec_module(self,module):module.__dict__.update(d.__dict__)
 fake=types.SimpleNamespace(loader=Loader())
 monkeypatch.setattr(m.importlib.util,'spec_from_file_location',lambda *_:fake);monkeypatch.setattr(m.importlib.util,'module_from_spec',lambda _:types.ModuleType('owned'))
 previous={s:signal.getsignal(s) for s in (signal.SIGINT,signal.SIGTERM)}
 if mode=='interrupt':
  with pytest.raises(KeyboardInterrupt):m.main(['--plan',str(planpath),'--sha256',m.sha(planpath)])
 else:assert m.main(['--plan',str(planpath),'--sha256',m.sha(planpath)])==(0 if mode=='passed' else 1)
 journal=json.loads((control/'pipeline.json').read_text());assert cleaned and journal['final_cleanup']['verified']==(mode!='cleanup_failure');assert all(signal.getsignal(s)==h for s,h in previous.items())
 assert journal['status']==({'passed':'passed','coverage':'failed_or_coverage_inadequate','interrupt':'failed','cleanup_failure':'failed'}[mode])
