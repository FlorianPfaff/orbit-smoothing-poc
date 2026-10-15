from pathlib import Path
import importlib.util,json,os,pytest
S=Path(__file__).with_name('prepare_segmented_fit_allowlist01.py');s=importlib.util.spec_from_file_location('allowlist',S);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v));return m.pin(p)
def file(p,text):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);return m.pin(p)
def fixture(t):
 run=t/'run';gen=run/'preparation/generation';att=file(gen/'family/generation/known_attitude.txt','known attitude');truth=file(gen/'family/evaluation/truth.npz','Cartesian truth');file(gen/'family/generation/ambiguity_truth.txt','true ambiguity')
 data=t/'prepared/data';orbit=file(data/'orbit.dat','GNSS-derived nominal orbit');obs=file(data/'receiver.dat','retained GNSS');prepared={'duration_hours':24,'native_data_inventory':m.inventory(data),'native_artifacts':[orbit,obs],'estimation_inputs':[dict(att,role='attitude')]};pp=save(t/'prepared/native-preparation.json',prepared)
 request={'stage':'synthetic','case':{'duration_hours':24},'method':'groops_pulses','parameters':{},'estimation_inputs':[dict(att,role='attitude'),dict(pp,role='force_auxiliary',metadata={'kind':'native_preparation'})]};rq=save(t/'request.json',request)
 cases=[{'case_id':str(i),'fit_request':request,'request_artifact':rq} for i in range(28)];attempts=[{'attempt_id':str(i)} for i in range(68)]
 runplan={'source':'same'};runplan['plan_hash']=m.canonical(runplan);runplan_pin=save(run/'plan.json',runplan)
 runtime={'source_root':str(t/'source'),'python':{'path':str(t/'python/bin/python')},'libraries':{'directory':str(t/'native/lib')},'source_sha256':'a'*64,'native':{'sha256':'b'*64},'segmented_solver':{'sha256':'c'*64}}
 manifest={'cases':cases,'attempts':attempts,'plan_hash':runplan['plan_hash'],'runtimes':{'dense':runtime,'segmented':runtime}};manifest['manifest_hash']=m.canonical(manifest);mp=save(run/'manifest.json',manifest)
 sp=save(run/'preparation-status.json',{'status':'prepared','manifest_hash':manifest['manifest_hash']});ap=save(t/'audit.json',{'schema':'orbit-poc-segmented-validation-terminal-independent-review-v1','consistency_passed':True,'scientific_status':'passed_scoped_checks','cleanup_verified':True,'identity':{'comparison_source_sha256':'a'*64,'native_sha256':'b'*64,'solver_sha256':'c'*64},'artifacts':{'run_plan':runplan_pin}})
 support=save(t/'support.json',{'schema':'orbit-poc-segmented-fit-support-files-v1','manifest_hash':manifest['manifest_hash'],'files':[file(t/'required-control.json','metadata')],'directories':[],'scope':'fabricated fixture'})
 source=t/'source';file(source/'src/a.py','implementation');ip=save(t/'source-inventory.json',m.inventory(source))
 file(t/'python/bin/python','python binary');file(t/'native/lib/lib.so','library');pi=save(t/'python-inventory.json',m.inventory(t/'python'));ni=save(t/'native-inventory.json',m.inventory(t/'native'))
 (run/'attempts').mkdir();(run/'.segmented.lock').touch();temp=t/'temporary';temp.mkdir()
 return {'schema':m.SCHEMA,'run_root':str(run),'manifest':mp,'preparation_status':sp,'validation_audit':ap,'support_inventory':support,'safe_trees':[{'kind':'source','inventory':ip},{'kind':'python_runtime','inventory':pi},{'kind':'native_runtime','inventory':ni}],'denied_trees':[str(gen)],'known_flight_references':[],'temporary_root':str(temp)},truth

def replace(plan,key,value):plan[key]=save(Path(plan[key]['path']),value)
def test_allowlist_retains_known_attitude_denies_truth_and_never_authorizes_fit(tmp_path):
 p,truth=fixture(tmp_path);v=m.build(p)
 assert any(x['path'].endswith('known_attitude.txt') for x in v['files'])
 assert truth['path'] in {x['path'] for x in v['denied_files']}
 assert not v['fit_execution_authorized'] and v['writable']['attempts']==str(tmp_path/'run/attempts')
 assert v['allowlist_hash']==m.canonical({k:x for k,x in v.items() if k!='allowlist_hash'})
@pytest.mark.parametrize('kind',['hardlink','copy','symlink'])
def test_truth_alias_rejected(tmp_path,kind):
 p,truth=fixture(tmp_path);alias=tmp_path/'alias.dat';original=Path(truth['path'])
 if kind=='hardlink':os.link(original,alias)
 elif kind=='symlink':alias.symlink_to(original)
 else:alias.write_bytes(original.read_bytes())
 support=json.loads(Path(p['support_inventory']['path']).read_text());support['files'].append(m.pin(alias));replace(p,'support_inventory',support)
 with pytest.raises(ValueError,match='Denied|denied'):m.build(p)
@pytest.mark.parametrize('kind',['unknown_field','no_generation_deny','audit_failed','audit_unclean','manifest_hash','preparation_failed','changed_support','extra_native_file','changed_native','nonempty_attempts','nonempty_temp','symlink_lock','source_changed','safe_overlap','support_truth','flight_reference'])
def test_fail_closed_identity_and_membership(tmp_path,kind):
 p,truth=fixture(tmp_path)
 if kind=='unknown_field':p['allow_truth']=True
 elif kind=='no_generation_deny':p['denied_trees']=[]
 elif kind in ('audit_failed','audit_unclean'):
  a=json.loads(Path(p['validation_audit']['path']).read_text());a['scientific_status' if kind=='audit_failed' else 'cleanup_verified']='failed' if kind=='audit_failed' else False;replace(p,'validation_audit',a)
 elif kind=='manifest_hash':v=json.loads(Path(p['manifest']['path']).read_text());v['manifest_hash']='0'*64;replace(p,'manifest',v)
 elif kind=='preparation_failed':v=json.loads(Path(p['preparation_status']['path']).read_text());v['status']='failed';replace(p,'preparation_status',v)
 elif kind=='changed_support':(tmp_path/'required-control.json').write_text('changed')
 elif kind=='extra_native_file':(tmp_path/'prepared/data/new.G01.dat').write_text('new transmitter')
 elif kind=='changed_native':(tmp_path/'prepared/data/orbit.dat').write_text('truth orbit')
 elif kind=='nonempty_attempts':(tmp_path/'run/attempts/prior').touch()
 elif kind=='nonempty_temp':(tmp_path/'temporary/prior').touch()
 elif kind=='symlink_lock':q=tmp_path/'run/.segmented.lock';q.unlink();q.symlink_to(tmp_path/'required-control.json')
 elif kind=='source_changed':(tmp_path/'source/src/a.py').write_text('changed')
 elif kind=='safe_overlap':p['safe_trees']=[{'kind':'source','inventory':save(tmp_path/'overlap.json',m.inventory(tmp_path/'run/preparation/generation'))}]
 elif kind=='support_truth':v=json.loads(Path(p['support_inventory']['path']).read_text());v['files'].append(truth);replace(p,'support_inventory',v)
 elif kind=='flight_reference':v=json.loads(Path(p['support_inventory']['path']).read_text());v['files'].append(file(tmp_path/'GNV1B.dat','flight reference'));replace(p,'support_inventory',v)
 with pytest.raises(ValueError):m.build(p)
def test_safe_tree_symlink_target_preserved(tmp_path):
 p,_=fixture(tmp_path);f=file(tmp_path/'lib/libactual.so','runtime library');q=tmp_path/'source/libalias.so';q.symlink_to(f['path']);p['safe_trees'][0]['inventory']=save(tmp_path/'source-inventory.json',m.inventory(tmp_path/'source'))
 v=m.build(p);r=next(x for x in v['files'] if x['path']==str(q));assert r['link_target']==f['path'];assert f['path'] in {x['path'] for x in v['files']}
def test_known_flight_reference_denied(tmp_path):
 p,_=fixture(tmp_path);reference=file(tmp_path/'GNV1B.dat','flight reference');p['known_flight_references']=[reference];v=m.build(p);assert reference['path'] in {x['path'] for x in v['denied_files']}
@pytest.mark.parametrize('key',['comparison_source_sha256','native_sha256','solver_sha256'])
def test_unrelated_validation_audit_rejected(tmp_path,key):
 p,_=fixture(tmp_path);a=json.loads(Path(p['validation_audit']['path']).read_text());a['identity'][key]='0'*64;replace(p,'validation_audit',a)
 with pytest.raises(ValueError,match='source/runtime'):m.build(p)
def test_nonempty_lock_rejected(tmp_path):
 p,_=fixture(tmp_path);(tmp_path/'run/.segmented.lock').write_text('sensitive data')
 with pytest.raises(ValueError,match='empty regular lock'):m.build(p)
def test_kernel_path_in_allowlist_rejected():
 with pytest.raises(ValueError,match='Kernel/device'):m.absolute('/proc/self/root/input')
def test_safe_tree_wrong_kind_rejected(tmp_path):
 p,_=fixture(tmp_path);p['safe_trees'][0]['kind']='python_runtime'
 with pytest.raises(ValueError,match='frozen source/runtime'):m.build(p)
