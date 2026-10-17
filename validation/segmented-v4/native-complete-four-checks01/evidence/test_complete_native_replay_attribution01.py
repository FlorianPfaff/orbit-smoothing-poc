from pathlib import Path
import copy,hashlib,importlib.util,json
import pytest
P=Path(__file__).with_name('complete_native_replay_attribution01.py');s=importlib.util.spec_from_file_location('attr',P);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def fixture(tmp_path,defect=None):
 def write(name,obj):
  p=tmp_path/name;p.write_text(json.dumps(obj));return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
 def data(name):
  p=tmp_path/name;p.write_bytes(name.encode());return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
 native=data('candidate');baseline={'path':'/original/native','sha256':m.BASE};before={'old':'a'};after={'old':'a','new':'b'}
 base=write('base.json',{'native':baseline,'source_after':before})
 relink=write('relink.json',{'passed':defect!='relink_failed','native':baseline,'artifact':{'path':'/copied/native','sha256':'0'*64 if defect=='wrong_baseline'else m.BASE},'baseline_result':base})
 installed=write('installed.json',{'passed':True,'status':'passed','source_after':{}if defect=='installed_source'else after})
 fx={'roundtrip':{'passed':defect!='fixture_failed'},'interpolation':{'binary':data('interpolation'),'stdout':'passed'},'serializer':{'binary':data('serializer'),'stdout':'records'}};fixtures=write('fixtures.json',fx)
 pre={'status':'prepared_complete_build','baseline_relink':relink,'installation_equivalence':installed,'supplemental_fixtures':fixtures};prepin=write('pre.json',pre)
 pa={'passed':defect!='preaudit_failed','preflight_result':prepin,**{k:pre[k]for k in ('baseline_relink','installation_equivalence','supplemental_fixtures')}}
 if defect=='preaudit_binding':pa['preflight_result']=data('wrong_pre')
 papin=write('preaudit.json',pa);plan=write('plan.json',{'phase':'build','native':baseline,'inputs':{'preflight_result':prepin,'preflight_audit':papin}})
 built={'schema':'orbit-poc-native-complete-build-v1','status':'built_complete_candidate','native':native,'compiled_object_count':611,'preprocessing_count':20,'reused_object_count':0,'baseline_result':base,'baseline_relink':relink,'source_before':before,'source_after':after,'installation_equivalence':installed,'plan':plan,'supplemental_fixtures':fixtures}
 for key in ('source_delta','original_recipe_inventory','normalized_configuration','complete_compile_evidence','build_manifest','cmake_cache','candidate_dependencies'):built[key]=data(key)
 if defect=='partial_build':built['status']='failed'
 if defect=='object_count':built['compiled_object_count']=610
 if defect=='preprocessing_count':built['preprocessing_count']=19
 if defect=='reused_object':built['reused_object_count']=1
 if defect=='source_baseline':built['source_before']={}
 bp=write('build.json',built);audit={'passed':defect!='audit_failed','actual_build_result':bp,'native':native}
 if defect=='audit_binding':audit['actual_build_result']=data('wrong_build')
 if defect=='audit_native':audit['native']=data('wrong_native')
 ap=write('audit.json',audit)
 if defect=='changed_native':Path(native['path']).write_bytes(b'changed')
 if defect=='changed_fixture':Path(fx['serializer']['binary']['path']).write_bytes(b'changed')
 if defect=='changed_evidence':Path(built['complete_compile_evidence']['path']).write_bytes(b'changed')
 return {'build_result':bp,'build_audit':ap},native
def test_exact_completed_build_and_prior_fixture_attribution(tmp_path):
 inputs,native=fixture(tmp_path);built,record=m.verify(inputs,native);assert record['native']==native and record['build_result']==inputs['build_result'];assert record['fixture_execution_in_this_replay']is False
@pytest.mark.parametrize('defect',['relink_failed','wrong_baseline','installed_source','fixture_failed','preaudit_failed','preaudit_binding','partial_build','object_count','preprocessing_count','reused_object','source_baseline','audit_failed','audit_binding','audit_native','changed_native','changed_fixture','changed_evidence'])
def test_incomplete_or_misattributed_build_rejects_before_replay(tmp_path,defect):
 inputs,native=fixture(tmp_path,defect)
 with pytest.raises(ValueError):m.verify(inputs,native)
