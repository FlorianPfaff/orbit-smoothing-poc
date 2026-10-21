"""Unlaunched validation07 full-build provenance checks; no scientific acceptance changes.

The previous validation, build base, and new executable are distinct identities.
This module inspects pinned documents only; it never compiles or launches work.
"""
from pathlib import Path
import collections,copy,hashlib,json,re,shlex

PREVIOUS_FREEZE='87b220cf9a66737e72ed2037c3a80895eb445bf3058918fad32d38e79df8078c'
PREVIOUS_CONFIG='d7d66e175353213889ce32d8606a572d219bc2138ad58f1041558e49b014486b'
PREVIOUS_NATIVE='eb41fabb2117fd81c9d018793ad8e067f6ae65e86d71dae8e6ef8fcca4771133'
PREVIOUS_HEADER='1590e13ff3f69cb6841af8341737b8d52c4d618592070b61b4ae6516f2ea4c28'
BUILD_BASE_RESULT='92dcf754ad42ad22c92b0e0413e86af83fd7d4f9700b69c08c86254022e69224'
BUILD_BASE_NATIVE='25661fd88779c009a84f7479b8fb9639aaeb9a37df3a11dc2d4adff2af94f7c2'
ORIGINAL_BUILD_NATIVE='a66949456ad67b816d09f2f14df792c68c2685f5304139499e4d90092fd75b22'
DENSE_NATIVE='f36bb698ea715a7fc3201c71f823315d493d943ecfb8e7ecad8fbb348ba61625'
PIN_KEYS={'previous_source','previous_config','repository_source_delta','actual_build_result','build_base_result','native_source_delta','original_recipe_inventory','normalized_configuration','complete_compile_evidence','baseline_relink','installation_equivalence','runtime_provenance'}
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

def command_inventory(commands):
 """Independently reconstruct the complete linked target membership."""
 require(isinstance(commands,list)and len(commands)==633 and all(isinstance(x,str)for x in commands),'Expected complete633 command inventory')
 groups={'cpp':{},'fortran':{},'preprocess':{},'link':[],'dyndep':[]}
 for index,text in enumerate(commands):
  words=shlex.split(text)
  if '-E'in words and '-o'in words:kind='preprocess'
  elif '-c'in words and '-o'in words:kind='fortran'if '-fpreprocessed'in words else'cpp'
  elif '-o'in words and words[words.index('-o')+1]=='groops':groups['link'].append((index,words,text));continue
  elif 'cmake_ninja_dyndep'in words:groups['dyndep'].append((index,words,text));continue
  else:raise RuntimeError('Unrecognized complete-build command')
  require(words.count('-o')==1,'Ambiguous command output')
  target=relative(words[words.index('-o')+1]);require(target not in groups[kind],'Repeated command target')
  groups[kind][target]=(index,words,text)
 require([len(groups[k])for k in ('cpp','fortran','preprocess','link','dyndep')]==[591,20,20,1,1],'Complete native command categories differ')
 objects=[x for x in groups['link'][0][1]if x.endswith('.o')]
 require(len(objects)==611 and len(set(objects))==611 and set(objects)==set(groups['cpp'])|set(groups['fortran']),'Native link does not cover every611 compiled object')
 return groups

def normalized_command(command,roots):
 words=shlex.split(command)if isinstance(command,str)else list(command)
 require(isinstance(roots,dict)and len(roots)==2 and set(roots.values())=={'<SOURCE>','<BUILD>'},'Invalid normalized root map')
 for root,label in sorted(roots.items(),key=lambda x:-len(x[0])):
  require(Path(root).is_absolute()and '..'not in Path(root).parts and str(Path(root))==root,'Noncanonical normalized root')
  words=[word.replace(root,label)for word in words]
 return words

def clean_link(words):
 if words[:2]==[':','&&']and words[-2:]==['&&',':']:words=words[2:-2]
 require(not any(x in ('&&',';','|','>','<',':','||','&')for x in words),'Unsupported native link command')
 return words

def ninja_records(text):
 lines=text.splitlines();require(lines and lines[0]=='# ninja log v7','Unknown fresh Ninja log')
 records={}
 for index,line in enumerate(lines[1:],1):
  f=line.split('\t');require(len(f)==5,'Malformed successful Ninja log record')
  start,end,stamp=map(int,f[:3]);require(0<=start<=end and stamp>0,'Invalid native command timing')
  require(f[3]not in records,'Repeated target in purportedly fresh build')
  records[f[3]]={'line':index,'raw':line,'start_ms':start,'end_ms':end,'mtime':stamp,'command_hash':f[4]}
 return records

def verify_baseline_relink(relink,receipt,base,checked):
 require(relink.get('schema')=='orbit-poc-native-baseline-relink-v1'and relink.get('passed')is True,'Baseline relink did not pass')
 require(relink['baseline_result']==receipt['build_base_result']and relink['native']==base['native'],'Baseline relink attribution differs')
 artifact(relink['artifact'],checked);require(relink['artifact']['sha256']==BUILD_BASE_NATIVE,'Relink does not reproduce actual25661 baseline')
 require(relink['link_command']==base['link_command'],'Baseline link command changed')
 objects=[x for x in base['link_command']if x.endswith('.o')]
 require(len(objects)==611 and set(relink['objects'])==set(objects),'Baseline relink object inventory incomplete')
 for name,h in relink['objects'].items():relative(name);hash_value(h)
 linkinputs=read_artifact(relink['link_inputs'],checked)
 require(linkinputs['schema']=='orbit-poc-current-native-link-inputs-v1'and linkinputs['baseline_result']==receipt['build_base_result'],'Baseline link input receipt differs')
 stage=relink['stage'];require(stage['label']=='baseline-link'and stage['argv']==base['link_command']and stage['returncode']==0,'Actual baseline relink stage differs')
 artifact(stage['stdout'],checked);artifact(stage['stderr'],checked)
 baseline_build=Path(receipt['build_base_result']['path']).parents[2]/'build';relink_root=Path(stage['cwd'])
 inputmap={x['path']:x['sha256']for x in linkinputs['inputs']};require(len(inputmap)==len(linkinputs['inputs']),'Repeated original link input')
 for name,h in relink['objects'].items():
  original=baseline_build/name;copied=relink_root/name
  require(inputmap.get(str(original))==h,'Current original object missing from exact link inventory')
  artifact({'path':str(original),'sha256':h},checked);artifact({'path':str(copied),'sha256':h},checked)
  a,b=original.stat(),copied.stat();require((a.st_dev,a.st_ino)!=(b.st_dev,b.st_ino),'Copied baseline object aliases original')
 return True

def verify_complete_build(build,receipt,documents,repo,checked):
 """Verify full fresh compilation from raw recipes, verbose output and log rows."""
 base=documents['build_base_result'];norm=documents['normalized_configuration'];evidence=documents['complete_compile_evidence'];recipes=documents['original_recipe_inventory']
 require(build['schema']=='orbit-poc-native-complete-build-v1'and build['status']=='built_complete_candidate','New native complete build did not pass')
 for name in ('baseline_result','source_delta','original_recipe_inventory','normalized_configuration','complete_compile_evidence','baseline_relink','installation_equivalence'):
  key={'baseline_result':'build_base_result','source_delta':'native_source_delta'}.get(name,name)
  require(build[name]==receipt[key],'Actual complete build evidence pin differs: '+name)
 require(build['compiled_object_count']==611 and build['preprocessing_count']==20 and build['reused_object_count']==0,'Complete-build counts differ')
 require(build['fit_attempts']==0 and build['release_evidence']is False,'Build receipt asserts scientific readiness')
 plan=read_artifact(build['plan'],checked);require(plan['phase']=='build','Complete build result is not the build phase')
 inputs=plan['inputs']
 for key,pin_key in (('baseline_result','build_base_result'),('source_delta','native_source_delta'),('recipe_inventory','original_recipe_inventory')):require(inputs[key]==receipt[pin_key],'Build plan input differs: '+key)
 require(plan['native']==base['native'],'Actual complete-build baseline differs')
 preflight=read_artifact(inputs['preflight_result'],checked);audit=read_artifact(inputs['preflight_audit'],checked)
 require(preflight['status']=='prepared_complete_build'and preflight['inputs']=={k:v for k,v in inputs.items()if k not in ('preflight_result','preflight_audit')},'Complete build preflight inputs differ')
 require(audit.get('passed')is True and audit['preflight_result']==inputs['preflight_result'],'Complete build lacks exact independent preflight approval')
 for key in ('baseline_relink','installation_equivalence','supplemental_fixtures'):require(preflight[key]==audit[key]==build[key],'Preflight artifact approval differs: '+key)
 require(preflight['source_after']==build['source_after'],'Preflight and complete-build source trees differ')
 verify_baseline_relink(documents['baseline_relink'],receipt,base,checked)
 verify_installation(documents['installation_equivalence'],receipt,build,repo,checked)
 install=documents['installation_equivalence'];require(install['request']==inputs['installation_request'],'Build input does not identify actual installation request')
 require({k:install['helper'][k]for k in ('path','sha256')}==inputs['installation_helper'],'Build installation helper differs')
 require(recipes['schema']=='orbit-poc-complete-native-recipes-v1'and recipes['baseline_result']==receipt['build_base_result'],'Original recipes have wrong baseline')
 original=command_inventory(recipes['all_commands'])
 require(clean_link(original['link'][0][1])==base['link_command'],'Original recipes do not reconstruct the actual baseline link')
 require(norm['schema']=='orbit-poc-native-complete-normalized-configuration-v1'and norm['original_recipe_inventory']==receipt['original_recipe_inventory'],'Wrong normalized configuration attribution')
 require(norm['rule']=='shlex tokens; replace only declared absolute source/build roots; preserve every remaining token and command multiplicity','Unreviewed command normalization rule')
 require(norm['serial_jobs']==1 and norm['verbose_only_build_argument']=='--verbose','Native build is not the serial reviewed invocation')
 candidate_doc=read_artifact(norm['candidate_commands'],checked)
 require(candidate_doc['schema']=='orbit-poc-complete-native-command-inventory-v1','Unknown candidate command inventory')
 artifact(candidate_doc['raw'],checked);commands=candidate_doc['commands']
 require(Path(candidate_doc['raw']['path']).read_text().splitlines()==commands,'Candidate command inventory differs from raw Ninja readback')
 candidate=command_inventory(commands)
 oldnorm=[normalized_command(x,norm['original_roots'])for x in recipes['all_commands']]
 newnorm=[normalized_command(x,norm['candidate_roots'])for x in commands]
 require(norm['normalized_commands']==newnorm and collections.Counter(map(json.dumps,oldnorm))==collections.Counter(map(json.dumps,newnorm)),'Normalized compile/preprocess/link recipes changed')
 original_manifest=read_artifact(base['original_build_manifest'],checked)
 old_command=original_manifest['build_command'];old_source=old_command[old_command.index('-S')+1];old_build=old_command[old_command.index('-B')+1]
 require(norm['original_roots']=={old_source:'<SOURCE>',old_build:'<BUILD>'}and recipes['recorded_source_root']==old_source,'Original normalization roots differ')
 candidate_source=receipt['candidate_native_source_root']
 build_root=str(Path(evidence['ninja_log']['path']).parent)
 execution=read_artifact(plan['execution'],checked)
 require(candidate_source==str(Path(execution['paths']['native_source'])/'candidate/source')and build_root==execution['paths']['build'],'Actual candidate source/build directories differ')
 require(norm['candidate_roots']=={candidate_source:'<SOURCE>',build_root:'<BUILD>'},'Candidate normalization roots differ')
 require(evidence['schema']=='orbit-poc-native-complete-compile-evidence-v1'and evidence['candidate_commands']==norm['candidate_commands']and evidence['reused_object_count']==0,'Wrong complete compilation evidence')
 artifact(evidence['ninja_log'],checked);artifact(evidence['verbose_stdout'],checked)
 logs=ninja_records(Path(evidence['ninja_log']['path']).read_text());actual=[]
 for line in Path(evidence['verbose_stdout']['path']).read_text().splitlines():
  found=re.match(r'^\[\d+/\d+\] (.*)$',line)
  if found:actual.append(found[1])
 require(collections.Counter(actual)==collections.Counter(commands),'Successful verbose command inventory incomplete')
 require(evidence['linked_objects']==sorted(set(candidate['cpp'])|set(candidate['fortran'])),'Compiled-object inventory differs from link inputs')
 for language in ('cpp','fortran','preprocess'):
  require(set(evidence[language])==set(candidate[language]),'Missing successful native command category: '+language)
  for target,(index,argv,text)in candidate[language].items():
   row=evidence[language][target]
   require(row['path']==str(Path(build_root)/target)and row['command_index']==index and row['verbose_index']==actual.index(text),'Object command/path attribution differs')
   require(target in logs and row['ninja_log']==logs[target],'Object successful Ninja log attribution differs')
   artifact({k:row[k]for k in ('path','sha256','bytes')},checked)
   stat=Path(row['path']).stat();require(stat.st_dev==row['device']and stat.st_ino==row['inode'],'Fresh object identity changed')
   if language in ('cpp','fortran'):
    original=(Path(receipt['build_base_result']['path']).parents[2]/'build'/target).stat()
    require((stat.st_dev,stat.st_ino)!=(original.st_dev,original.st_ino),'Fresh compiled object aliases preserved baseline')
 require(evidence['link']=={'command_index':candidate['link'][0][0],'verbose_index':actual.index(candidate['link'][0][2]),'ninja_log':logs['groops']},'Actual successful native link attribution differs')
 stages=build['stages'];labels=[x['label']for x in stages]
 require(labels==['public-installer-0','public-installer-1','public-installer-2','configure','complete-build','native-help','candidate-command-inventory','candidate-dependency-inventory'],'Public full-build stage sequence differs')
 for stage in stages:
  require(stage['returncode']==0,'Native complete-build stage failed');artifact(stage['stdout'],checked);artifact(stage['stderr'],checked)
 require(evidence['build_stage']==stages[4]and stages[4]['stdout']==evidence['verbose_stdout'],'Actual build output attribution differs')
 tool=read_artifact(norm['compiler_pins'],checked)
 require(norm['compiler_pins']==inputs['toolchain'],'Actual build toolchain receipt differs')
 require(set(tool)=={'schema','python','cmake','ninja','cxx','cc','fc','git'}and tool['schema']=='orbit-poc-native-complete-toolchain-v1','Unknown complete-build toolchain')
 for key in set(tool)-{'schema'}:artifact(tool[key],checked)
 require(tool['cxx']['path']==base['link_command'][0],'C++ compiler differs from baseline')
 for language in ('cpp','fortran','preprocess'):
  for target,(_,argv,_)in candidate[language].items():
   require(argv[0]==tool['cxx'if language=='cpp'else'fc']['path'],'Actual compile/preprocess compiler differs')
   if language in ('cpp','preprocess'):
    source=Path(argv[argv.index('-c'if language=='cpp'else'-E')+1])
    require(source.is_relative_to(candidate_source)and str(source.relative_to(candidate_source))in build['source_after'],'Compilation does not use a frozen candidate translation unit')
   else:require(argv[argv.index('-c')+1]in candidate['preprocess'],'Fortran compilation lacks its exact fresh preprocessed output')
 calls=norm['public_run_calls'];require(len(calls)==6,'Public script command count differs')
 for index,stage in enumerate(stages[:6]):require(stage['argv']==calls[index]+(['--verbose']if index==4 else[]),'Actual public build call differs')
 require(calls[4]==[tool['cmake']['path'],'--build',build_root,'--parallel','1']and calls[5]==[str(Path(build_root)/'groops'),'--help'],'Complete build or native help command differs')
 request=read_artifact(install['request'],checked);repository=read_artifact(request['repository_inventory'],checked);repo_root=Path(repository['root']);checkout=Path(candidate_source).parent
 for index,name in enumerate(('apply_extension.py','native_segmented.py','native_tangent_wide.py')):
  require(calls[index][1:]==[str(repo_root/'groops/extension'/name),str(checkout)]+(['--numerics']if index==0 else[]),'Actual public installer command differs')
  artifact({'path':calls[index][0],'sha256':tool['python']['sha256']},checked)
 require(norm['public_script_argv']==[str(repo_root/'scripts/build_groops.py'),'--source-dir',str(checkout),'--build-dir',build_root,'--prefix',execution['paths']['prefix'],'--jobs','1','--numerics','--segmented','--wide-tangent-candidate','--cmake-executable',tool['cmake']['path']],'Public build script opt-in or arguments differ')
 wanted=list(old_command);wanted[wanted.index('-S')+1]=candidate_source;wanted[wanted.index('-B')+1]=build_root
 require(calls[3]==wanted and calls[3][0]==tool['cmake']['path'],'Pinned configure arguments changed')
 require(stages[6]['argv']==[tool['ninja']['path'],'-C',build_root,'-t','commands','groops']and stages[6]['stdout']==candidate_doc['raw'],'Candidate recipe readback stage differs')
 require(stages[7]['argv']==[tool['ninja']['path'],'-C',build_root,'-t','deps']and stages[7]['stdout']==build['candidate_dependencies'],'Candidate dependency readback attribution differs')
 artifact(build['candidate_dependencies'],checked)
 manifest=read_artifact(build['build_manifest'],checked);artifact(build['cmake_cache'],checked);artifact(build['native'],checked)
 require(manifest['executable_sha256']==build['native']['sha256']and manifest['cmake_cache_sha256']==build['cmake_cache']['sha256'],'Final build manifest executable/cache differs')
 require(manifest['mpi']is False and manifest['upstream_commit']==UPSTREAM_COMMIT and manifest['build_command']==calls[3],'Final build configuration differs')
 require(manifest['build_script_sha256']==repo['scripts/build_groops.py'],'Public candidate build script differs')
 require(manifest.get('wide_tangent_extension')=={'schema':'orbit-poc-wide-tangent-install-v1','candidate_only':True,'changed_files':7,'source_hashes':{name:build['source_after'][name]for name in receipt['installed_source_mapping']},'manifest_sha256':repo['groops/extension/wide_tangent/manifest.json'],'compiled':False},'Public candidate overlay attribution differs')
 installed={}
 for name,h in manifest['patched_source']['files'].items():
  require(name.startswith('source/'),'Unknown build manifest source prefix');rel=relative(name[len('source/'):]);require(rel not in installed,'Repeated build manifest source');installed[rel]=h
 require(installed==build['source_after']and manifest['patched_source']['sha256']==digest(manifest['patched_source']['files']),'Full compiled source manifest differs')
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

INSTALLER_HELPER='ea31f14adbabd7e8aae798ca181e685725e06ef182c08ae455ed68588b2fc8d4'
UPSTREAM_COMMIT='7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee'

def artifact(record,checked):
 """Nested installer receipts add size; public configuration pins stay strict."""
 require(isinstance(record,dict)and {'path','sha256'}<=set(record)<= {'path','sha256','bytes'},'Invalid nested artifact pin')
 checked({k:record[k]for k in ('path','sha256')})
 if 'bytes'in record:require(type(record['bytes'])is int and record['bytes']>=0 and Path(record['path']).stat().st_size==record['bytes'],'Artifact size differs')
 return record

def read_artifact(record,checked):
 artifact(record,checked)
 return json.loads(Path(record['path']).read_text())

def verify_installation(install,receipt,build,repo,checked):
 """Bind the actual source-only installation to the entire compiled tree."""
 require(install.get('schema')=='orbit-poc-native-installer-equivalence-result-v1'and install.get('status')=='passed'and install.get('passed')is True,'Source-only installation did not pass')
 require(install.get('compiled')is False and install.get('native_launches')==0 and install.get('git_mutations')==0,'Installation receipt has unexpected execution scope')
 for flag in ('repository_preserved','git_head_preserved','pinned_inputs_preserved'):require(install.get(flag)is True,'Installation preservation unverified: '+flag)
 artifact(install['helper'],checked);require(install['helper']['sha256']==INSTALLER_HELPER,'Unreviewed source-only installation helper')
 request=read_artifact(install['request'],checked)
 fields={'schema','archive','archive_provenance','python','git','git_head','git_dir','repository_inventory','baseline_result','source_delta','output'}
 require(set(request)==fields and request['schema']=='orbit-poc-native-installer-equivalence-request-v1','Unknown source installation request')
 require(install['inputs']=={k:request[k]for k in fields-{'schema','output'}},'Actual installation input attribution differs')
 for key in fields-{'schema','output','git_dir'}:artifact(request[key],checked)
 require(install['baseline_result']==request['baseline_result']==receipt['build_base_result'],'Installation build baseline differs')
 require(install['source_delta']==request['source_delta']==receipt['native_source_delta'],'Installation source delta differs')
 require(install['repository_inventory']==request['repository_inventory'],'Installation repository inventory pin differs')
 inventory=read_artifact(request['repository_inventory'],checked)
 require(set(inventory)=={'schema','root','files'}and inventory['schema']=='orbit-poc-native-installer-repository-inventory-v1','Unknown installation repository inventory')
 require(inventory['files']=={k:v for k,v in repo.items()if k.startswith('groops/')or k=='scripts/build_groops.py'},'Installer repository differs from frozen native source')
 source_map(install['source_after'])
 require(install['source_after']==build['source_after'],'Full pristine-installed tree differs from compiled source')
 count=len(build['source_after']);require(count==1134,'Unexpected complete installed source membership')
 require(install['comparison']=={'expected_files':count,'actual_files':count,'missing':[],'extra':[],'different':[]},'Incomplete pristine-install comparison')
 require(install['source_after_sha256']==install['expected_source_sha256']==digest(build['source_after']),'Pristine-install source digest differs')
 output=Path(request['output']);checkout=output/'checkout';root=Path(inventory['root']);gitdir=Path(request['git_dir'])
 require(output.is_absolute()and root.is_absolute()and gitdir.is_absolute()and install['installed_checkout']==str(checkout),'Installation output/source attribution differs')
 provenance=read_artifact(request['archive_provenance'],checked)
 require(provenance.get('schema')=='orbit-poc-pristine-native-source-archive-v1'and provenance.get('commit')==UPSTREAM_COMMIT and provenance.get('uses_git_object_content_not_worktree')is True,'Wrong pristine archive provenance')
 require(provenance['archive']==request['archive']==install['archive']and provenance['git_sha256']==request['git']['sha256']and install['archive_provenance']==request['archive_provenance'],'Pristine archive identity differs')
 expected=[
  [request['git']['path'],'-C',provenance['repository'],'rev-parse','--absolute-git-dir'],
  [request['git']['path'],'-C',provenance['repository'],'rev-parse','HEAD'],
  [request['python']['path'],str(root/'groops/extension/apply_extension.py'),str(checkout),'--numerics'],
  [request['python']['path'],str(root/'groops/extension/native_segmented.py'),str(checkout)],
  [request['python']['path'],str(root/'groops/extension/native_tangent_wide.py'),str(checkout)],
  [request['git']['path'],'-C',str(gitdir.parent),'rev-parse','HEAD']]
 require([x['argv']for x in install['commands']]==expected,'Source-only installation command sequence differs')
 for command in install['commands']:
  require(command['returncode']==0,'Source-only installation command failed')
  artifact(command['stdout'],checked);artifact(command['stderr'],checked)
 require(Path(install['commands'][0]['stdout']['path']).read_text().strip()==str(gitdir),'Genuine Git directory readback differs')
 for index in (1,5):require(Path(install['commands'][index]['stdout']['path']).read_text().strip()==UPSTREAM_COMMIT,'Genuine Git commit readback differs')
 archive=read_artifact(install['archive_member_inventory'],checked)
 require(archive['schema']=='orbit-poc-upstream-archive-members-v1'and archive['archive']==request['archive'],'Archive member receipt differs')
 names=[x['path']for x in archive['members']];require(len(names)==len(set(names))and names,'Repeated or empty archive inventory')
 expected_pristine={}
 for row in archive['members']:
  name=relative(row['path']);require(name=='source'or name.startswith('source/'),'Archive member outside source')
  if row['kind']=='file':require(name!='source','Invalid archive file root');expected_pristine[name[len('source/'):]]=hash_value(row['sha256'])
  else:require(row['kind']=='directory','Unsupported archive member type')
 require(install['pristine_source']==expected_pristine,'Pristine archive extraction inventory differs')
 return True


def verify_native_provenance(receipt,config,freeze,checked,stages):
 require(set(receipt)==RECEIPT_KEYS and receipt['schema']=='orbit-poc-v4-native-rebuild-provenance-v3'and receipt['status']=='verified_actual_complete_rebuild','Unknown validation07 native provenance')
 documents={k:read(receipt[k],checked)for k in PIN_KEYS}
 require(receipt['previous_source']['sha256']==PREVIOUS_FREEZE and receipt['previous_config']['sha256']==PREVIOUS_CONFIG and receipt['build_base_result']['sha256']==BUILD_BASE_RESULT,'Historical validation/build source identity differs')
 require(freeze['previous_source']==receipt['previous_source'],'Current freeze predecessor differs')
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
 require(build['source_before']==base['source_after'],'Native source does not start at exact precision02 installed baseline')
 require(build['source_delta']==receipt['native_source_delta'],'Native source delta pin differs')
 verify_installed_delta(documents['native_source_delta'],receipt['build_base_result'],build['source_before'],build['source_after'],after,receipt['installed_source_mapping'],checked)
 require(build['candidate_source_sha256']==digest(build['source_after']),'Complete native source digest differs')
 verify_complete_build(build,receipt,documents,after,checked)
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
