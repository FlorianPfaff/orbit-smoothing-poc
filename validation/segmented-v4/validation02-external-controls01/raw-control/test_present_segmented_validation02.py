from pathlib import Path
import importlib.util,json,hashlib,pytest,gzip
HERE=Path(__file__).parent
def module(name):
 s=importlib.util.spec_from_file_location(name,HERE/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
m=module('present_segmented_validation02');cap=module('capture_segmented_validation01');f=module('test_capture_segmented_validation01')
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v));return m.artifact(p)
def load(p):return json.loads(p.read_text())
def fixture(tmp,failed=False):
 root,e,l=f.fixture(tmp,failed);c=root/'control';r=root/'run';a=r/'validation/attempt-0001'
 config={'controls':{'unchanged':True},'original150_report':{'path':'','sha256':''}}
 cf=save(c/'segmented-v4.json',config)
 source={'sha256':'a'*64,'files':{'src/a.py':'b'*64}}
 freeze={'source':{'sha256':'c'*64,'files':{'src/a.py':'b'*64}},'comparison_source':source}
 sf=save(c/'source-freeze.json',freeze)
 cases=[{'case_id':'case'+str(i),'case':{'duration_hours':24 if i<12 else 48},'stage':'synthetic','method':'groops_pulses','family_id':'family'+str(i)} for i in range(28)]
 attempts=[]
 for i,cse in enumerate(cases):
  for profile in (['dense_corrected','segmented_1h','segmented_4h'] if i<12 else ['dense_corrected','segmented_1h']):attempts.append({'attempt_id':cse['case_id']+'--'+profile,'case_id':cse['case_id'],'profile':profile,'order':len(attempts)})
 runplan={'schema':'orbit-poc-segmented-plan-v1','config':{'controls':{'unchanged':True}},'source':source,'cases':cases,'attempts':attempts,'expected_attempts':68};runplan['plan_hash']=m.canonical(runplan);rp=save(r/'plan.json',runplan)
 runtime={'source_sha256':source['sha256'],'native':{'sha256':'d'*64},'segmented_solver':{'sha256':'e'*64}}
 context={'plan_hash':runplan['plan_hash'],'runtimes':{'segmented':runtime}};context['validation_context_hash']=m.canonical(context);ct=save(r/'validation/context.json',context)
 vp={'stages':list(m.STAGES),'validation_context_hash':context['validation_context_hash']};vp['plan_hash']=m.canonical(vp);vpp=save(r/'validation/plan.json',vp)
 pipe=load(a/'pipeline.json');pipe.update(plan_hash=vp['plan_hash'],validation_context_hash=context['validation_context_hash']);save(a/'pipeline.json',pipe);f.repin_pipeline(root)
 launchplan=load(c/'launch-plan.json');launchplan.update(config={k:cf[k] for k in ('path','sha256')},source_freeze={k:sf[k] for k in ('path','sha256')});lp=save(c/'launch-plan.json',launchplan)
 launch=load(c/'validation-launch.json');launch['argv'][-1]=lp['sha256'];l=save(c/'validation-launch.json',launch)['sha256']
 controller=load(c/'validation-controller.json');controller.update(plan=lp,source=freeze['source']);save(c/'validation-controller.json',controller)
 save(c/'launch-pins.json',{'all':'pinned'})
 audit={'schema':'orbit-poc-segmented-validation-terminal-independent-review-v1','reviewer':'fabricated fixture','consistency_passed':True,'scientific_status':'failed' if failed else 'passed_scoped_checks','cleanup_verified':True,'release_ready':False,'fit_covariance_authorized':False,'benchmark_attempts_executed':0,'identity':{'full_source_sha256':'c'*64,'comparison_source_sha256':'a'*64,'source_file_count':1,'native_sha256':'d'*64,'solver_sha256':'e'*64},'stages':[{'name':s['name'],'status':s['status'],'raw_artifacts':[s['execution']] if 'execution' in s else [],'measurements':{'count':106} if s['name']=='native-tests' else {},'independently_consistent':True} for s in pipe['steps']]}
 audit['artifacts']={k:m.artifact(p) for k,p in {'controller':c/'validation-controller.json','cli_pipeline':a/'pipeline.json','validation_context':r/'validation/context.json','validation_plan':r/'validation/plan.json','run_plan':r/'plan.json','config':c/'segmented-v4.json','source_freeze':c/'source-freeze.json','launch_plan':c/'launch-plan.json','launch_pins':c/'launch-pins.json'}.items()}
 for s in audit['stages']:
  for p in s['raw_artifacts']:p['bytes']=Path(p['path']).stat().st_size
 ap=save(tmp/'audit.json',audit)
 report={'plan_hash':runplan['plan_hash'],'manifest_hash':None,'expected_attempts':68,'terminal_attempts':0,'execution_complete':False,'release_ready':False,'attempts':[{**x,**{k:cases[int(x['case_id'][4:])][k] for k in ('case','stage','method','family_id')},'status':'not_run','strict_success':False} for x in attempts]}
 reportpin=save(tmp/'raw-report/report.json',report);h=tmp/'raw-report/index.html';h.write_text('Original pending report')
 ip=save(tmp/'interface.json',{'plan_hash':runplan['plan_hash'],'source_sha256':'a'*64,'config':cf,'report_sha256':reportpin['sha256']})
 out=tmp/'capture';cap.capture(root,e,l,out)
 plan={'schema':'orbit-poc-segmented-validation-presentation-plan-v1','capture':m.artifact(out/'manifest.json'),'independent_audit':ap,'raw_report':reportpin,'raw_html':m.artifact(h),'interface_review':ip}
 return plan

def repin(plan,key,v):plan[key]=save(Path(plan[key]['path']),v)
@pytest.mark.parametrize('failed',[False,True])
def test_actual_status_and_all_missing_attempts(tmp_path,failed):
 p=fixture(tmp_path,failed);out=tmp_path/'published';v=m.publish(p,out);s=load(out/'summary.json')
 assert s['scientific_status']==('failed' if failed else 'passed_scoped_checks') and len(s['stages'])==14 and len(s['attempts'])==68
 assert sum(x['status']=='not_run' for x in s['stages'])==(13 if failed else 0)
 assert s['release_ready'] is False and s['fit_covariance_authorized'] is False
 assert (out/'raw-benchmark/report.json').read_bytes()==Path(p['raw_report']['path']).read_bytes()
 assert all(m.artifact(out/x['path'])['sha256']==x['sha256'] for x in v['files'])
@pytest.mark.parametrize('mutation',['capture_hash','raw_hash','audit_status','cleanup','promotion','attempt_count','stage_count','stage_status','artifact_identity','source_identity','runtime_identity','core_absent','benchmark_present','unexpected_file','unsafe_path','compressed_hash','interface_report','case_substitution'])
def test_attribution_mutations_reject(tmp_path,mutation):
 p=fixture(tmp_path)
 if mutation=='capture_hash':p['capture']['sha256']='0'*64
 elif mutation=='raw_hash':Path(p['raw_report']['path']).write_text('{}')
 elif mutation.startswith('audit') or mutation in ('cleanup','promotion','stage_count','stage_status','artifact_identity','source_identity','runtime_identity'):
  d=load(Path(p['independent_audit']['path']))
  if mutation=='audit_status':d['consistency_passed']=False
  elif mutation=='cleanup':d['cleanup_verified']=False
  elif mutation=='promotion':d['release_ready']=True
  elif mutation=='stage_count':d['stages'].pop()
  elif mutation=='stage_status':d['stages'][0]['status']='failed'
  elif mutation=='artifact_identity':d['artifacts']['run_plan']['sha256']='0'*64
  elif mutation=='source_identity':d['identity']['comparison_source_sha256']='0'*64
  elif mutation=='runtime_identity':d['identity']['native_sha256']='0'*64
  repin(p,'independent_audit',d)
 elif mutation in ('attempt_count','case_substitution'):
  d=load(Path(p['raw_report']['path']))
  if mutation=='attempt_count':d['attempts'].pop()
  else:d['attempts'][0]['case']={'different':True}
  repin(p,'raw_report',d);i=load(Path(p['interface_review']['path']));i['report_sha256']=p['raw_report']['sha256'];repin(p,'interface_review',i)
 elif mutation=='interface_report':
  d=load(Path(p['interface_review']['path']));d['report_sha256']='0'*64;repin(p,'interface_review',d)
 else:
  d=load(Path(p['capture']['path']));base=Path(p['capture']['path']).parent
  if mutation=='core_absent':rec=d['records'].pop();(base/rec['stored']['path']).unlink()
  elif mutation=='benchmark_present':d['benchmark_outputs']['attempts_directory_present']=True
  elif mutation=='unexpected_file':(base/'extra.json').write_text('{}')
  elif mutation=='unsafe_path':d['records'][0]['stored']['path']='../escape'
  elif mutation=='compressed_hash':d['records'][0]['encoding']='gzip'
  repin(p,'capture',d)
 with pytest.raises((ValueError,KeyError,OSError)):m.publish(p,tmp_path/'published')
 assert not (tmp_path/'published').exists()
def test_existing_output_rejects(tmp_path):
 p=fixture(tmp_path);o=tmp_path/'pub';o.mkdir()
 with pytest.raises(ValueError):m.publish(p,o)
def test_failed_raw_xml_artifact_can_be_preserved(tmp_path):
 p=fixture(tmp_path,True);m.inspect(p)
def test_actual_junit_xml_in_audit_raw_artifacts(tmp_path):
 p=fixture(tmp_path);base=Path(p['capture']['path']).parent;raw=b'<testsuite tests="106" failures="0"/>'
 target=base/'run/validation/attempt-0001/native-tests/junit.xml';target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
 source={'path':'/actual/run/validation/attempt-0001/native-tests/junit.xml','sha256':m.sha(raw),'bytes':len(raw)}
 capture=load(Path(p['capture']['path']));capture['records'].append({'source':source,'stored':{**m.artifact(target),'path':str(target.relative_to(base))},'encoding':'identity'});repin(p,'capture',capture)
 audit=load(Path(p['independent_audit']['path']));audit['stages'][0]['raw_artifacts'].append(source);repin(p,'independent_audit',audit)
 assert m.inspect(p)['stages'][0]['raw_artifacts'][-1]==source

def test_actual_gzip_capture_member_is_preserved(tmp_path):
 p=fixture(tmp_path);capture=load(Path(p['capture']['path']));base=Path(p['capture']['path']).parent;rec=capture['records'][0];old=base/rec['stored']['path'];new=old.with_name(old.name+'.gz');new.write_bytes(gzip.compress(old.read_bytes(),mtime=0));old.unlink();rec['encoding']='gzip';rec['stored']={**m.artifact(new),'path':str(new.relative_to(base))};repin(p,'capture',capture)
 m.publish(p,tmp_path/'published');assert (tmp_path/'published/raw-capture'/rec['stored']['path']).read_bytes()==new.read_bytes()
