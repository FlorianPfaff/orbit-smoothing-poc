from pathlib import Path
c=Path('/mnt/d/orbit-segmented-v4/control');s=(c/'build_tangent_capture03.py').read_text()
s=s.replace('Diagnostic-only single-TU rebuild using exact copied original link objects.','Separate precision-candidate rebuild of every recorded dependent translation unit.')
s=s.replace("KEYS={'original_build_manifest','recipe_inspection','capture_header','capture_block','reader_source','reader_manifest','reader_tangent','reader_force','reader_quadrature'}","KEYS={'original_build_manifest','recipe_inspection','link_inspection','candidate_header'}")
start=s.index('def validate_capture_delta(');end=s.index('def save(',start);s=s[:start]+s[end:]
start=s.index('def recipes(');end=s.index('def main():',start)
s=s[:start]+'''def recipes(record,original_source,new_source):
 if record['commands_count']!=633 or len(record['selected_compile_commands'])!=27 or len(record['header_dependency_blocks'])!=27:raise ValueError('Unexpected complete dependency inventory')
 targets=set()
 for block in record['header_dependency_blocks']:
  line=block.splitlines()[0]
  if '(VALID)'not in line or str(original_source/'source/misc/orbitPoc/sixStateTangent.h')not in block:raise ValueError('Invalid recorded tangent dependency')
  target=line.split(': #deps ',1)[0]
  if target in targets:raise ValueError('Duplicate dependency target')
  targets.add(target)
 if targets!=set(record['selected_compile_commands']):raise ValueError('Compile recipes omit tangent dependency')
 result={}
 for target,command in sorted(record['selected_compile_commands'].items()):
  argv=shlex.split(command)
  if argv[argv.index('-o')+1]!=target or not Path(argv[argv.index('-c')+1]).is_relative_to(original_source/'source'):raise ValueError('Unexpected translation unit')
  if any(x in ('&&',';','|','>','<')for x in argv):raise ValueError('Shell operation in compile argv')
  changed=[x.replace(str(original_source),str(new_source))for x in argv]
  if sum(a!=b for a,b in zip(argv,changed))!=2:raise ValueError('Exactly include/source roots must change')
  result[target]=changed
 link=shlex.split(record['link_command'])
 if link[:2]!=[':','&&']or link[-2:]!=['&&',':']:raise ValueError('Unsupported link recipe shell structure')
 link=link[2:-2]
 if any(x in ('&&',';','|','>','<')for x in link)or link[link.index('-o')+1]!='groops':raise ValueError('Unexpected link recipe')
 if not targets.issubset(link)or any(argv[0]!=link[0]for argv in result.values()):raise ValueError('Compile targets/compiler disagree with link')
 return result,link
''' +s[end:]
start=s.index(" installed='misc/orbitPoc/stagedVariationalBody.h'");end=s.index(' object_names=',start)
s=s[:start]+''' installed='misc/orbitPoc/sixStateTangent.h';candidate=check(p['inputs']['candidate_header']);target_header=paths['native_source']/'source'/installed
 assert sha(target_header)==before[installed] and sha(candidate)!=before[installed]
 target_header.write_bytes(candidate.read_bytes());after=files(paths['native_source']/'source');assert {k for k in before if before[k]!=after[k]}=={installed} and set(before)==set(after)
 inspection=json.loads(check(p['inputs']['recipe_inspection']).read_text());compile_commands,link=recipes(inspection,original_source,paths['native_source']);link_inspection=json.loads(check(p['inputs']['link_inspection']).read_text())
''' +s[end:]
s=s.replace("dependencies=inspection['link_dependency_block'].splitlines()","dependencies=link_inspection['link_dependency_block'].splitlines()").replace("pinned_link_inputs=inspection['original_link_input_pins']","pinned_link_inputs=link_inspection['original_link_input_pins']")
s=s.replace("assert sha(Path(compile_[0]))==e['runtime_artifacts']['cxx_compiler']['sha256']","assert sha(Path(link[0]))==e['runtime_artifacts']['cxx_compiler']['sha256']")
s=s.replace("'schema':'orbit-poc-tangent-capture-diagnostic-build-v1'","'schema':'orbit-poc-tangent-precision-candidate-build-v1'").replace("'compile_command':compile_","'compile_commands':compile_commands")
s=s.replace(" run('compile',compile_)\n assert {name for name in object_names if sha(paths['build']/name)!=originals[name]}=={target}"," for index,(target,command)in enumerate(compile_commands.items()):run('compile-'+str(index).zfill(2),command)\n changed_objects={name for name in object_names if sha(paths['build']/name)!=originals[name]}\n assert changed_objects.issubset(compile_commands) and 'CMakeFiles/groopscore.dir/programs/preprocessing/preprocessingVariationalEquation.cpp.o'in changed_objects")
s=s.replace("('groops-capture-'+sha(paths['build']/'groops')[:16])","('groops-precision-'+sha(paths['build']/'groops')[:16])")
start=s.index(" reader=paths['binaries']/'tangent-replay'");end=s.index(" save(root/'result.json',record)",start)
s=s[:start]+''' record.update(status='built_precision_candidate',baseline_relinked_sha256=p['native']['sha256'],native={'path':str(native),'sha256':sha(native)},compiler_version=subprocess.check_output([link[0],'--version'],env=env,text=True),original_native=p['native'],candidate_source_sha256=hashlib.sha256(json.dumps(after,sort_keys=True,separators=(',',':')).encode()).hexdigest(),reused_object_count=len(object_names)-len(compile_commands),rebuilt_objects=list(compile_commands),changed_objects=sorted(changed_objects))
''' +s[end:]
s=s.replace(",'reader':record['reader']","")
(c/'build_tangent_precision01.py').write_text(s)
s=(c/'run_tangent_capture_build03.py').read_text().replace('orbit-poc-tangent-capture-build-plan-v1','orbit-poc-tangent-precision-build-plan-v1').replace('orbit-poc-owned-tangent-capture-build-v1','orbit-poc-owned-tangent-precision-build-v1').replace("{'original_build_manifest','recipe_inspection','capture_header','capture_block','reader_source','reader_manifest','reader_tangent','reader_force','reader_quadrature'}","{'original_build_manifest','recipe_inspection','link_inspection','candidate_header'}")
(c/'run_tangent_precision_build01.py').write_text(s)
