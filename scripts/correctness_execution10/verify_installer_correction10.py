"""Strict supplementary execution10 lineage; no native computation or gate changes."""
from pathlib import Path
import hashlib,json,datetime,xml.etree.ElementTree as ET
PREVIOUS=Path('/mnt/seagate10tb/orbit-v31-correctness-09-florianpfaff')
PINS_SHA='bef26212c810f13ac9a1050034c61e99d5a4d944a4b4edd768a31f7de5a7fb81'
FREEZE_SHA='149f55da9ae92ee0d6c6c529125b1268c327f6ba0904b09898ddcc0cd57a4f1b'
PIPELINE_SHA='c66d830ce7c8ca98e916706e6d30a0724b54efeb7d65f678702193fbeb30731e'
POST_SHA='726e3d744d921dfe7ababd849cc78b824c4b1e0f53e789bdb578dad6867e01e2'
SOURCE_SHA='365313010e30a086729f21c6a4d7721431395155db590ed92a2bcb37b6d15fe1'
JUNIT_SHA='ccfa291a3024393543b212f2dd2e46dbbec3960422bc7012a58a16738dbb9cb0'
INSTALLER='groops/extension/positionRemainder.py'
def require(ok,message):
    if not ok:raise ValueError(message)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def pin(path):return {'path':str(path),'sha256':sha(path)}
def read(path):return json.loads(Path(path).read_text())
def checked(item):
    require(isinstance(item,dict) and set(item)=={'path','sha256'} and Path(item['path']).is_absolute(),'Invalid supplementary artifact')
    require(sha(item['path'])==item['sha256'],'Supplementary artifact changed: '+item['path'])
    return read(item['path'])
def verify(control,source,execution,previous=PREVIOUS):
    control,source,previous=Path(control),Path(source),Path(previous)
    supplement_path=control/'installer-correction10.json';s=read(supplement_path)
    expected={'schema','execution_attempt','control_version','previous_source_freeze','previous_pins','failed_pipeline','postprocess_pipeline','new_source_freeze','independent_review','changes','original_native_test_count','separate_regression_count','generated_tree_byte_equivalence','scientific_validation_complete'}
    require(set(s)==expected and s['schema']=='orbit-poc-installer-correction10-v1' and s['execution_attempt']=='10' and s['control_version']=='09','Wrong supplementary lineage schema')
    for field,name,digest in [('previous_source_freeze','control/candidate09-source-freeze.json',FREEZE_SHA),('previous_pins','control/candidate09-pins.json',PINS_SHA),('failed_pipeline','validation-09/pipeline.json',PIPELINE_SHA),('postprocess_pipeline','postprocess-09-01/pipeline.json',POST_SHA)]:
        require(s[field]=={'path':str(previous/name),'sha256':digest},'Wrong exact previous09 identity: '+field)
    before=checked(s['previous_source_freeze']);oldpins=checked(s['previous_pins']);failed=checked(s['failed_pipeline']);post=checked(s['postprocess_pipeline'])
    require(oldpins['source_sha256']==before['source']['sha256'] and oldpins['new_source_freeze']==s['previous_source_freeze'] and failed.get('source')==before['source'],'Failed09 source attribution differs')
    oldexecution_path=previous/'control/candidate09-execution.json';oldexecution=read(oldexecution_path)
    require(sha(oldexecution_path)==oldpins['execution_sha256'] and failed.get('execution')==dict(pin(oldexecution_path),bytes=oldexecution_path.stat().st_size),'Failed09 execution attribution differs')
    require(failed.get('status')=='failed' and failed.get('finished_at') and failed.get('phase')=='native-tests' and failed.get('final_cleanup',{}).get('verified') is True,'Failed09 is not the terminal original-test failure')
    require(failed.get('resume')=={'status':'not_applicable','reason':'no_campaign_running'},'Failed09 campaign receipt differs')
    steps=failed.get('steps',[]);require([x['name'] for x in steps]==['clone','checkout','build','native-tests'] and all(x.get('status')=='passed' for x in steps[:3]) and steps[3].get('returncode')==1,'Wrong09 failed stage inventory')
    require(failed.get('native',{}).get('sha256')=='beaf1afc41c5102477fdcd27b81a146aac9916b487ffb235eb4d15a37241d774','Failed09 native identity differs')
    junit=previous/'validation-09/native-tests.xml';require(sha(junit)==JUNIT_SHA,'Original failed106 JUnit changed');cases=list(ET.parse(junit).getroot().iter('testcase'))
    failures=[x.get('name') for x in cases if x.find('failure') is not None]
    require(len(cases)==106 and len(failures)==2 and not any(x.find('error') is not None or x.find('skipped') is not None for x in cases) and set(failures)=={'test_installer_is_idempotent_and_preserves_compatibility_output','test_piecewise_exact_legacy_batch_and_both_receiver_caches'},'Original106 failed-test attribution differs')
    require(post.get('status')=='completed' and post.get('finished_at') and post.get('validation_pipeline',{}).get('sha256')==PIPELINE_SHA and [x['name'] for x in post.get('steps',[])]==['audit','report','collect'] and all(x.get('cleanup_verified') is True for x in post['steps']),'Failed09 postprocessing is not terminal and clean')
    require(s['new_source_freeze']['path']==str(control/'candidate09-source-freeze.json'),'New freeze path differs')
    after=checked(s['new_source_freeze']);review=checked(s['independent_review'])
    require(after.get('schema')=='orbit-poc-candidate09-source-freeze-v1' and after.get('execution_attempt')=='10' and after.get('control_version')=='09' and after.get('immediate_previous_source_freeze')==s['previous_source_freeze'] and after.get('immediate_previous_source_commit')==before['commit'] and after['commit']!=before['commit'],'Immediate source predecessor differs')
    files={str(p.relative_to(source)):sha(p) for p in sorted(source.rglob('*')) if p.is_file()}
    digest=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    require(after['source']=={'files':files,'sha256':digest} and digest==SOURCE_SHA and len(files)==772,'Actual source06 inventory differs')
    changes={n:{'before':before['source']['files'].get(n),'after':v} for n,v in files.items() if before['source']['files'].get(n)!=v}
    require(set(files)==set(before['source']['files']) and changes==s['changes'] and set(changes)=={INSTALLER},'Only measured installer path may change from source05')
    require(review.get('passed') is True and review.get('source_sha256')==digest and review.get('source_file_count')==772 and review.get('generated_tree_byte_equivalence') is True,'Source review does not verify generated native equivalence')
    require(after['regression_suite']==before['regression_suite'] and after['original_native_test_count']==s['original_native_test_count']==106 and s['separate_regression_count']==after['regression_suite']['expected_count']==51 and s['generated_tree_byte_equivalence'] is True and s['scientific_validation_complete'] is False,'Original test/gate inventory changed or premature acceptance')
    cumulative=read(control/'candidate09-correction-lineage.json')
    require(cumulative.get('supplementary_correction')==pin(supplement_path) and cumulative['new_source_freeze']==s['new_source_freeze'] and cumulative['new_source_sha256']==digest,'Cumulative lineage does not bind supplementary correction')
    basis=checked(cumulative['previous_source_freeze'])
    require(cumulative['changes']=={n:{'before':basis['source']['files'].get(n),'after':v} for n,v in files.items() if basis['source']['files'].get(n)!=v},'Cumulative basis changes differ')
    control_manifest=previous/'control/candidate09-control-validation.json'
    require(sha(control_manifest)=='a7381fa6d4195e3fb9d835b419563b50f6338a08e4eebbde0fc83cc875e0487f','Reviewed21-control manifest changed')
    controls=read(control_manifest)['files'];require(len(controls)==21,'Expected exact21 reviewed controls')
    for name,item in controls.items():
        path=control/name;require(path.is_file() and sha(path)==item['sha256'] and path.stat().st_size==item['bytes'],'Executed09 control byte mismatch: '+name)
    require(execution['read_only_bindings']==oldexecution['read_only_bindings'],'Scientific runtime/input aliases changed')
    require(all(execution['runtime_artifacts'].get(n)==v for n,v in oldexecution['runtime_artifacts'].items()),'Existing runtime pins changed')
    require(execution['paths']['source']==str(source) and execution['paths']['control']==str(control) and Path(execution['paths']['root'])==control.parent and control.parent!=previous,'Fresh execution paths required')
    require(all(not Path(execution['paths'][n]).exists() and not Path(execution['paths'][n]).is_symlink() for n in ('native_source','build','binaries','run','temporary')),'Production output reuse is forbidden')
    return {'schema':'orbit-poc-installer-correction10-verification-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'passed':True,'supplementary_lineage':pin(supplement_path),'failed09_junit':pin(junit),'immediate_previous_source_commit':before['commit'],'new_source_commit':after['commit'],'source_sha256':digest,'source_files':len(files),'changes':changes,'original_tests_unchanged':True,'unchanged_control_files':controls,'control_manifest':pin(control_manifest),'generated_tree_byte_equivalence':True,'execution_before_supplementary_pins':execution,'scientific_validation_complete':False,'correctness_resolved':False,'accepted_covariance_authorized':False}
