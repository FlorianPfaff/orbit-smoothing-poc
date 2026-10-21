"""Preserve existing source/config/stage guards; full build checks tested separately."""
from pathlib import Path
import ast,importlib.util,json
import pytest
C=Path(__file__).parent
s=importlib.util.spec_from_file_location('old_validation07_tests',C/'test_validation07_provenance01.py');old=importlib.util.module_from_spec(s);s.loader.exec_module(old)
s=importlib.util.spec_from_file_location('validation07_02',C/'validation07_provenance04.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

@pytest.fixture
def f(tmp_path,monkeypatch):
 monkeypatch.setattr(old,'m',m)
 # This suite tests source/config invariants. The actual full-build verifier has
 # a separate complete633-command/611-object fixture and signed-mutation suite.
 monkeypatch.setattr(m,'verify_complete_build',lambda *a:True)
 value=old.fixture(tmp_path,monkeypatch);oldseal=value['seal']
 def seal():
  oldseal();r=value['r'];r['schema']='orbit-poc-v4-native-rebuild-provenance-v3';r['status']='verified_actual_complete_rebuild'
  r['original_recipe_inventory']=r.pop('recipe_inventory');r.pop('dependency_selection',None)
  for name in ('normalized_configuration','complete_compile_evidence','baseline_relink','installation_equivalence'):
   path=tmp_path/(name+'.json');path.write_text('{}');r[name]=old.pin(path)
  value['freeze']['previous_source']=r['previous_source']
 value['seal']=seal;seal();return value

def test_distinct_historical_validation_and_build_source_pass(f):assert f['run']()

@pytest.mark.parametrize('case',['missing_source','undeclared_replacement','undeclared_addition','source_delete','source_digest','changed_gate','changed_qr','bad_old_header','supplemental_not_added','unknown_delta','installed_missing','installed_payload_mapping','installed_old','installed_duplicate','native_delta_pin','wrong_base_source','wrong_installed_digest','runtime_native','runtime_build','dense','solver','prior','weights_controls','validation_inputs','resource_limit','unknown_config','stages','wrong_source_pin','comparison_source_digest','unknown_receipt'])
def test_original_source_config_mutation_rejected(f,case):old.test_mutation_rejected(f,case)

def test_freeze_must_bind_exact_previous_source(f):
 f['freeze']['previous_source']={'path':'/wrong','sha256':'0'*64}
 with pytest.raises(RuntimeError,match='predecessor'):f['run']()

def test_controller_and_launch_change_only_pinned_verifier_name():
 original=(C/'run_segmented_validation07.py').read_text();new=(C/'run_segmented_validation07_04.py').read_text()
 assert new==original.replace('validation07_provenance01.py','validation07_provenance04.py')
 original=(C/'launch_segmented_validation07.py').read_text();new=(C/'launch_segmented_validation07_04.py').read_text()
 assert new==original.replace('run_segmented_validation07.py','run_segmented_validation07_04.py')
 old.test_controller_only_changes_provenance_and_extra_pin()
