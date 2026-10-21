"""Bind a bounded native replay to the actual audited complete build."""
from pathlib import Path
import hashlib,json
BASE='25661fd88779c009a84f7479b8fb9639aaeb9a37df3a11dc2d4adff2af94f7c2'
def check(pin):
 if set(pin)!={'path','sha256'}:raise ValueError('Exact artifact pin required')
 p=Path(pin['path'])
 if not p.is_absolute() or '..'in p.parts or hashlib.sha256(p.read_bytes()).hexdigest()!=pin['sha256']:raise ValueError('Changed complete-build artifact')
 return p
def read(pin):return json.loads(check(pin).read_text())
def require(value,message):
 if not value:raise ValueError(message)
def verify(inputs,native):
 built=read(inputs['build_result']);audit=read(inputs['build_audit'])
 require(built['schema']=='orbit-poc-native-complete-build-v1'and built['status']=='built_complete_candidate','No completed candidate build')
 require(audit['passed']is True and audit['actual_build_result']==inputs['build_result']and audit['native']==native,'Independent build acceptance differs')
 require(built['native']==native,'Native differs from complete build');check(native)
 require((built['compiled_object_count'],built['preprocessing_count'],built['reused_object_count'])==(611,20,0),'Incomplete fresh native compilation')
 base=read(built['baseline_result']);relink=read(built['baseline_relink'])
 require(base['native']['sha256']==BASE and relink['passed']is True and relink['native']==base['native']and relink['artifact']['sha256']==BASE and relink['baseline_result']==built['baseline_result'],'Actual baseline relink lineage differs')
 require(built['source_before']==base['source_after'],'Actual build source baseline differs')
 installed=read(built['installation_equivalence']);require(installed['passed']is True and installed['status']=='passed'and installed['source_after']==built['source_after'],'Pristine full installation differs')
 plan=read(built['plan']);require(plan['phase']=='build'and plan['native']==base['native'],'Complete build plan differs')
 preflight=read(plan['inputs']['preflight_result']);preaudit=read(plan['inputs']['preflight_audit'])
 require(preflight['status']=='prepared_complete_build'and preaudit['passed']is True and preaudit['preflight_result']==plan['inputs']['preflight_result'],'Source/fixture preflight acceptance differs')
 for key in ('baseline_relink','installation_equivalence','supplemental_fixtures'):
  require(built[key]==preflight[key]==preaudit[key],'Audited preflight artifact differs: '+key);check(built[key])
 fixtures=read(built['supplemental_fixtures']);require(fixtures['roundtrip']['passed']is True,'Typed supplemental roundtrip missing')
 for name in ('interpolation','serializer'):
  require(set(fixtures[name])=={'binary','stdout'},'Unexpected supplemental fixture record');check(fixtures[name]['binary'])
 for key in ('source_delta','original_recipe_inventory','normalized_configuration','complete_compile_evidence','build_manifest','cmake_cache','candidate_dependencies'):check(built[key])
 return built,{'build_result':inputs['build_result'],'build_audit':inputs['build_audit'],'native':native,'baseline_native_sha256':BASE,'preflight_result':plan['inputs']['preflight_result'],'preflight_audit':plan['inputs']['preflight_audit'],'supplemental_fixtures':built['supplemental_fixtures'],'fixture_execution_in_this_replay':False}
