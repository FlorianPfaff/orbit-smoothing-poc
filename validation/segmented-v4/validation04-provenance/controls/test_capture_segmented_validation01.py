from pathlib import Path
import importlib.util,json,hashlib,gzip,pytest
S=Path(__file__).with_name('capture_segmented_validation01.py');spec=importlib.util.spec_from_file_location('capture',S);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v));return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def fixture(tmp_path,failed=False):
 r=tmp_path/'root';c=r/'control';a=r/'run/validation/attempt-0001'
 ep=save(c/'execution.json',{'paths':{'root':str(r),'control':str(c),'run':str(r/'run')}})
 sf=save(c/'source-freeze.json',{'source':{'files':{'a':'b'},'sha256':'source'}})
 cf=save(c/'segmented-v4.json',{'unchanged':True});neq=save(c/'native-input-equivalence.json',{'same':True})
 plan=save(c/'launch-plan.json',{'execution':ep,'config':cf,'source_freeze':sf,'native_equivalence':neq})
 launch=save(c/'validation-launch.json',{'launch_committed':True,'execution_sha256':ep['sha256'],'driver_process':{'pid':1,'start_ticks':2,'boot_id':'boot'},'argv':['python','runner','--plan',plan['path'],'--sha256',plan['sha256']]})
 steps=[]
 for i,n in enumerate(m.STAGES):
  d=a/n;s={'name':n,'directory':str(d),'status':'failed' if failed and i==0 else 'not_run' if failed else 'passed'}
  if s['status']!='not_run':s['execution']=save(d/'execution.json',{'status':'failed' if failed else 'complete','returncode':1 if failed else 0,'harness_execution':{'owned_process_group_cleaned':True}})
  steps.append(s)
 pp=save(a/'pipeline.json',{'schema':'orbit-poc-segmented-validation-run-v1','status':'failed' if failed else 'passed','steps':steps});save(r/'run/validation/latest.json',{'pipeline':pp})
 save(c/'validation-controller.json',{'status':'failed' if failed else 'passed','returncode':1 if failed else 0,'final_cleanup':{'verified':True},'plan':plan,'source':{'files':{'a':'b'},'sha256':'source'},'admission':{'driver_identity':{'pid':1,'start_ticks':2},'boot_id':'boot'},'cli_validation':{'pipeline':pp}})
 return r,ep['sha256'],launch['sha256']
def rewrite(p,fn):v=json.loads(p.read_text());fn(v);save(p,v)
def repin_pipeline(r):
 p=r/'run/validation/attempt-0001/pipeline.json';pin={'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()};save(r/'run/validation/latest.json',{'pipeline':pin});rewrite(r/'control/validation-controller.json',lambda x:x['cli_validation'].update(pipeline=pin))
@pytest.mark.parametrize('failed',[False,True])
def test_terminal_status_and_missing_preserved(tmp_path,failed):
 r,e,l=fixture(tmp_path,failed);out=tmp_path/'out';v=m.capture(r,e,l,out)
 assert len(v['planned_gates'])==14 and v['pipeline_status']==('failed' if failed else 'passed')
 assert sum(x['status']=='not_run' for x in v['planned_gates'])==(13 if failed else 0)
 for x in v['records']:
  stored=(out/x['stored']['path']).read_bytes();raw=gzip.decompress(stored) if x['encoding']=='gzip' else stored
  assert hashlib.sha256(raw).hexdigest()==x['source']['sha256']
def test_compression_keeps_exact_bytes_and_spools_outside(tmp_path):
 r,e,l=fixture(tmp_path);a=r/'run/validation/attempt-0001/native-tests';(a/'worker.log').write_bytes(b'x'*90000);(a/'rows.bin').write_bytes(b'large data')
 v=m.capture(r,e,l,tmp_path/'out');rec=next(x for x in v['records'] if x['source']['path'].endswith('worker.log'));assert rec['encoding']=='gzip';assert all(not x['source']['path'].endswith('rows.bin') for x in v['records']);assert (a/'rows.bin').read_bytes()==b'large data'
@pytest.mark.parametrize('mutation',['active','cleanup','pid','boot','source','plan','foreign_execution','failed_pass','missing_execution','order','duplicate','active_gate','passed_summary','config'])
def test_identity_status_and_cleanup_fail_closed(tmp_path,mutation):
 r,e,l=fixture(tmp_path);c=r/'control';p=r/'run/validation/attempt-0001/pipeline.json'
 if mutation=='active':rewrite(c/'validation-controller.json',lambda x:x.update(status='running'))
 elif mutation=='cleanup':rewrite(c/'validation-controller.json',lambda x:x.update(final_cleanup={'verified':False}))
 elif mutation=='pid':rewrite(c/'validation-controller.json',lambda x:x['admission']['driver_identity'].update(pid=7))
 elif mutation=='boot':rewrite(c/'validation-controller.json',lambda x:x['admission'].update(boot_id='new'))
 elif mutation=='source':rewrite(c/'validation-controller.json',lambda x:x.update(source={'sha256':'other'}))
 elif mutation=='plan':(c/'launch-plan.json').write_text('{}')
 elif mutation=='config':(c/'segmented-v4.json').write_text('{}')
 else:
  def mutate(x):
   s=x['steps'][0]
   if mutation=='foreign_execution':s['execution']=save(tmp_path/'foreign.json',{'status':'complete','returncode':0,'harness_execution':{'owned_process_group_cleaned':True}})
   if mutation=='failed_pass':s['execution']=save(Path(s['directory'])/'execution.json',{'status':'failed','returncode':1,'harness_execution':{'owned_process_group_cleaned':True}})
   if mutation=='missing_execution':s.pop('execution')
   if mutation=='order':x['steps'].reverse()
   if mutation=='duplicate':x['steps'][1]['name']=s['name']
   if mutation=='active_gate':s['status']='running'
   if mutation=='passed_summary':s['status']='failed'
  rewrite(p,mutate);repin_pipeline(r)
 with pytest.raises((ValueError,KeyError)):m.capture(r,e,l,tmp_path/'out')
 assert not (tmp_path/'out').exists()
def test_existing_output_refused(tmp_path):
 r,e,l=fixture(tmp_path);o=tmp_path/'out';o.mkdir()
 with pytest.raises(ValueError,match='already exists'):m.capture(r,e,l,o)
def test_source_hash_failure(tmp_path):
 r,e,l=fixture(tmp_path)
 with pytest.raises(ValueError,match='Changed artifact'):m.capture(r,'0'*64,l,tmp_path/'out')
def test_symlink_evidence_refused(tmp_path):
 r,e,l=fixture(tmp_path);a=r/'run/validation/attempt-0001/native-tests';(a/'evil.json').symlink_to(r/'control/execution.json')
 with pytest.raises(ValueError,match='symlink evidence'):m.capture(r,e,l,tmp_path/'out')
def test_oversize_recorded_without_promotion(tmp_path,monkeypatch):
 r,e,l=fixture(tmp_path);a=r/'run/validation/attempt-0001/native-tests';(a/'worker.log').write_bytes(b'x'*90000);monkeypatch.setattr(m,'MAX_FILE',80000)
 v=m.capture(r,e,l,tmp_path/'out');assert len(v['external_not_copied'])==1;assert (a/'worker.log').stat().st_size==90000
def test_plans_context_and_supervisor_receipts_captured(tmp_path):
 r,e,l=fixture(tmp_path)
 for relative in ('run/plan.json','run/validation/context.json','run/validation/plan.json','run/validation/attempt-0001/native-tests/supervisor/result.json'):
  save(r/relative,{'preserve':'raw'})
 v=m.capture(r,e,l,tmp_path/'out');names={x['source']['path'] for x in v['records']}
 assert all(str(r/x) in names for x in ('run/plan.json','run/validation/context.json','run/validation/plan.json','run/validation/attempt-0001/native-tests/supervisor/result.json'))
@pytest.mark.parametrize('present',[False,True])
def test_benchmark_output_presence_explicit(tmp_path,present):
 r,e,l=fixture(tmp_path)
 if present:
  save(r/'run/manifest.json',{'manifest':True});(r/'run/attempts/first').mkdir(parents=True)
 v=m.capture(r,e,l,tmp_path/'out')['benchmark_outputs'];assert v['manifest_present']==present and v['attempts_directory_present']==present;assert v['attempt_entries']==(['first'] if present else [])

def test_repinned_changed_plan_cannot_match_original_launch(tmp_path):
 r,e,l=fixture(tmp_path);c=r/'control';plan=json.loads((c/'launch-plan.json').read_text());plan['config']=save(c/'segmented-v4.json',{'changed':True});new=save(c/'launch-plan.json',plan);rewrite(c/'validation-controller.json',lambda x:x.update(plan=new))
 with pytest.raises(ValueError,match='Launch command plan'):m.capture(r,e,l,tmp_path/'out')
def test_different_observed_launch_argv_rejected(tmp_path):
 r,e,l=fixture(tmp_path);p=r/'control/validation-launch.json';rewrite(p,lambda x:x.update(observed_argv=['different']));l=hashlib.sha256(p.read_bytes()).hexdigest()
 with pytest.raises(ValueError,match='Observed launch'):m.capture(r,e,l,tmp_path/'out')
