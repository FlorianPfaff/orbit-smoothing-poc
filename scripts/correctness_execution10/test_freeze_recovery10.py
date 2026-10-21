import copy,hashlib,importlib.util,json,types
from pathlib import Path
import pytest
HERE=Path(__file__).parent
spec=importlib.util.spec_from_file_location('freeze10',HERE/'freeze_recovery10.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def save(p,v):p.write_text(json.dumps(v));return {'path':str(p),'sha256':m.sha(p)}
@pytest.fixture
def fx(tmp_path,monkeypatch):
    root=tmp_path/'current';control=root/'control';control.mkdir(parents=True)
    verifier=control/'verify_installer_correction10.py';verifier.write_text('exact reviewed verifier')
    original=control/'freeze_recovery09.py';original.write_text('exact reviewed freezer')
    save(control/'execution10-root-helper-pins.json',{'freeze_recovery09.py':m.sha(original)})
    base={'paths':{'root':str(root),'control':str(control),'source':str(root/'source')},'runtime_artifacts':{'preserved':{'path':'/prior','sha256':'a'*64}}}
    fresh={'schema':'verified','passed':True,'created_at':'fresh time','execution_before_supplementary_pins':copy.deepcopy(base),'source_files':772}
    receipt=copy.deepcopy(fresh);receipt['created_at']='prior time';rp=control/'verification.json';receiptpin=save(rp,receipt)
    execution=copy.deepcopy(base);execution['runtime_artifacts'].update(recovery10_supplementary_verifier={'path':str(verifier),'sha256':m.sha(verifier)},recovery10_supplementary_receipt=receiptpin);ep=control/'candidate09-execution.json';save(ep,execution)
    calls=[]
    def module(path,name):
        if name=='freeze10_supplementary':
            def verify(c,s,e):
                calls.append(('verify',Path(c),Path(s),copy.deepcopy(e)));return copy.deepcopy(fresh)
            return types.SimpleNamespace(verify=verify)
        assert name=='freeze10_original09'
        def freeze(**kwargs):calls.append(('freeze',kwargs));return {'original_freezer_delegated':True}
        return types.SimpleNamespace(freeze=freeze)
    monkeypatch.setattr(m,'module',module)
    return types.SimpleNamespace(root=root,control=control,base=base,fresh=fresh,receipt=receipt,rp=rp,execution=execution,ep=ep,calls=calls,verifier=verifier,original=original)

def test_fresh_supplementary_verification_precedes_exact_original_freezer(fx):
    old=Path('/cumulative08');assert m.freeze(old=old,new=fx.root)=={'original_freezer_delegated':True}
    assert fx.calls==[('verify',fx.control,fx.root/'source',fx.base),('freeze',{'old':old,'new':fx.root})]
    assert json.loads(fx.ep.read_text())==fx.execution

@pytest.mark.parametrize('role',['recovery10_supplementary_verifier','recovery10_supplementary_receipt'])
def test_changed_checked_artifact_rejected_before_delegation(fx,role):
    Path(fx.execution['runtime_artifacts'][role]['path']).write_text('changed')
    with pytest.raises(ValueError,match='identity changed'):m.freeze(new=fx.root)
    assert not fx.calls

def test_changed_current_execution_cannot_reuse_stale_verification(fx):
    fx.execution['runtime_artifacts']['preserved']['sha256']='b'*64;save(fx.ep,fx.execution)
    with pytest.raises(ValueError,match='current execution'):m.freeze(new=fx.root)
    assert not fx.calls

def test_rehashed_false_verification_receipt_is_rejected(fx):
    fx.receipt['passed']=False;fx.execution['runtime_artifacts']['recovery10_supplementary_receipt']=save(fx.rp,fx.receipt);save(fx.ep,fx.execution)
    with pytest.raises(ValueError):m.freeze(new=fx.root)
    assert not fx.calls

def test_verifier_cannot_be_relocated_even_with_matching_hash(fx):
    other=fx.control/'other.py';other.write_bytes(fx.verifier.read_bytes());fx.execution['runtime_artifacts']['recovery10_supplementary_verifier']['path']=str(other);save(fx.ep,fx.execution)
    with pytest.raises(ValueError,match='verifier path'):m.freeze(new=fx.root)
    assert not fx.calls

@pytest.mark.parametrize('key,value',[('passed',False),('source_files',771),('schema','other')])
def test_fresh_verification_disagreement_blocks_original_freezer(fx,key,value):
    fx.fresh[key]=value
    with pytest.raises(ValueError,match='disagrees'):m.freeze(new=fx.root)
    assert len(fx.calls)==1

def test_changed_original_freezer_is_rejected(fx):
    fx.original.write_text('changed')
    with pytest.raises(ValueError,match='freeze09 helper changed'):m.freeze(new=fx.root)
    assert len(fx.calls)==1
