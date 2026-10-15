import copy, hashlib, importlib.util, io, json, tarfile
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('stage09',Path(__file__).with_name('stage_recovery09.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

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
    wrapper=control/'with_correctness_namespace_04.py';wrapper.write_text('# frozen wrapper')
    ep=control/'candidate07-execution.json';ep.write_text(json.dumps({'paths':{'wrapper':str(wrapper)},'read_only_bindings':[{'source':'/immutable','target':'/canonical'}]}))
    pins={'execution_sha256':m.sha(ep),'driver_sha256':m.PREVIOUS_DRIVER_SHA,'wrapper_sha256':m.sha(wrapper)}
    (control/'candidate07-pins.json').write_text(json.dumps(pins))
    return ep,wrapper,{'execution':m.pin(ep)}

def test_prior_execution_matches_actual_and_sealed_inputs(tmp_path):
    ep,wrapper,validation=prior_controls(tmp_path)
    assert m.check_previous_controls(tmp_path,validation)==ep

def test_tampered_prior_alias_map_rejected(tmp_path):
    ep,wrapper,validation=prior_controls(tmp_path);data=json.loads(ep.read_text());data['read_only_bindings'][0]['source']='/different';ep.write_text(json.dumps(data))
    with pytest.raises(RuntimeError,match='sealed08'):m.check_previous_controls(tmp_path,validation)

def test_swapped_prior_execution_attribution_rejected(tmp_path):
    ep,wrapper,validation=prior_controls(tmp_path);validation['execution']['sha256']='wrong'
    with pytest.raises(RuntimeError,match='actual08'):m.check_previous_controls(tmp_path,validation)

def test_tampered_prior_wrapper_rejected(tmp_path):
    ep,wrapper,validation=prior_controls(tmp_path);wrapper.write_text('# changed')
    with pytest.raises(RuntimeError,match='wrapper'):m.check_previous_controls(tmp_path,validation)
