from pathlib import Path
import importlib.util,json,types,pytest
s=importlib.util.spec_from_file_location('shift_stage',Path(__file__).with_name('stage_shifted_diagnostic01.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def put(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v));return m.pin(p)
def source(p):return {'files':{str(x.relative_to(p)):m.pin(x)['sha256'] for x in sorted(Path(p).rglob('*')) if x.is_file()}}
@pytest.fixture
def case(tmp_path,monkeypatch):
 old=tmp_path/'validation';(old/'source').mkdir(parents=True);(old/'source/a.py').write_text('unchanged')
 e={'paths':{'root':str(old),'source':str(old/'source')},'read_only_bindings':[],'runtime_artifacts':{}}
 p={'schema':'orbit-poc-shifted-stage-input-v1','execution':put(old/'control/execution.json',e),'source_freeze':put(old/'control/source-freeze.json',{'source':source(old/'source')}),'config':put(old/'control/config.json',{'segmented_runtime':{'source_root':str(old/'source'),'segmented_solver':{'path':'/solver','sha256':'a'*64}},'dense_runtime':{'source_root':str(old/'source')}}),'output_root':str(tmp_path/'diagnostic'),'helpers':{}}
 steps=[{'name':name,'status':'passed'} for name in m.STAGES]
 for step in steps[-2:]:step['evidence']={'result':put(old/(step['name']+'.json'),{'passed':True})}
 p['pipeline']=put(old/'run/pipeline.json',{'status':'passed','steps':steps});original=put(old/'control/launch-plan.json',{'global_lock':str(tmp_path/'lock')})
 p['controller']=put(old/'control/controller.json',{'status':'passed','final_cleanup':{'verified':True},'cli_validation':{'pipeline':p['pipeline']},'plan':original})
 for key,name in m.HELPERS.items():q=tmp_path/'helpers'/name;q.parent.mkdir(exist_ok=True);q.write_text('# pinned '+key);p['helpers'][key]=m.pin(q)
 d=types.SimpleNamespace(source_receipt=source,load_execution=lambda p:json.loads(Path(p).read_text()));monkeypatch.setattr(m,'load',lambda path:d)
 return p,e,d
def change(p,key,fn):
 v=json.loads(Path(p[key]['path']).read_text());fn(v);p[key]=put(Path(p[key]['path']),v)
def test_copy_and_exact_readonly_old_context_with_absent_mutables(case):
 p,e,d=case;before={k:m.pin(v['path']) for k,v in p.items() if isinstance(v,dict) and set(v)=={'path','sha256'}};v=m.stage(p);root=Path(p['output_root']);new=json.loads(Path(v['execution']['path']).read_text());plan=json.loads(Path(v['plan']['path']).read_text())
 assert v['status']=='staged_unexecuted' and source(root/'source')==source(Path(e['paths']['source']))
 assert {'source':e['paths']['root'],'target':e['paths']['root']} in new['read_only_bindings']
 assert all(not Path(x).exists() for x in v['fresh_mutable_paths']);assert plan['config']==p['config'] and plan['pipeline']==p['pipeline'] and plan['controller']==p['controller'];assert plan['wall_limit_seconds']==1800
 assert all(m.pin(x['path'])==x for x in before.values())
@pytest.mark.parametrize('kind',['unknown','changed_pin','helper','existing','overlap','source','config','cleanup','pipeline_status','stage_fail','stage_order','controller_attribution'])
def test_refuses_identity_freshness_or_failed_suite(case,kind):
 p,e,d=case
 if kind=='unknown':p['extra']=True
 if kind=='changed_pin':p['execution']['sha256']='0'*64
 if kind=='helper':p['helpers']['runner']['sha256']='0'*64
 if kind=='existing':Path(p['output_root']).mkdir()
 if kind=='overlap':p['output_root']=str(Path(e['paths']['root'])/'new')
 if kind=='source':Path(e['paths']['source'],'a.py').write_text('changed')
 if kind=='config':change(p,'config',lambda v:v['dense_runtime'].update(source_root='/other'))
 if kind=='cleanup':change(p,'controller',lambda v:v['final_cleanup'].update(verified=False))
 if kind in ('pipeline_status','stage_fail','stage_order'):
  if kind=='pipeline_status':change(p,'pipeline',lambda v:v.update(status='failed'))
  if kind=='stage_fail':change(p,'pipeline',lambda v:v['steps'][0].update(status='failed'))
  if kind=='stage_order':change(p,'pipeline',lambda v:v['steps'].reverse())
  change(p,'controller',lambda v:v['cli_validation'].update(pipeline=p['pipeline']))
 if kind=='controller_attribution':change(p,'controller',lambda v:v['cli_validation']['pipeline'].update(sha256='0'*64))
 with pytest.raises(ValueError):m.stage(p)
