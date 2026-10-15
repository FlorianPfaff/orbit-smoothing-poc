import copy,hashlib,importlib.util,json,shutil,xml.etree.ElementTree as ET
from pathlib import Path
import pytest
HERE=Path(__file__).parent
spec=importlib.util.spec_from_file_location('supp10',HERE/'verify_installer_correction10.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,sort_keys=True));return m.pin(p)
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()

class Fixture:
    def __init__(self,tmp,monkeypatch):
        self.mp=monkeypatch;self.previous=tmp/'previous';self.root=tmp/'current';self.control=self.root/'control';self.source=self.root/'source';self.control.mkdir(parents=True);self.source.mkdir()
        self.files={m.INSTALLER:hashlib.sha256(b'new installer').hexdigest()}
        for i in range(771):self.files['tests/test_preserved.py' if i==0 else f'data/{i}.txt']=hashlib.sha256(b'x').hexdigest()
        for name in self.files:
            p=self.source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'new installer' if name==m.INSTALLER else b'x')
        old=dict(self.files);old[m.INSTALLER]=hashlib.sha256(b'old installer').hexdigest()
        suite={'files':['tests/test_preserved.py'],'expected_count':51}
        self.before={'commit':'old09','source':{'files':old,'sha256':digest(old)},'regression_suite':suite,'original_native_test_count':106}
        self.beforepath=self.previous/'control/candidate09-source-freeze.json';bp=save(self.beforepath,self.before);monkeypatch.setattr(m,'FREEZE_SHA',bp['sha256'])
        self.execution={'paths':{'root':str(self.root),'source':str(self.source),'control':str(self.control),**{k:str(self.root/k) for k in ('native_source','build','binaries','run','temporary')}},'read_only_bindings':[{'source':'/immutable','target':'/canonical'}],'runtime_artifacts':{'same':{'path':'/pinned/runtime','sha256':'0'*64}}}
        self.oldexecution=copy.deepcopy(self.execution);self.oldexecution['paths']['root']=str(self.previous)
        self.ep=self.previous/'control/candidate09-execution.json';save(self.ep,self.oldexecution)
        self.oldpins={'source_sha256':digest(old),'new_source_freeze':bp,'execution_sha256':m.sha(self.ep)}
        self.pp=self.previous/'control/candidate09-pins.json';pp=save(self.pp,self.oldpins);monkeypatch.setattr(m,'PINS_SHA',pp['sha256'])
        self.failed={'source':self.before['source'],'execution':dict(m.pin(self.ep),bytes=self.ep.stat().st_size),'status':'failed','finished_at':'t','phase':'native-tests','final_cleanup':{'verified':True},'resume':{'status':'not_applicable','reason':'no_campaign_running'},'steps':[{'name':n,'status':'passed' if n!='native-tests' else 'failed','returncode':0 if n!='native-tests' else 1} for n in ('clone','checkout','build','native-tests')],'native':{'sha256':'beaf1afc41c5102477fdcd27b81a146aac9916b487ffb235eb4d15a37241d774'}}
        self.failedpath=self.previous/'validation-09/pipeline.json';fp=save(self.failedpath,self.failed);monkeypatch.setattr(m,'PIPELINE_SHA',fp['sha256'])
        self.post={'status':'completed','finished_at':'t','validation_pipeline':fp,'steps':[{'name':n,'cleanup_verified':True} for n in ('audit','report','collect')]}
        self.postpath=self.previous/'postprocess-09-01/pipeline.json';postp=save(self.postpath,self.post);monkeypatch.setattr(m,'POST_SHA',postp['sha256'])
        self.junit=self.previous/'validation-09/native-tests.xml';tree=ET.Element('testsuite')
        for i in range(106):
            name=['test_installer_is_idempotent_and_preserves_compatibility_output','test_piecewise_exact_legacy_batch_and_both_receiver_caches'][i] if i<2 else 'passed_'+str(i)
            case=ET.SubElement(tree,'testcase',name=name)
            if i<2:ET.SubElement(case,'failure')
        ET.ElementTree(tree).write(self.junit);monkeypatch.setattr(m,'JUNIT_SHA',m.sha(self.junit))
        monkeypatch.setattr(m,'SOURCE_SHA',digest(self.files))
        self.after={'schema':'orbit-poc-candidate09-source-freeze-v1','execution_attempt':'10','control_version':'09','immediate_previous_source_freeze':bp,'immediate_previous_source_commit':'old09','commit':'new10','source':{'files':self.files,'sha256':digest(self.files)},'regression_suite':copy.deepcopy(suite),'original_native_test_count':106}
        self.afterpath=self.control/'candidate09-source-freeze.json';ap=save(self.afterpath,self.after)
        self.review={'passed':True,'source_sha256':digest(self.files),'source_file_count':772,'generated_tree_byte_equivalence':True};self.reviewpath=self.control/'review.json';rp=save(self.reviewpath,self.review)
        self.changes={m.INSTALLER:{'before':old[m.INSTALLER],'after':self.files[m.INSTALLER]}}
        self.s={'schema':'orbit-poc-installer-correction10-v1','execution_attempt':'10','control_version':'09','previous_source_freeze':bp,'previous_pins':pp,'failed_pipeline':fp,'postprocess_pipeline':postp,'new_source_freeze':ap,'independent_review':rp,'changes':self.changes,'original_native_test_count':106,'separate_regression_count':51,'generated_tree_byte_equivalence':True,'scientific_validation_complete':False}
        self.sp=self.control/'installer-correction10.json';save(self.sp,self.s)
        self.cumulative={'supplementary_correction':m.pin(self.sp),'new_source_freeze':ap,'new_source_sha256':digest(self.files),'previous_source_freeze':bp,'changes':self.changes};self.cp=self.control/'candidate09-correction-lineage.json';save(self.cp,self.cumulative)
        manifest=HERE/'candidate09-control-validation.json';target=self.previous/'control/candidate09-control-validation.json';shutil.copyfile(manifest,target)
        self.controls=json.loads(manifest.read_text())['files']
        for name in self.controls:shutil.copyfile(HERE/'recovery09'/name,self.control/name)
    def sync(self):
        self.s['new_source_freeze']=save(self.afterpath,self.after);self.s['independent_review']=save(self.reviewpath,self.review)
        save(self.sp,self.s);self.cumulative['supplementary_correction']=m.pin(self.sp);self.cumulative['new_source_freeze']=m.pin(self.afterpath);save(self.cp,self.cumulative)
    def history(self):
        self.s['failed_pipeline']=save(self.failedpath,self.failed);self.mp.setattr(m,'PIPELINE_SHA',self.s['failed_pipeline']['sha256'])
        self.post['validation_pipeline']=self.s['failed_pipeline'];self.s['postprocess_pipeline']=save(self.postpath,self.post);self.mp.setattr(m,'POST_SHA',self.s['postprocess_pipeline']['sha256']);self.sync()
    def verify(self):return m.verify(self.control,self.source,self.execution,previous=self.previous)

@pytest.fixture
def fx(tmp_path,monkeypatch):return Fixture(tmp_path,monkeypatch)

def test_complete_actual_shape_is_preserved(fx):
    result=fx.verify();assert result['passed'] and result['source_files']==772 and len(result['unchanged_control_files'])==21
    assert result['scientific_validation_complete'] is result['correctness_resolved'] is result['accepted_covariance_authorized'] is False

@pytest.mark.parametrize('key,value',[('scientific_validation_complete',True),('generated_tree_byte_equivalence',False),('original_native_test_count',105),('separate_regression_count',52),('unknown',1)])
def test_supplement_rejects_relabelled_inventory_or_acceptance(fx,key,value):
    fx.s[key]=value;fx.sync()
    with pytest.raises(ValueError):fx.verify()

@pytest.mark.parametrize('key,value',[('status','completed'),('phase','objective-log_drag_ou'),('resume',{'status':'resumed'}),('final_cleanup',{'verified':False}),('native',{'sha256':'0'*64})])
def test_refreshed_history_pins_still_require_exact_failed09(fx,key,value):
    fx.failed[key]=value;fx.history()
    with pytest.raises(ValueError):fx.verify()

@pytest.mark.parametrize('key,value',[('status','running'),('steps',[{'name':'audit','cleanup_verified':False}])])
def test_refreshed_postprocess_pins_cannot_hide_incomplete_cleanup(fx,key,value):
    fx.post[key]=value;fx.history()
    with pytest.raises(ValueError):fx.verify()

@pytest.mark.parametrize('kind',['missing','extra','wrong_name','skip','error','bytes'])
def test_raw_junit_and_exact_failure_inventory(fx,kind):
    tree=ET.parse(fx.junit);root=tree.getroot()
    if kind=='missing':root.remove(list(root)[-1])
    elif kind=='extra':ET.SubElement(root,'testcase',name='extra')
    elif kind=='wrong_name':list(root)[0].set('name','other_failure')
    elif kind in ('skip','error'):ET.SubElement(list(root)[-1],{'skip':'skipped','error':'error'}[kind])
    else:list(root)[-1].set('extra','mutated')
    tree.write(fx.junit)
    if kind!='bytes':fx.mp.setattr(m,'JUNIT_SHA',m.sha(fx.junit))
    with pytest.raises(ValueError):fx.verify()

@pytest.mark.parametrize('key,value',[('passed',False),('source_file_count',771),('generated_tree_byte_equivalence','true')])
def test_refreshed_independent_review_cannot_be_weakened(fx,key,value):
    fx.review[key]=value;fx.sync()
    with pytest.raises(ValueError):fx.verify()

@pytest.mark.parametrize('which',['source','control','alias','runtime','output','symlink'])
def test_current_identity_or_freshness_changes_rejected(fx,which):
    if which=='source':(fx.source/'tests/test_preserved.py').write_text('changed')
    elif which=='control':(fx.control/'validate_candidate_09.py').write_text('changed')
    elif which=='alias':fx.execution['read_only_bindings'][0]['source']='/other'
    elif which=='runtime':fx.execution['runtime_artifacts']['same']['sha256']='1'*64
    elif which=='output':Path(fx.execution['paths']['build']).mkdir()
    else:Path(fx.execution['paths']['build']).symlink_to('/absent')
    with pytest.raises(ValueError):fx.verify()

def test_refreshed_new_freeze_cannot_change_existing51_suite(fx):
    fx.after['regression_suite']['expected_count']=52;fx.sync()
    with pytest.raises(ValueError):fx.verify()

def test_refreshed_cumulative_lineage_must_bind_immediate_transition(fx):
    fx.cumulative['changes']={};save(fx.cp,fx.cumulative)
    with pytest.raises(ValueError):fx.verify()
