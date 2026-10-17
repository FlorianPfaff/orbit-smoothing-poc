import copy, hashlib, importlib.util, io, json, tarfile
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('stage09',Path(__file__).with_name('stage_recovery10.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def archive(tmp_path, entries):
    p=tmp_path/'source.tar'
    with tarfile.open(p,'w') as stream:
        for name,raw,kind in entries:
            entry=tarfile.TarInfo(name);entry.type=kind
            if kind==tarfile.REGTYPE:entry.size=len(raw);stream.addfile(entry,io.BytesIO(raw))
            else:entry.linkname='outside';stream.addfile(entry)
    return p

def inventory(files):
    values={name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()}
    return {'files':values,'sha256':m.digest(values)}

@pytest.mark.parametrize('name',['../a','/absolute','a/../b','a//b','./b','.git/config','a\\b',''])
def test_unsafe_names_fail(name):
    with pytest.raises(RuntimeError):m.safe_name(name)

def test_exact_source_is_read_only(tmp_path):
    entries={'a.txt':b'one','nested/b.txt':b'two'}
    p=archive(tmp_path,[(name,raw,tarfile.REGTYPE) for name,raw in entries.items()]);target=tmp_path/'out'
    m.unpack_source(p,target,inventory(entries))
    assert {str(x.relative_to(target)):x.read_bytes() for x in target.rglob('*') if x.is_file()}==entries
    assert all(x.stat().st_mode&0o222==0 for x in target.rglob('*') if x.is_file())

@pytest.mark.parametrize('entries,files',[
    ([('a',b'x',tarfile.REGTYPE),('a',b'x',tarfile.REGTYPE)],{'a':b'x'}),
    ([('a',b'x',tarfile.REGTYPE)],{'a':b'x','missing':b'y'}),
    ([('a',b'x',tarfile.REGTYPE),('extra',b'y',tarfile.REGTYPE)],{'a':b'x'}),
    ([('a',b'wrong',tarfile.REGTYPE)],{'a':b'x'}),
    ([('a',b'',tarfile.SYMTYPE)],{'a':b'x'}),
    ([('a',b'',tarfile.LNKTYPE)],{'a':b'x'}),
    ([('a',b'',tarfile.DIRTYPE)],{'a':b'x'}),
])
def test_bad_archive_rejected_before_source_creation(tmp_path,entries,files):
    p=archive(tmp_path,entries);target=tmp_path/'out'
    with pytest.raises(RuntimeError):m.unpack_source(p,target,inventory(files))
    assert not target.exists()

def test_source_inventory_digest_checked_before_writing(tmp_path):
    p=archive(tmp_path,[('a',b'x',tarfile.REGTYPE)]);frozen=inventory({'a':b'x'});frozen['sha256']='0'*64
    with pytest.raises(RuntimeError):m.unpack_source(p,tmp_path/'out',frozen)
    assert not (tmp_path/'out').exists()

@pytest.mark.parametrize('symlink',[False,True])
def test_existing_source_never_reused(tmp_path,symlink):
    p=archive(tmp_path,[('a',b'x',tarfile.REGTYPE)]);target=tmp_path/'out'
    if symlink:target.symlink_to(tmp_path/'missing')
    else:target.mkdir();(target/'retained').write_bytes(b'old')
    with pytest.raises(RuntimeError):m.unpack_source(p,target,inventory({'a':b'x'}))
    if not symlink:assert (target/'retained').read_bytes()==b'old'

def good_terminal():
    return ({'status':'failed','finished_at':'time','final_cleanup':{'verified':True}}, {'status':'failed','finished_at':'time','steps':[{'cleanup_verified':True}],'validation_pipeline':{'sha256':m.PREVIOUS_PIPELINE_SHA}})

def test_failed_prior_result_is_accepted_as_history_only():m.check_terminal(*good_terminal())

@pytest.mark.parametrize('side,key,value',[(0,'status','running'),(0,'finished_at',None),(0,'final_cleanup',{'verified':False}),(1,'status','running'),(1,'finished_at',None),(1,'steps',[]),(1,'steps',[{'cleanup_verified':False}]),(1,'validation_pipeline',{'sha256':'wrong'})])
def test_incomplete_history_never_admitted(side,key,value):
    records=good_terminal();records[side][key]=value
    with pytest.raises(RuntimeError):m.check_terminal(*records)

def test_execution_separates_outputs_preserves_runtime():
    old=Path('/old/08');new=Path('/new/09')
    paths={key:str(old/key) for key in ('source','control','wrapper',*m.MUTABLE)};paths['root']=str(old);paths['upstream_repository']=str(old/'upstream.git');paths['python']='/immutable/python'
    value={'paths':paths,'runtime_artifacts':{'python':{'path':'/immutable/python','sha256':'1'*64}},'read_only_bindings':[{'source':'/immutable','target':'/canonical'}],'reserved_cpu_note':'old'};before=copy.deepcopy(value)
    result=m.next_execution(value,old,new)
    assert value==before
    assert result['runtime_artifacts']==before['runtime_artifacts'] and result['read_only_bindings']==before['read_only_bindings']
    assert result['paths']['run']==str(new/'validation-09')
    assert result['paths']['wrapper']==str(new/'control/with_correctness_namespace_09.py')
    assert result['paths']['upstream_repository']==str(new/'upstream.git')
    result['runtime_artifacts']['python']['sha256']='changed';assert value==before

def test_execution_rejects_unowned_paths():
    paths={key:'/old/08/'+key for key in ('root','source','control','wrapper',*m.MUTABLE)};paths['source']='/other/source'
    with pytest.raises(RuntimeError):m.next_execution({'paths':paths},Path('/old/08'),Path('/new/09'))


def prior_controls(tmp_path):
    control=tmp_path/'control';control.mkdir()
    wrapper=control/'with_correctness_namespace_09.py';wrapper.write_text('# frozen wrapper')
    ep=control/'candidate09-execution.json';ep.write_text(json.dumps({'paths':{'wrapper':str(wrapper)},'read_only_bindings':[{'source':'/immutable','target':'/canonical'}]}))
    pins={'execution_sha256':m.sha(ep),'driver_sha256':m.PREVIOUS_DRIVER_SHA,'wrapper_sha256':m.sha(wrapper)}
    (control/'candidate09-pins.json').write_text(json.dumps(pins))
    return ep,wrapper,{'execution':dict(m.pin(ep),bytes=ep.stat().st_size)}

def test_prior_execution_matches_actual_and_sealed_inputs(tmp_path):
    ep,wrapper,validation=prior_controls(tmp_path)
    assert m.check_previous_controls(tmp_path,validation)==ep

def test_tampered_prior_alias_map_rejected(tmp_path):
    ep,wrapper,validation=prior_controls(tmp_path);data=json.loads(ep.read_text());data['read_only_bindings'][0]['source']='/different';ep.write_text(json.dumps(data))
    with pytest.raises(RuntimeError,match='sealed09'):m.check_previous_controls(tmp_path,validation)

def test_swapped_prior_execution_attribution_rejected(tmp_path):
    ep,wrapper,validation=prior_controls(tmp_path);validation['execution']['sha256']='wrong'
    with pytest.raises(RuntimeError,match='actual09'):m.check_previous_controls(tmp_path,validation)

def test_tampered_prior_wrapper_rejected(tmp_path):
    ep,wrapper,validation=prior_controls(tmp_path);wrapper.write_text('# changed')
    with pytest.raises(RuntimeError,match='wrapper'):m.check_previous_controls(tmp_path,validation)


@pytest.mark.parametrize('field,value',[('bytes',0),('path','/wrong/path'),('sha256','0'*64),('unknown',True)])
def test_exact_actual_artifact_metadata_required(tmp_path,field,value):
    _,_,validation=prior_controls(tmp_path);validation['execution'][field]=value
    with pytest.raises(RuntimeError,match='actual09'):m.check_previous_controls(tmp_path,validation)


def test_missing_byte_count_rejected(tmp_path):
    _,_,validation=prior_controls(tmp_path);del validation['execution']['bytes']
    with pytest.raises(RuntimeError,match='actual09'):m.check_previous_controls(tmp_path,validation)


@pytest.mark.parametrize('name',['recovery10-staging.json','recovery10-staging-failed.json'])
@pytest.mark.parametrize('symlink',[False,True])
def test_receipt_reuse_rejected_before_any_input_read(tmp_path,monkeypatch,name,symlink):
    old=tmp_path/'old';new=tmp_path/'new';control=new/'control';control.mkdir(parents=True)
    p=control/name
    if symlink:p.symlink_to(tmp_path/'absent')
    else:p.write_text('retained')
    monkeypatch.setattr(m,'sha',lambda p:pytest.fail('Read input before freshness rejection'))
    with pytest.raises(RuntimeError,match='retry'):m.stage(tmp_path/'no.tar','0'*64,'0'*64,'0'*64,old,new)
    assert p.is_symlink() if symlink else p.read_text()=='retained'


def stage_fixture(tmp_path,monkeypatch,behavior='pass'):
    old=tmp_path/'old';new=tmp_path/'new';oc=old/'control';nc=new/'control';oc.mkdir(parents=True);nc.mkdir(parents=True)
    (old/'validation-09').mkdir();(old/'postprocess-09-01').mkdir()
    wrapper=oc/'with_correctness_namespace_09.py';wrapper.write_text('# wrapper')
    (nc/wrapper.name).write_bytes(wrapper.read_bytes())
    paths={key:str(old/key) for key in ('source','control','wrapper',*m.MUTABLE)};paths.update(root=str(old),control=str(oc),wrapper=str(wrapper),upstream_repository=str(old/'upstream.git'),python='/readonly/python')
    prior={'paths':paths,'runtime_artifacts':{},'read_only_bindings':[],'reserved_cpu_note':'old'}
    ep=oc/'candidate09-execution.json';ep.write_text(json.dumps(prior))
    driver=oc/'validate_candidate_09.py'
    driver.write_text('''import json,hashlib\nfrom pathlib import Path\ndef load_execution(p):return json.loads(Path(p).read_text())\ndef admission(p):return {'status':'admitted'}\ndef source_receipt(p):\n f={str(x.relative_to(p)):hashlib.sha256(x.read_bytes()).hexdigest() for x in p.rglob('*') if x.is_file()}\n return {'files':f,'sha256':hashlib.sha256(json.dumps(f,sort_keys=True,separators=(',',':')).encode()).hexdigest()}\ndef resolved_host_path(p,e):return Path(p)\n''')
    monkeypatch.setattr(m,'PREVIOUS_DRIVER_SHA',m.sha(driver))
    pins={'execution_sha256':m.sha(ep),'driver_sha256':m.sha(driver),'wrapper_sha256':m.sha(wrapper)}
    pp=oc/'candidate09-pins.json';pp.write_text(json.dumps(pins));monkeypatch.setattr(m,'PREVIOUS_PINS_SHA',m.sha(pp))
    v,p=good_terminal();v['execution']=dict(m.pin(ep),bytes=ep.stat().st_size)
    vp=old/'validation-09/pipeline.json';vp.write_text(json.dumps(v));monkeypatch.setattr(m,'PREVIOUS_PIPELINE_SHA',m.sha(vp));p['validation_pipeline']['sha256']=m.sha(vp)
    post=old/'postprocess-09-01/pipeline.json';post.write_text(json.dumps(p));monkeypatch.setattr(m,'PREVIOUS_POST_SHA',m.sha(post))
    inv=inventory({'a':b'source'});tar=archive(tmp_path,[('a',b'source',tarfile.REGTYPE)])
    freeze=nc/'candidate09-source-freeze.json';freeze.write_text(json.dumps({'schema':'orbit-poc-candidate09-source-freeze-v1','source':inv}))
    for name in ['execution10-root-helper-pins.json','freeze_recovery10.py','freeze_recovery09.py','smoke_recovery09.py']:(nc/name).write_text('# pinned helper')
    verifier=nc/'verify_installer_correction10.py'
    body="assert (source/'a').read_bytes()==b'source';assert execution['paths']['root']==str(control.parent);return {'passed':True,'source_sha256':'fixture','native_launched':False}"
    if behavior=='failure':body="raise RuntimeError('supplementary rejected')"
    if behavior=='interruption':body="raise KeyboardInterrupt('supplementary interrupted')"
    verifier.write_text('def verify(control,source,execution):\n '+body+'\n')
    commands=[]
    def run(argv,**kw):
        commands.append(argv);assert argv[:4]==['git','clone','--bare','--no-hardlinks'];Path(argv[-1]).mkdir()
    def output(argv,**kw):
        commands.append(argv)
        if argv[3]=='rev-parse':return m.TREE+'\n'
        assert argv[3:]==['archive','--format=tar',m.COMMIT];return b'archive'
    monkeypatch.setattr(m.subprocess,'run',run);monkeypatch.setattr(m.subprocess,'check_output',output)
    monkeypatch.setattr(m,'UPSTREAM_ARCHIVE_SHA',hashlib.sha256(b'archive').hexdigest())
    return old,new,tar,m.sha(tar),m.sha(freeze),m.sha(verifier),commands


def test_complete_staging_preserves_aliases_and_pins_supplement(tmp_path,monkeypatch):
    old,new,tar,th,fh,vh,commands=stage_fixture(tmp_path,monkeypatch)
    r=m.stage(tar,th,fh,vh,old,new);assert r['status']=='passed' and r['native_launched'] is False
    c=new/'control';e=json.loads((c/'candidate09-execution.json').read_text())
    assert e['read_only_bindings']==[]
    assert e['runtime_artifacts']['recovery10_supplementary_verifier']==m.pin(c/'verify_installer_correction10.py')
    assert e['runtime_artifacts']['recovery10_supplementary_receipt']==m.pin(c/'execution10-supplementary-verification.json')
    assert e['runtime_artifacts']['recovery10_previous_validation']==m.pin(old/'validation-09/pipeline.json')
    assert (new/'source/a').read_bytes()==b'source'
    assert all(not Path(e['paths'][k]).exists() for k in m.MUTABLE)
    assert len(commands)==3 and not (c/'recovery10-staging-failed.json').exists()

@pytest.mark.parametrize('behavior',['failure','interruption'])
def test_supplement_failure_preserved_without_execution_or_success(tmp_path,monkeypatch,behavior):
    old,new,tar,th,fh,vh,_=stage_fixture(tmp_path,monkeypatch,behavior)
    with pytest.raises((RuntimeError,KeyboardInterrupt)):m.stage(tar,th,fh,vh,old,new)
    c=new/'control';r=json.loads((c/'recovery10-staging-failed.json').read_text());assert r['status']=='failed' and 'supplementary' in r['error']
    assert not (c/'candidate09-execution.json').exists() and not (c/'recovery10-staging.json').exists()


def test_wrong_supplement_hash_never_imported(tmp_path,monkeypatch):
    old,new,tar,th,fh,vh,_=stage_fixture(tmp_path,monkeypatch)
    with pytest.raises(RuntimeError,match='verifier changed'):m.stage(tar,th,fh,'0'*64,old,new)
    assert not (new/'control/execution10-supplementary-verification.json').exists()


def test_original_nonmetadata_helpers_unchanged():
    import ast
    c=Path(__file__).parent
    def functions(p):return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(p.read_text()).body if isinstance(n,ast.FunctionDef)}
    old=functions(c/'stage_recovery09_02.py');new=functions(c/'stage_recovery10.py')
    for name in ['sha','pin','require','save','digest','safe_name','unpack_source','check_terminal']:assert old[name]==new[name]


def test_postprocessor_launcher_is_exact_two_identity_substitutions():
    c=Path(__file__).parent;old=(c/'launch_postprocess09.py').read_text();new=(c/'launch_postprocess10.py').read_text()
    expected=old.replace("new=Path('/mnt/seagate10tb/orbit-v31-correctness-09-florianpfaff')","new=Path('/mnt/seagate10tb/orbit-v31-correctness-10-florianpfaff')").replace('orbit-poc-recovery09-postprocess-launch-v1','orbit-poc-recovery10-postprocess-launch-v1')
    assert new==expected
