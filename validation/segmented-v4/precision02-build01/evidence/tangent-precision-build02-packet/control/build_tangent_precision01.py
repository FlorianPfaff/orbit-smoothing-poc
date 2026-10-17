#!/usr/bin/env python3
"""Separate precision-candidate rebuild of every recorded dependent translation unit."""
from pathlib import Path
import argparse,hashlib,json,os,shlex,shutil,subprocess
KEYS={'original_build_manifest','recipe_inspection','link_inspection','candidate_header'}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(p):
 if set(p)!={'path','sha256'} or sha(p['path'])!=p['sha256']:raise ValueError('Changed build input')
 return Path(p['path'])
def files(root):return {str(p.relative_to(root)):sha(p)for p in sorted(root.rglob('*'))if p.is_file()}
def normalized_source_files(value):
 if not isinstance(value,dict) or not value:raise ValueError('Missing original source receipt')
 result={}
 for name,digest in value.items():
  if not isinstance(name,str) or not name.startswith('source/') or name=='source/':raise ValueError('Original source receipt has outside-prefix member')
  relative=name[len('source/'):]
  if Path(relative).is_absolute() or '..'in Path(relative).parts or str(Path(relative))!=relative or relative in result:raise ValueError('Invalid or duplicate normalized source member')
  if not isinstance(digest,str) or len(digest)!=64 or any(x not in '0123456789abcdef'for x in digest):raise ValueError('Invalid source digest')
  result[relative]=digest
 return result
def save(path,value):
 with Path(path).open('x') as f:json.dump(value,f,indent=2,sort_keys=True);f.write('\n')
def recipes(record,original_source,new_source):
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
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--sha256',required=True);a=ap.parse_args();assert sha(a.plan)==a.sha256;p=json.loads(a.plan.read_text());assert set(p['inputs'])==KEYS
 for x in p['inputs'].values():check(x)
 e=json.loads(check(p['execution']).read_text());paths={k:Path(v)for k,v in e['paths'].items()};root=Path(p['output']);assert not root.exists();root.mkdir()
 original_manifest=check(p['inputs']['original_build_manifest']);original_build=original_manifest.parent;original_source=original_build.parent/'groops-source';manifest=json.loads(original_manifest.read_text());before=files(original_source/'source')
 assert before==normalized_source_files(manifest['patched_source']['files']) and manifest['executable_sha256']==p['native']['sha256']==sha(original_build/'groops')
 for name in ('native_source','build','binaries'):
  target=paths[name];assert target.is_dir() and not target.is_symlink() and target.resolve()==target and not any(target.iterdir())
  assert all(target!=old and target not in old.parents and old not in target.parents for old in (original_source,original_build))
 assert len({paths[name]for name in ('native_source','build','binaries')})==3
 shutil.copytree(original_source/'source',paths['native_source']/'source')
 newsource=files(paths['native_source']/'source');assert newsource==before
 installed='misc/orbitPoc/sixStateTangent.h';candidate=check(p['inputs']['candidate_header']);target_header=paths['native_source']/'source'/installed
 assert sha(target_header)==before[installed] and sha(candidate)!=before[installed]
 target_header.write_bytes(candidate.read_bytes());after=files(paths['native_source']/'source');assert {k for k in before if before[k]!=after[k]}=={installed} and set(before)==set(after)
 inspection=json.loads(check(p['inputs']['recipe_inspection']).read_text());compile_commands,link=recipes(inspection,original_source,paths['native_source']);link_inspection=json.loads(check(p['inputs']['link_inspection']).read_text())
 object_names=[x for x in link if x.endswith('.o')];assert len(object_names)==len(set(object_names)) and all(not Path(x).is_absolute() and '..'not in Path(x).parts for x in object_names)
 originals={name:sha(original_build/name)for name in object_names}
 for name in object_names:
  dest=paths['build']/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original_build/name,dest);assert sha(dest)==originals[name] and dest.stat().st_ino!=(original_build/name).stat().st_ino
 dependencies=link_inspection['link_dependency_block'].splitlines()
 assert dependencies[0].startswith('groops: #deps ') and '(VALID)'in dependencies[0]
 link_inputs={}
 for word in dependencies[1:]:
  word=word.strip()
  if not word:continue
  item=Path(word)if Path(word).is_absolute()else original_build/word
  assert item.is_file(),str(item)
  link_inputs[str(item)]=sha(item)
 assert len(link_inputs)==637
 pinned_link_inputs=link_inspection['original_link_input_pins'];assert len(pinned_link_inputs)==637
 assert {x['path']:x['sha256']for x in pinned_link_inputs}==link_inputs
 for item in pinned_link_inputs:
  current=Path(item['path']).stat();assert (current.st_dev,current.st_ino,current.st_size)==(item['device'],item['inode'],item['bytes'])
 libraries={x:sha(Path(x))for x in link if x.startswith('/') and Path(x).is_file()};assert sha(Path(link[0]))==e['runtime_artifacts']['cxx_compiler']['sha256']
 record={'schema':'orbit-poc-tangent-precision-candidate-build-v1','status':'building','original_build_manifest':p['inputs']['original_build_manifest'],'source_before':before,'source_after':after,'changed_native_file':installed,'original_object_sha256':originals,'link_libraries':libraries,'all_original_link_inputs':link_inputs,'compile_commands':compile_commands,'link_command':link,'fit_attempts':0,'release_evidence':False}
 save(root/'inputs.json',record)
 env=dict(os.environ,PATH=str(paths['prefix']/'bin')+':/usr/bin:/bin',LD_LIBRARY_PATH=str(paths['prefix']/'lib'))
 def run(label,argv):
  with(root/(label+'.log')).open('x')as out:subprocess.run(argv,cwd=paths['build'],env=env,stdout=out,stderr=subprocess.STDOUT,check=True)
 run('baseline-link',link)
 assert sha(paths['build']/'groops')==p['native']['sha256'],'Copied original objects failed exact baseline link reproduction'
 for index,(target,command)in enumerate(compile_commands.items()):run('compile-'+str(index).zfill(2),command)
 changed_objects={name for name in object_names if sha(paths['build']/name)!=originals[name]}
 assert changed_objects.issubset(compile_commands) and 'CMakeFiles/groopscore.dir/programs/preprocessing/preprocessingVariationalEquation.cpp.o'in changed_objects
 run('link',link);run('native-help',[str(paths['build']/'groops'),'--help'])
 assert files(paths['native_source']/'source')==after
 assert files(original_source/'source')==before and all(sha(original_build/name)==digest for name,digest in originals.items()) and all(sha(Path(name))==digest for name,digest in libraries.items()) and all(sha(Path(name))==digest for name,digest in link_inputs.items())
 native=paths['binaries']/('groops-precision-'+sha(paths['build']/'groops')[:16]);shutil.copy2(paths['build']/'groops',native);native.chmod(0o555)
 record.update(status='built_precision_candidate',baseline_relinked_sha256=p['native']['sha256'],native={'path':str(native),'sha256':sha(native)},compiler_version=subprocess.check_output([link[0],'--version'],env=env,text=True),original_native=p['native'],candidate_source_sha256=hashlib.sha256(json.dumps(after,sort_keys=True,separators=(',',':')).encode()).hexdigest(),reused_object_count=len(object_names)-len(compile_commands),rebuilt_objects=list(compile_commands),changed_objects=sorted(changed_objects))
 save(root/'result.json',record)
 for x in p['inputs'].values():check(x)
 print(json.dumps({'status':record['status'],'native':record['native'],'reused_objects':record['reused_object_count']}))
if __name__=='__main__':main()
