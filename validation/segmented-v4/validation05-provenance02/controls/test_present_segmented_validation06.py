from pathlib import Path
import importlib.util,json,copy,pytest
HERE=Path(__file__).parent
def module(name):
 spec=importlib.util.spec_from_file_location(name,HERE/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
m=module('present_segmented_validation06');base=module('test_present_segmented_validation03');original_fixture=base.fixture
def read(pin):return json.loads(Path(pin['path']).read_text())
def save(path,value):path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return m.artifact(path)
def fixture(tmp,failed=False):
 p=original_fixture(tmp,failed);cap=read(p['capture']);audit=read(p['independent_audit']);root=Path(p['capture']['path']).parent
 def get(key):
  rec=next(x for x in cap['records'] if x['source']['path']==audit['artifacts'][key]['path']);assert rec['encoding']=='identity'
  return json.loads((root/rec['stored']['path']).read_text())
 def update(key,value):
  rec=next(x for x in cap['records'] if x['source']['path']==audit['artifacts'][key]['path']);path=root/rec['stored']['path'];new=save(path,value)
  for part in ['source','stored']:
   for k in ['sha256','bytes']:rec[part][k]=new[k]
  audit['artifacts'][key]=dict(rec['source']);return dict(rec['source'])
 config=get('config');runplan=get('run_plan');context=get('validation_context');freeze=get('source_freeze')
 context['runtimes']['segmented']['native']['path']='/native/candidate'
 context['runtimes']['dense']={'source_sha256':audit['identity']['comparison_source_sha256'],'native':{'path':'/native/reference','sha256':'f'*64}}
 config['segmented_runtime']=copy.deepcopy(context['runtimes']['segmented']);config['dense_runtime']=copy.deepcopy(context['runtimes']['dense'])
 runplan['config']={k:v for k,v in config.items() if k not in m.REPORT_ONLY};runplan['plan_hash']=m.canonical({k:v for k,v in runplan.items() if k!='plan_hash'})
 context['plan_hash']=runplan['plan_hash'];context['validation_context_hash']=m.canonical({k:v for k,v in context.items() if k!='validation_context_hash'})
 vplan=get('validation_plan');vplan['validation_context_hash']=context['validation_context_hash'];vplan['plan_hash']=m.canonical({k:v for k,v in vplan.items() if k!='plan_hash'})
 pipeline=get('cli_pipeline');pipeline.update(plan_hash=vplan['plan_hash'],validation_context_hash=context['validation_context_hash'])
 native_inputs={f'groops/input{i}.h':'1'*64 for i in range(69)};native_inputs['groops/extension/sixStateTangent.h']='2'*64
 freeze['source']['files'].update(native_inputs);audit['identity']['source_file_count']=len(freeze['source']['files'])
 configpin=update('config',config)
 for key,value in [('run_plan',runplan),('validation_context',context),('validation_plan',vplan),('source_freeze',freeze)]:update(key,value)
 cap['pipeline']=update('cli_pipeline',pipeline)
 controller=get('controller')
 if 'cli_validation' in controller:controller['cli_validation']['pipeline']=cap['pipeline']
 cap['controller']=update('controller',controller)
 provenance={'schema':'orbit-poc-v4-native-rebuild-provenance-v1','status':'verified_actual_rebuild','fixed_stage_names':list(m.STAGES),'native_inputs':native_inputs}
 for key in ['actual_build_result','runtime_provenance','previous_config','previous_source']:provenance[key]={'path':'/original/'+key+'.json','sha256':'3'*64}
 stored=root/'control/native-rebuild-provenance.json';sp=save(stored,provenance);source={**sp,'path':str(Path(audit['artifacts']['config']['path']).with_name('native-rebuild-provenance.json'))}
 cap['records'].append({'source':source,'stored':{**sp,'path':str(stored.relative_to(root))},'encoding':'identity'});audit['artifacts']['native_rebuild_provenance']=source
 p['capture']=save(p['capture']['path'],cap)
 array=read(p['array_capture']);array['main_capture']=p['capture'];array['pipeline']=cap['pipeline'];p['array_capture']=save(p['array_capture']['path'],array);audit['array_capture']=p['array_capture']
 p['independent_audit']=save(p['independent_audit']['path'],audit)
 report=read(p['raw_report']);report['plan_hash']=runplan['plan_hash'];p['raw_report']=save(p['raw_report']['path'],report)
 interface=read(p['interface_review']);interface.update(plan_hash=runplan['plan_hash'],config=configpin,report_sha256=p['raw_report']['sha256']);p['interface_review']=save(p['interface_review']['path'],interface)
 return p
base.m=m;base.fixture=fixture

@pytest.mark.parametrize('failed',[False,True])
def test_preserved_original_full_and_failed_publication_checks(tmp_path,failed):
 base.test_preserve_exact_capture_and_eight_arrays_without_promotion(tmp_path,failed)
 summary=json.loads((tmp_path/'out/summary.json').read_text())
 assert summary['native_rebuild']['candidate_native']['sha256']=='d'*64
 assert summary['native_rebuild']['dense_reference_native']['sha256']=='f'*64
 assert summary['release_ready'] is False

@pytest.mark.parametrize('kind',['main_hash','main_bytes','pipeline','audit_pin','schema','missing','duplicate','unexpected','source_path','source_hash','stored_hash','encoding','extra_file','unsafe_path','file_changed'])
def test_preserved_original_array_guards(tmp_path,kind):base.test_array_attribution_and_membership_reject(tmp_path,kind)

def test_preserved_copy_mutation_guard(tmp_path,monkeypatch):base.test_changed_array_during_copy_preserves_failed_partial_output(tmp_path,monkeypatch)

@pytest.mark.parametrize('kind',['schema','status','stages','input_count','header_absent','input_hash','build_path','runtime_digest','dense_native','dense_source','candidate_native'])
def test_rebuild_specific_guards(tmp_path,kind):
 p=fixture(tmp_path);state=m.inspect(p);cap=read(p['capture']);audit=read(p['independent_audit']);root=Path(p['capture']['path']).parent
 def get(key):
  rec=next(x for x in cap['records'] if x['source']['path']==audit['artifacts'][key]['path']);return json.loads((root/rec['stored']['path']).read_text())
 provenance=get('native_rebuild_provenance');config=get('config');context=get('validation_context');freeze=get('source_freeze');identity=audit['identity']
 if kind=='schema':provenance['schema']='old_equivalence'
 elif kind=='status':provenance['status']='all70_unchanged'
 elif kind=='stages':provenance['fixed_stage_names'].pop()
 elif kind=='input_count':provenance['native_inputs'].pop('groops/input0.h')
 elif kind=='header_absent':provenance['native_inputs']['wrong.h']=provenance['native_inputs'].pop('groops/extension/sixStateTangent.h')
 elif kind=='input_hash':provenance['native_inputs']['groops/extension/sixStateTangent.h']='9'*64
 elif kind=='build_path':provenance['actual_build_result']['path']='relative.json'
 elif kind=='runtime_digest':provenance['runtime_provenance']['sha256']='not-a-hash'
 elif kind=='dense_native':config['dense_runtime']['native']['sha256']='8'*64
 elif kind=='dense_source':config['dense_runtime']['source_sha256']='8'*64
 elif kind=='candidate_native':config['segmented_runtime']['native']['sha256']='8'*64
 with pytest.raises(ValueError):m.verify_native_rebuild(provenance,config,context,freeze,identity)

def test_missing_new_audit_artifact_rejects_before_output(tmp_path):
 p=fixture(tmp_path);audit=read(p['independent_audit']);audit['artifacts'].pop('native_rebuild_provenance');p['independent_audit']=save(p['independent_audit']['path'],audit)
 with pytest.raises(ValueError,match='artifact keys'):m.publish(p,tmp_path/'out')
 assert not (tmp_path/'out').exists()


def relocated_fixture(tmp):
 p=fixture(tmp);audit=read(p['independent_audit']);arrays=read(p['array_capture'])
 original_capture={**p['capture'],'path':'/remote/validation-05/terminal-capture-01/manifest.json'}
 arrays['main_capture']=original_capture;p['array_capture']=save(p['array_capture']['path'],arrays)
 original_arrays={**p['array_capture'],'path':'/remote/validation-05/terminal-linearization-arrays-01/manifest.json'}
 audit['capture']=original_capture;audit['array_capture']=original_arrays;p['independent_audit']=save(p['independent_audit']['path'],audit)
 p['schema']='orbit-poc-segmented-validation-presentation-plan-v3'
 p['relocation']={'schema':'orbit-poc-validation-evidence-relocation-v1','capture':{'original':original_capture,'local':p['capture']},'array_capture':{'original':original_arrays,'local':p['array_capture']}}
 return p

def test_exact_relocated_evidence_preserves_raw_audit_bytes(tmp_path):
 p=relocated_fixture(tmp_path);before=Path(p['independent_audit']['path']).read_bytes()
 m.publish(p,tmp_path/'out')
 assert (tmp_path/'out/independent-audit.json').read_bytes()==before
 summary=read({'path':str(tmp_path/'out/summary.json')})
 assert summary['inputs']['relocation']==p['relocation']
 assert summary['release_ready'] is False

@pytest.mark.parametrize('kind',['extra','missing','schema','local_path','local_hash','original_path','original_hash','original_bytes','unsafe_original','array_original_link','unannounced'])
def test_relocation_rejects_changed_identity(tmp_path,kind):
 p=relocated_fixture(tmp_path)
 if kind=='extra':p['relocation']['extra']=1
 elif kind=='missing':p['relocation'].pop('capture')
 elif kind=='schema':p['relocation']['schema']='wrong'
 elif kind=='local_path':p['relocation']['capture']['local']={**p['capture'],'path':'/different/manifest.json'}
 elif kind=='local_hash':p['relocation']['capture']['local']={**p['capture'],'sha256':'f'*64}
 elif kind=='original_path':p['relocation']['capture']['original']={**p['relocation']['capture']['original'],'path':'/other/manifest.json'}
 elif kind=='original_hash':p['relocation']['array_capture']['original']={**p['relocation']['array_capture']['original'],'sha256':'f'*64}
 elif kind=='original_bytes':p['relocation']['array_capture']['original']={**p['relocation']['array_capture']['original'],'bytes':7}
 elif kind=='unsafe_original':
  audit=read(p['independent_audit']);audit['capture']['path']='/remote/../manifest.json';p['relocation']['capture']['original']=audit['capture'];p['independent_audit']=save(p['independent_audit']['path'],audit)
 elif kind=='array_original_link':
  arrays=read(p['array_capture']);arrays['main_capture']['path']='/wrong/source';p['array_capture']=save(p['array_capture']['path'],arrays)
  audit=read(p['independent_audit']);audit['array_capture']={**p['array_capture'],'path':'/remote/validation-05/terminal-linearization-arrays-01/manifest.json'};p['independent_audit']=save(p['independent_audit']['path'],audit)
  p['relocation']['array_capture']={'original':audit['array_capture'],'local':p['array_capture']}
 elif kind=='unannounced':p.pop('relocation');p['schema']='orbit-poc-segmented-validation-presentation-plan-v2'
 with pytest.raises(ValueError):m.publish(p,tmp_path/'out')
 assert not (tmp_path/'out').exists()
