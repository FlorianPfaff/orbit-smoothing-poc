"""Fabricated bounded transfer only; never contacts SSH or runs native code."""
from pathlib import Path
import importlib.util,json,hashlib,gzip
import pytest
HERE=Path(__file__).parent
s=importlib.util.spec_from_file_location('t09',HERE/'transfer_terminal09_compact.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v));return p

def pin(p):return {'path':str(p),'sha256':m.sha(p.read_bytes())}

@pytest.fixture
def fixture(tmp_path):
 root=tmp_path/'remote';c=root/'control';c.mkdir(parents=True);run=root/'validation-09';post=root/'postprocess-09-01';run.mkdir();post.mkdir()
 helper=c/'recovery_evidence_09.py';helper.write_bytes((HERE/'recovery09/recovery_evidence_09.py').read_bytes())
 inputs={str(i):{'path':str(tmp_path/('input'+str(i))),'sha256':'a'*64} for i in range(14)}
 old=write(c/'oldpins.json',{'input_artifacts':inputs})
 source={'files':{'fixture.py':'f'*64},'sha256':'b'*64};freeze=write(c/'freeze.json',{'schema':'orbit-poc-candidate09-source-freeze-v1','commit':'c'*40,'source':source})
 execution=write(c/'candidate09-execution.json',{'paths':{'root':str(root),'run':str(run)},'read_only_bindings':[]})
 pins=write(c/'candidate09-pins.json',{'input_artifacts':inputs,'candidate03_pins':pin(old),'new_source_freeze':pin(freeze),'recovery_verifier_sha256':m.sha(helper.read_bytes())})
 pipeline=write(run/'pipeline.json',{'schema':'orbit-poc-correctness-validation09-run-v1','status':'failed','finished_at':'now','final_cleanup':{'verified':True},'execution':pin(execution),'required_pins':pin(pins),'source':source,'steps':[{'name':'nuisance-replay-candidate1-point012','status':'failed','returncode':1}]})
 finish=write(post/'pipeline.json',{'schema':'orbit-poc-correctness-postprocess09-run-v1','status':'failed','finished_at':'now','validation_pipeline':pin(pipeline),'steps':[{'name':n,'cleanup_verified':True,'status':'failed' if n=='collect' else 'passed','returncode':1 if n=='collect' else 0} for n in ['audit','report','collect']]})
 point=run/'objective-log_drag_ou/point-006';write(point/'profile.execution.json',{'returncode':1});write(point/'qr.1.nuisance_line_search.json',{'accepted':False});(point/'profile.xml').write_text('<profile/>');(point/'qr.1.R.bin').write_bytes(b'EXTERNAL FACTOR')
 replay=run/'nuisance-replay-candidate1-point012';write(replay/'receipt.json',{'passed':False});write(replay/'qr.1.profile.json',{'nuisance_converged':False});(replay/'profile.log').write_text('failed')
 write(post/'report/summary.json',{'candidate_evidence_status':'failed'});(post/'report/index.html').write_text('<h1>failed</h1>')
 write(post/'publication/partial.json',{'partial':True})
 plan={'schema':'orbit-poc-terminal09-transfer-plan-v1','root':str(root),'journals':{'validation-09/pipeline.json':m.sha(pipeline.read_bytes()),'postprocess-09-01/pipeline.json':m.sha(finish.read_bytes())},'execution_sha256':m.sha(execution.read_bytes()),'pins_sha256':m.sha(pins.read_bytes()),'source_commit':'c'*40,'source_sha256':'b'*64}
 return root,plan


def test_capture_includes_both_failure_kinds_and_original14_without_spools(fixture,tmp_path):
 root,plan=fixture;v=m.capture(plan);assert len(v['original14_input_artifacts'])==14
 assert {x['kind'] for x in v['failed_profiles']}=={'objective','original_replay'}
 assert not v['collector_publication_transferred'] and len(v['collector_publication_inventory'])==1
 assert not any(row['source'].endswith('.bin') or '/publication/' in row['source'] for row in v['files'])
 failed=v['failed_profiles'][0];assert failed['external_native_artifacts'][0]['bytes']==15
 out=tmp_path/'local';result=m.restore(v,out);assert result['local_match_verified']
 assert (out/'postprocess-09-01/report/summary.json.gz').is_file()
 assert json.loads(gzip.decompress((out/'postprocess-09-01/report/summary.json.gz').read_bytes()))['candidate_evidence_status']=='failed'


def test_completed_collector_is_preserved(fixture):
 root,plan=fixture;p=root/'postprocess-09-01/pipeline.json';d=json.loads(p.read_text());manifest=write(root/'postprocess-09-01/publication/manifest.json',{'files':[]});d['steps'][2].update(returncode=0,result=pin(manifest));d['steps'][2].pop('status',None);write(p,d);plan['journals']['postprocess-09-01/pipeline.json']=m.sha(p.read_bytes())
 v=m.capture(plan);assert v['collector_publication_transferred'];assert any('/publication/manifest.json' in row['source'] for row in v['files'])

@pytest.mark.parametrize('which,field,value',[('validation-09/pipeline.json','status','running'),('validation-09/pipeline.json','final_cleanup',{'verified':False}),('postprocess-09-01/pipeline.json','status','waiting'),('postprocess-09-01/pipeline.json','finished_at',None)])
def test_nonterminal_or_unclean_journals_fail_even_when_rehashed(fixture,which,field,value):
 root,plan=fixture;p=root/which;d=json.loads(p.read_text());d[field]=value;write(p,d);plan['journals'][which]=m.sha(p.read_bytes())
 with pytest.raises(ValueError):m.capture(plan)

@pytest.mark.parametrize('key',['execution_sha256','pins_sha256','source_commit','source_sha256'])
def test_plan_identity_changes_fail(fixture,key):
 root,plan=fixture;plan[key]='0'*len(plan[key])
 with pytest.raises(ValueError):m.capture(plan)


def test_original14_cannot_be_replaced(fixture):
 root,plan=fixture;p=root/'control/oldpins.json';d=json.loads(p.read_text());d['input_artifacts']['0']['sha256']='0'*64;write(p,d)
 with pytest.raises(ValueError,match='pin changed'):m.capture(plan)


def test_symlinked_selected_receipt_fails(fixture):
 root,plan=fixture;p=root/'validation-09/nuisance-replay-candidate1-point012/profile.log';p.unlink();p.symlink_to(root/'postprocess-09-01/report/index.html')
 with pytest.raises(ValueError,match='symlinked'):m.capture(plan)


def test_bad_returned_bytes_cannot_create_local_output(fixture,tmp_path):
 root,plan=fixture;v=m.capture(plan);v['files'][0]['sha256']='0'*64
 with pytest.raises(ValueError):m.restore(v,tmp_path/'local')
 assert not (tmp_path/'local').exists()


def test_unsafe_returned_path_cannot_create_local_output(fixture,tmp_path):
 root,plan=fixture;v=m.capture(plan);v['files'][0]['relative']='../escape'
 with pytest.raises(ValueError):m.restore(v,tmp_path/'local')
 assert not (tmp_path/'local').exists()


def test_existing_local_output_is_never_replaced(fixture,tmp_path):
 root,plan=fixture;v=m.capture(plan);out=tmp_path/'existing';out.mkdir()
 with pytest.raises(ValueError,match='new'):m.restore(v,out)


def test_failed_point_compression_mapping_is_explicit(fixture,monkeypatch):
 root,plan=fixture;point=root/'validation-09/objective-log_drag_ou/point-006';(point/'profile.log').write_text('x'*200000)
 monkeypatch.setattr(m,'MAX_FILE',100000)
 v=m.capture(plan);item=next(x for x in v['failed_profiles'] if x['kind']=='objective');mapping={r['source']:r['stored'] for r in item['selected_files']}
 assert mapping['validation-09/objective-log_drag_ou/point-006/profile.log'].endswith('.gz')


def test_strict_replay_xml_and_final_search_preserved_even_when_passed(fixture):
 root,plan=fixture;p=root/'validation-09/pipeline.json';d=json.loads(p.read_text());d['steps'].append({'name':'nuisance-replay','status':'passed','returncode':0});write(p,d);plan['journals']['validation-09/pipeline.json']=m.sha(p.read_bytes())
 post=root/'postprocess-09-01/pipeline.json';f=json.loads(post.read_text());f['validation_pipeline']=pin(p);write(post,f);plan['journals']['postprocess-09-01/pipeline.json']=m.sha(post.read_bytes())
 replay=root/'validation-09/nuisance-replay';write(replay/'receipt.json',{'passed':True});(replay/'profile.xml').write_text('<exact/>');write(replay/'qr.5.nuisance_line_search.json',{'undamped_maximum_update_m':1e-10})
 v=m.capture(plan);names={r['relative'] for r in v['files']}
 assert 'validation-09/nuisance-replay/profile.xml' in names and 'validation-09/nuisance-replay/qr.5.nuisance_line_search.json' in names
 assert all(x['point']!='validation-09/nuisance-replay' for x in v['failed_profiles'])


@pytest.mark.parametrize('key',['remote_root','journals','pins_sha256','source_commit'])
def test_returned_plan_identity_rejected_before_restore(fixture,key):
 root,plan=fixture;v=m.capture(plan);v[key]='wrong'
 with pytest.raises(ValueError,match='attribution'):m.verify_return(v,plan)


def test_changed_original_source_path_is_rejected_before_output(fixture,tmp_path):
 root,plan=fixture;v=m.capture(plan);v['files'][0]['source']='/unrelated/source'
 with pytest.raises(ValueError,match='attribution'):m.restore(v,tmp_path/'local')
 assert not (tmp_path/'local').exists()


def test_terminal_postprocessor_failure_retains_unstarted_steps(fixture):
 root,plan=fixture;p=root/'postprocess-09-01/pipeline.json';d=json.loads(p.read_text());d.update(steps=[],error='Source guard failed before audit');d.pop('validation_pipeline');write(p,d);plan['journals']['postprocess-09-01/pipeline.json']=m.sha(p.read_bytes())
 v=m.capture(plan)
 assert v['postprocess_status']=='failed' and v['postprocess_validation_binding']=='not_recorded_before_failure'
 assert all(s['status']=='not_run' for s in v['postprocess_planned_steps']) and v['collector_publication_transferred'] is False


def test_failed_objective_incomplete_point_without_execution_is_preserved(fixture):
 root,plan=fixture;p=root/'validation-09/pipeline.json';d=json.loads(p.read_text());d['steps'].append({'name':'objective-log_drag_ou','status':'failed','returncode':1});write(p,d);plan['journals']['validation-09/pipeline.json']=m.sha(p.read_bytes())
 post=root/'postprocess-09-01/pipeline.json';f=json.loads(post.read_text());f['validation_pipeline']=pin(p);write(post,f);plan['journals']['postprocess-09-01/pipeline.json']=m.sha(post.read_bytes())
 point=root/'validation-09/objective-log_drag_ou/point-007';point.mkdir();(point/'profile.log').write_text('closure failed before profiling');write(point/'closure.json',{'converged':False})
 closure=point/'closure-01';write(closure/'propagate.execution.json',{'returncode':1});(closure/'propagate.log').write_text('failed');(closure/'propagate.xml').write_text('<propagate/>');write(closure/'derivatives.json',{'failed':True});(closure/'variational.dat').write_bytes(b'BULKY EXCLUDED')
 v=m.capture(plan);item=next(x for x in v['failed_profiles'] if x['point'].endswith('point-007'))
 assert item['status_receipt']['status']=='incomplete_point_missing_execution_receipt'
 assert not item['status_receipt']['execution_receipt_present']
 assert {Path(row['source']).name for row in item['selected_files']}=={'profile.log','closure.json','propagate.execution.json','propagate.log','propagate.xml','derivatives.json'}
 assert not any(row['source'].endswith('variational.dat') for row in v['files'])
 assert not any(row['source'].endswith('point-007/profile.execution.json') for row in v['files'])
