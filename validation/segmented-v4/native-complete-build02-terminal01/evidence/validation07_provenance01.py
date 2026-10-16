"""Unlaunched validation07 provenance checks; no scientific acceptance changes.

The previous validation, build base, and new executable are distinct identities.
This module inspects pinned documents only; it never compiles or launches work.
"""
from pathlib import Path
import copy,hashlib,json,re

PREVIOUS_FREEZE='87b220cf9a66737e72ed2037c3a80895eb445bf3058918fad32d38e79df8078c'
PREVIOUS_CONFIG='d7d66e175353213889ce32d8606a572d219bc2138ad58f1041558e49b014486b'
PREVIOUS_NATIVE='eb41fabb2117fd81c9d018793ad8e067f6ae65e86d71dae8e6ef8fcca4771133'
PREVIOUS_HEADER='1590e13ff3f69cb6841af8341737b8d52c4d618592070b61b4ae6516f2ea4c28'
BUILD_BASE_RESULT='92dcf754ad42ad22c92b0e0413e86af83fd7d4f9700b69c08c86254022e69224'
BUILD_BASE_NATIVE='25661fd88779c009a84f7479b8fb9639aaeb9a37df3a11dc2d4adff2af94f7c2'
ORIGINAL_BUILD_NATIVE='a66949456ad67b816d09f2f14df792c68c2685f5304139499e4d90092fd75b22'
DENSE_NATIVE='f36bb698ea715a7fc3201c71f823315d493d943ecfb8e7ecad8fbb348ba61625'
PIN_KEYS={'previous_source','previous_config','repository_source_delta','actual_build_result','build_base_result','native_source_delta','recipe_inventory','dependency_selection','runtime_provenance'}
RECEIPT_KEYS=PIN_KEYS|{'schema','status','native_inputs','installed_source_mapping','candidate_native_source_root','fixed_stage_names'}
PROTECTED=(
 'src/orbit_poc/segmented/validation.py','src/orbit_poc/segmented/validation_reference.py','src/orbit_poc/segmented/report.py',
 'tests/test_numerics_native_qr.py','tests/test_numerics_original_objective.py','tests/test_numerics_mean_residual.py',
 'tests/test_numerics_derivatives.py','tests/test_numerics_geometry_precision.py','tests/test_numerics_synthetic_force_arithmetic.py',
 'tests/test_numerics_query_precision.py','tests/test_numerics_reference_precision.py','tests/test_numerics_precise_residual.py',
 'tests/test_numerics_precise_objective.py','tests/test_numerics_light_time_precision.py',
 'scripts/validate_numerics_synthetic_refinement.py','scripts/validate_numerics_flight_refinement.py',
 'scripts/validate_numerics_objective.py','scripts/validate_numerics_nuisance.py','scripts/validate_segmented_linearization.py',
 'groops/extension/segmentedQrMain.cpp','groops/extension/segmentedQr.h')

def require(value,why):
 if not value:raise RuntimeError(why)
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def hash_value(value):
 require(isinstance(value,str)and re.fullmatch('[0-9a-f]{64}',value)is not None,'Invalid SHA256')
 return value
def relative(value):
 require(isinstance(value,str)and value and not Path(value).is_absolute()and str(Path(value))==value and '..'not in Path(value).parts,'Invalid relative source path')
 return value
def source_map(value):
 require(isinstance(value,dict)and value,'Missing source inventory')
 for name,h in value.items():relative(name);hash_value(h)
 return value
def read(pin,checked):checked(pin);return json.loads(Path(pin['path']).read_text())

def verify_repository_delta(delta,previous_pin,before,after):
 require(set(delta)=={'schema','previous_source','before_sha256','after_sha256','replacements','additions','supplemental_tests'},'Unknown repository delta options')
 require(delta['schema']=='orbit-poc-validation-repository-delta-v1'and delta['previous_source']==previous_pin,'Repository delta predecessor differs')
 source_map(before);source_map(after)
 require(delta['before_sha256']==digest(before)and delta['after_sha256']==digest(after),'Repository delta inventory digest differs')
 require(set(before)<=set(after),'Source deletion is unsupported')
 replacements=delta['replacements'];additions=delta['additions']
 require(isinstance(replacements,dict)and isinstance(additions,dict),'Missing explicit add/replace maps')
 actual={k for k in before if before[k]!=after[k]}
 require(set(replacements)==actual and set(additions)==set(after)-set(before),'Undeclared or redundant repository source change')
 for name,row in replacements.items():
  require(set(row)=={'before','after'}and row=={'before':before[name],'after':after[name]},'Repository replacement bytes differ')
 require(additions=={k:after[k]for k in additions},'Repository added bytes differ')
 supplementary=delta['supplemental_tests']
 require(isinstance(supplementary,dict)and supplementary and all(k.startswith('tests/')and k in additions and additions[k]==h for k,h in supplementary.items()),'Supplemental tests must be exact added files')
 for name in PROTECTED:require(name in before and after[name]==before[name],'Protected original gate or QR source changed: '+name)
 return True

def verify_installed_delta(delta,baseline_pin,before,after,repo,mapping,checked):
 require(set(delta)=={'schema','baseline_result','base_source_sha256','changes'}and delta['schema']=='orbit-poc-native-source-delta-v1','Unknown installed source delta')
 source_map(before);source_map(after)
 require(delta['baseline_result']==baseline_pin and delta['base_source_sha256']==digest(before),'Installed delta baseline differs')
 require(isinstance(mapping,dict),'Missing installed-to-repository mapping')
 expected=dict(before);changed=set()
 for row in delta['changes']:
  require(set(row)=={'relative','action','old_sha256','new_file'},'Unknown installed source change')
  name=relative(row['relative']);require(name not in changed,'Repeated installed source change');changed.add(name);checked(row['new_file'])
  if row['action']=='replace':require(name in before and row['old_sha256']==before[name]and row['new_file']['sha256']!=before[name],'Wrong installed replacement')
  elif row['action']=='add':require(name not in before and row['old_sha256']is None,'Wrong installed addition')
  else:raise RuntimeError('Installed deletion or unknown source action')
  require(name in mapping and relative(mapping[name])in repo and repo[mapping[name]]==row['new_file']['sha256'],'Installed payload does not match frozen repository')
  expected[name]=row['new_file']['sha256']
 require(changed and set(mapping)==changed and expected==after,'Installed source membership/delta differs')
 return changed

def verify_dependencies(selection,recipes,build,changed,new_root):
 """Recompute old/new source dependency intersections; do not assume 27 TUs."""
 old=selection['old'];new=selection['new'];targets=selection['rebuild_targets'];reasons=selection['selection_reasons']
 objects=[x for x in build['link_command']if x.endswith('.o')]
 require(len(objects)==len(set(objects))and objects,'Invalid link object membership')
 require(set(old)==set(new)==set(reasons)==set(build['compile_commands'])==set(objects),'Incomplete linked-object dependency/command inventory')
 root=Path(recipes['recorded_source_root']);candidate=Path(new_root)
 require(root.is_absolute()and candidate.is_absolute()and root!=candidate and '..'not in root.parts and '..'not in candidate.parts,'Invalid native source roots')
 selected=set()
 for target in objects:
  relative(target);row=old[target];source=Path(row['source'])
  require(source.is_relative_to(root),'Original source outside recorded root')
  olddeps=row['dependencies'];newdeps=new[target]
  require(isinstance(olddeps,list)and isinstance(newdeps,list)and olddeps and newdeps,'Missing dependency list')
  require(len(olddeps)==len(set(olddeps))and len(newdeps)==len(set(newdeps))and all(Path(v).is_absolute()for v in olddeps+newdeps),'Invalid dependency member')
  rel=str(source.relative_to(root));require(str(source)in olddeps and str(candidate/rel)in newdeps,'Translation unit absent from dependencies')
  a={str(Path(v).relative_to(root))for v in olddeps if Path(v).is_relative_to(root)}
  b={str(Path(v).relative_to(candidate))for v in newdeps if Path(v).is_relative_to(candidate)}
  hits=sorted(changed&(a|b|{rel}));require(reasons[target]==hits,'Dependency selection reason differs')
  if hits:selected.add(target)
 require(selected and len(targets)==len(set(targets))and set(targets)==selected,'Dependency rebuild target set differs')
 require(build['rebuilt_objects']==sorted(selected)and len(build['changed_objects'])==len(set(build['changed_objects']))and set(build['changed_objects'])<=selected,'Actual rebuilt/changed objects differ')
 require(build['reused_object_count']==len(objects)-len(selected),'Reused object count differs')
 require(isinstance(selection['external_dependency_identities'],dict)and selection['external_dependency_identities'],'External compile dependency inventory missing')
 labels=[x['label']for x in build['stages']]
 require(len(labels)==len(set(labels))and labels[0]=='baseline-link'and labels[-2:]==['candidate-link','native-help'],'Actual build stage sequence differs')
 compile_stages=[x for x in build['stages']if x['label'].startswith('compile-')]
 require(len(compile_stages)==len(selected),'Actual compilation stage count differs')
 for stage,target in zip(compile_stages,sorted(selected)):require(stage['argv']==build['compile_commands'][target],'Actual compile command attribution differs')
 return True

def verify_native_provenance(receipt,config,freeze,checked,stages):
 require(set(receipt)==RECEIPT_KEYS and receipt['schema']=='orbit-poc-v4-native-rebuild-provenance-v2'and receipt['status']=='verified_actual_source_delta_rebuild','Unknown validation07 native provenance')
 documents={k:read(receipt[k],checked)for k in PIN_KEYS}
 require(receipt['previous_source']['sha256']==PREVIOUS_FREEZE and receipt['previous_config']['sha256']==PREVIOUS_CONFIG and receipt['build_base_result']['sha256']==BUILD_BASE_RESULT,'Historical validation/build source identity differs')
 old=documents['previous_source'];previous=documents['previous_config'];before=old['source']['files'];after=freeze['source']['files']
 require(len(before)==384 and before['groops/extension/sixStateTangent.h']==PREVIOUS_HEADER,'Original384 source identity differs')
 require(previous['segmented_runtime']['native']['sha256']==PREVIOUS_NATIVE and previous['dense_runtime']['native']['sha256']==DENSE_NATIVE,'Previous validation executable identity differs')
 verify_repository_delta(documents['repository_source_delta'],receipt['previous_source'],before,after)
 require(freeze['source']['sha256']==digest(after),'Current source freeze digest differs')
 require(all(config[role]['source_sha256']==freeze['comparison_source']['sha256']for role in('dense_runtime','segmented_runtime')),'Runtime comparison-source digest differs')
 native={k:v for k,v in after.items()if k.startswith('groops/')or k=='scripts/build_groops.py'}
 require(native==receipt['native_inputs'],'Complete current native source inputs differ')
 base=documents['build_base_result'];build=documents['actual_build_result'];runtime=documents['runtime_provenance']
 require(base['status']=='built_precision_candidate'and base['native']['sha256']==BUILD_BASE_NATIVE and base['baseline_relinked_sha256']==base['original_native']['sha256']==ORIGINAL_BUILD_NATIVE,'Build-base lineage is not precision02 from original a669')
 require(build['schema']=='orbit-poc-native-source-delta-build-v1'and build['status']=='built_source_delta_candidate'and build['baseline_result']==receipt['build_base_result'],'New native build attribution differs')
 require(build['baseline_relinked_sha256']==build['baseline_relinked_artifact']['sha256']==base['native']['sha256'],'New build did not reproduce its actual25661 baseline')
 checked(build['baseline_relinked_artifact']);checked(build['native'])
 require(build['source_before']==base['source_after'],'Native source does not start at exact precision02 installed baseline')
 require(build['source_delta']==receipt['native_source_delta'],'Native source delta pin differs')
 changed=verify_installed_delta(documents['native_source_delta'],receipt['build_base_result'],build['source_before'],build['source_after'],after,receipt['installed_source_mapping'],checked)
 require(build['candidate_source_sha256']==digest(build['source_after'])and build['link_command']==base['link_command'],'Installed source digest or baseline link recipe differs')
 require(documents['recipe_inventory']['baseline_result']==receipt['build_base_result'],'Complete recipe inventory baseline differs')
 verify_dependencies(documents['dependency_selection'],documents['recipe_inventory'],build,changed,receipt['candidate_native_source_root'])
 require(build['fit_attempts']==0 and build['release_evidence']is False,'Build receipt asserts unauthorized scientific readiness')
 require(runtime['actual_build_result']==receipt['actual_build_result']and runtime['source_native']==build['native'],'Runtime build attribution differs')
 for name in ('native','build_manifest','library_manifest'):
  checked(runtime[name]);require(config['segmented_runtime'][name]==runtime[name],'Relocated runtime artifact differs: '+name)
 require(runtime['native']['sha256']==build['native']['sha256'],'Relocated executable bytes differ')
 # Compare the entire configuration after substituting only execution locations,
 # source identity, current admission receipt and candidate native artifacts.
 expected=copy.deepcopy(previous)
 expected['output_dir']=config['output_dir'];expected['preparation']['cache_dir']=config['preparation']['cache_dir']
 expected['resources']['admission']=config['resources']['admission']
 for role in ('dense_runtime','segmented_runtime'):
  for name in ('source_root','source_sha256'):expected[role][name]=config[role][name]
 for name in ('native','build_manifest','library_manifest'):expected['segmented_runtime'][name]=config['segmented_runtime'][name]
 require(expected==config,'Physical/statistical settings, reference, resources or unaffected runtime changed')
 require(receipt['fixed_stage_names']==list(stages),'Scientific14 stage sequence differs')
 return True
