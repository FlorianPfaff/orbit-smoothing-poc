"""Actual frozen recipe schema and negative attribution tests; no native work."""
from pathlib import Path
import ast,copy,hashlib,importlib.util,json
import pytest
C=Path(__file__).parent
s=importlib.util.spec_from_file_location('recipe04',C/'validation07_provenance04.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def setup(monkeypatch):
 p=C/'native-source-delta01-recipe-inspection01.json';assert hashlib.sha256(p.read_bytes()).hexdigest()=='89fa79afc9a0b2753238cc0586a840f5121d98813f8279cb0e7362ba8f5e93a9'
 r=json.loads(p.read_bytes());base={k:copy.deepcopy(r[k])for k in ('native','original_build_manifest')};receipt={'build_base_result':copy.deepcopy(r['baseline_result'])}
 manifest={'build_command':['/pinned/cmake','-S','/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/engineering-02/groops-source/source','-B','/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/engineering-02/build']};seen=[]
 def checked(pin):seen.append(copy.deepcopy(pin))
 def read(pin,checker):
  assert pin==base['original_build_manifest'];checker(pin);return manifest
 monkeypatch.setattr(m,'read_artifact',read)
 return r,base,receipt,manifest,seen,checked

def test_actual_frozen633_record_and_historical_identities(monkeypatch):
 r,b,p,manifest,seen,checked=setup(monkeypatch)
 assert m.verify_original_recipes(r,p,b,checked)==manifest
 assert seen==[r['ninja'],r['original_build_manifest']]
 groups=m.command_inventory(r['all_commands']);assert len(groups['cpp'])==591 and len(groups['fortran'])==len(groups['preprocess'])==20 and len(r['all_commands'])==633
 assert len(r['all_dependency_blocks'])==592
 assert r['native']['sha256']==m.BUILD_BASE_NATIVE and r['baseline_result']['sha256']==m.BUILD_BASE_RESULT

@pytest.mark.parametrize('defect',['schema','extra','missing','baseline','manifest','native','compiled','propagated','relative_root','duplicate_root','same_roots','noncanonical_root'])
def test_strict_actual_recipe_attribution_rejects(monkeypatch,defect):
 r,b,p,manifest,seen,checked=setup(monkeypatch)
 if defect=='schema':r['schema']='orbit-poc-complete-native-recipes-v1'
 elif defect=='extra':r['recorded_source_root']='/invented'
 elif defect=='missing':del r['observed_at']
 elif defect=='baseline':r['baseline_result']={'path':'/wrong','sha256':'0'*64}
 elif defect=='manifest':r['original_build_manifest']={'path':'/wrong','sha256':'0'*64}
 elif defect=='native':r['native']={'path':'/wrong','sha256':'0'*64}
 elif defect=='compiled':r['native_compilations']=1
 elif defect=='propagated':r['native_propagations']=1
 elif defect=='relative_root':manifest['build_command'][2]='relative/source'
 elif defect=='duplicate_root':manifest['build_command']+=['-S','/second/source']
 elif defect=='same_roots':manifest['build_command'][4]=manifest['build_command'][2]
 elif defect=='noncanonical_root':manifest['build_command'][2]='/path/../source'
 with pytest.raises(RuntimeError):m.verify_original_recipes(r,p,b,checked)

def test_existing_scientific_and_evidence_helpers_unchanged():
 old=ast.parse((C/'validation07_provenance03.py').read_text());new=ast.parse((C/'validation07_provenance04.py').read_text())
 olds={n.name:n for n in old.body if isinstance(n,ast.FunctionDef)};news={n.name:n for n in new.body if isinstance(n,ast.FunctionDef)}
 assert set(news)==set(olds)|{'verify_original_recipes'}
 for k in olds:
  if k!='verify_complete_build':assert ast.dump(olds[k])==ast.dump(news[k]),k
