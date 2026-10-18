"""Exact metadata plan derivation only; the readonly wrapper is never executed."""
import importlib.util
import json
from pathlib import Path
import pytest
D=Path(__file__).parent
def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
v=load('view_builder',D/'plan_direct_sealing_view04.py');f=load('assembly_fixtures',D/'test_assembly.py')
def setup(t):
 p,base,root,prior,seal,campaign=f.fixture(t)
 return p,base,root,prior,seal,campaign
def test_actual_plan_derives_exact_reviewed_direct_view(tmp_path):
 p,base,root,prior,seal,_=setup(tmp_path);out=seal/'derived-readonly.json';r=v.build(p['sealing_plan'],p['helpers']['readonly'],str(out))
 derived=json.loads(out.read_text());assert f.a.read(derived['parent_topology'])==f.a.read(base['parent_topology'])
 assert {k:x for k,x in derived.items() if k!='parent_topology'}=={k:x for k,x in base.items() if k!='parent_topology'}
 assert r['fit_attempts']==r['native_executions']==0 and r['fit_execution_authorized'] is False
 with pytest.raises(ValueError,match='fresh'):v.build(p['sealing_plan'],p['helpers']['readonly'],str(out))
@pytest.mark.parametrize('kind',['wrong_plan','wrong_helper','wrong_manifest','wrong_control','nonempty_lock','outside_output','prior_output','changed_sealer'])
def test_bad_view_inputs_rejected_without_output(tmp_path,kind):
 p,base,root,prior,seal,_=setup(tmp_path);out=seal/'derived-readonly.json'
 if kind=='wrong_plan':p['sealing_plan']['sha256']='0'*64
 elif kind=='wrong_helper':p['helpers']['readonly']['sha256']='0'*64
 elif kind=='nonempty_lock':Path(base['shared_lock']['path']).write_text('preserved')
 elif kind=='outside_output':out=root/'run/unwanted.json'
 elif kind=='prior_output':out.write_text('preserved')
 elif kind=='changed_sealer':Path(base['payload']['helper']['path']).write_text('changed')
 else:
  plan=f.a.read(p['sealing_plan'])
  if kind=='wrong_manifest':plan['manifest_hash']='wrong'
  else:plan['request']['control']['inode']+=1
  p['sealing_plan']=f.put(seal/'changed-sealing-plan.json',plan)
 with pytest.raises((ValueError,RuntimeError)):v.build(p['sealing_plan'],p['helpers']['readonly'],str(out))
 assert not out.exists() or kind=='prior_output' and out.read_text()=='preserved'
