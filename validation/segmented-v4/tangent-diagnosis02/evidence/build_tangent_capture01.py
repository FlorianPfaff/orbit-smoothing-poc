#!/usr/bin/env python3
"""Diagnostic-only single-TU rebuild using exact copied original link objects."""
from pathlib import Path
import argparse,hashlib,json,os,shlex,shutil,subprocess
KEYS={'original_build_manifest','recipe_inspection','capture_header','reader_source','reader_manifest','reader_tangent','reader_force','reader_quadrature'}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(p):
 if set(p)!={'path','sha256'} or sha(p['path'])!=p['sha256']:raise ValueError('Changed build input')
 return Path(p['path'])
def files(root):return {str(p.relative_to(root)):sha(p)for p in sorted(root.rglob('*'))if p.is_file()}
def save(path,value):
 with Path(path).open('x') as f:json.dump(value,f,indent=2,sort_keys=True);f.write('\n')
def recipes(record,original_source,new_source):
 if record['commands_count']!=633 or len(record['selected_commands'])!=2 or len(record['header_dependency_blocks'])!=1:raise ValueError('Unexpected original dependency graph')
 compile_,link=map(shlex.split,record['selected_commands']);target='CMakeFiles/groopscore.dir/programs/preprocessing/preprocessingVariationalEquation.cpp.o'
 if compile_[compile_.index('-o')+1]!=target or compile_[compile_.index('-c')+1]!=str(original_source/'source/programs/preprocessing/preprocessingVariationalEquation.cpp'):raise ValueError('Unexpected translation unit')
 if link[:2]!=[':','&&'] or link[-2:]!=['&&',':']:raise ValueError('Unsupported link recipe shell structure')
 link=link[2:-2]
 if any(x in ('&&',';','|','>','<') for x in compile_+link):raise ValueError('Shell operation in direct argv')
 if compile_[0]!=link[0] or link[link.index('-o')+1]!='groops' or target not in link:raise ValueError('Unexpected link target/compiler')
 changed=[x.replace(str(original_source),str(new_source))for x in compile_]
 if sum(a!=b for a,b in zip(compile_,changed))!=2:raise ValueError('Exactly source include/translation-unit roots must change')
 return changed,link,target
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--sha256',required=True);a=ap.parse_args();assert sha(a.plan)==a.sha256;p=json.loads(a.plan.read_text());assert set(p['inputs'])==KEYS
 for x in p['inputs'].values():check(x)
 e=json.loads(check(p['execution']).read_text());paths={k:Path(v)for k,v in e['paths'].items()};root=Path(p['output']);assert not root.exists();root.mkdir()
 original_manifest=check(p['inputs']['original_build_manifest']);original_build=original_manifest.parent;original_source=original_build.parent/'groops-source';manifest=json.loads(original_manifest.read_text());before=files(original_source/'source')
 assert before==manifest['patched_source']['files'] and manifest['executable_sha256']==p['native']['sha256']==sha(original_build/'groops')
 for name in ('native_source','build','binaries'):
  target=paths[name];assert target.is_dir() and not target.is_symlink() and target.resolve()==target and not any(target.iterdir())
  assert all(target!=old and target not in old.parents and old not in target.parents for old in (original_source,original_build))
 assert len({paths[name]for name in ('native_source','build','binaries')})==3
 shutil.copytree(original_source/'source',paths['native_source']/'source')
 newsource=files(paths['native_source']/'source');assert newsource==before
 installed='misc/orbitPoc/stagedVariationalBody.h';capture=check(p['inputs']['capture_header']);target_header=paths['native_source']/'source'/installed
 assert sha(target_header)=='39ec6589cc2b7d1b36d7712760169a030682f957ba286743248517f4c71ebb0d'
 target_header.write_bytes(capture.read_bytes());after=files(paths['native_source']/'source');assert {k for k in before if before[k]!=after[k]}=={installed} and set(before)==set(after)
 inspection=json.loads(check(p['inputs']['recipe_inspection']).read_text());compile_,link,target=recipes(inspection,original_source,paths['native_source'])
 object_names=[x for x in link if x.endswith('.o')];assert len(object_names)==len(set(object_names)) and all(not Path(x).is_absolute() and '..'not in Path(x).parts for x in object_names)
 originals={name:sha(original_build/name)for name in object_names}
 for name in object_names:
  dest=paths['build']/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original_build/name,dest);assert sha(dest)==originals[name] and dest.stat().st_ino!=(original_build/name).stat().st_ino
 dependencies=inspection['link_dependency_block'].splitlines()
 assert dependencies[0].startswith('groops: #deps ') and '(VALID)'in dependencies[0]
 link_inputs={}
 for word in dependencies[1:]:
  word=word.strip()
  if not word:continue
  item=Path(word)if Path(word).is_absolute()else original_build/word
  assert item.is_file(),str(item)
  link_inputs[str(item)]=sha(item)
 assert len(link_inputs)==637
 pinned_link_inputs=inspection['original_link_input_pins'];assert len(pinned_link_inputs)==637
 assert {x['path']:x['sha256']for x in pinned_link_inputs}==link_inputs
 for item in pinned_link_inputs:
  current=Path(item['path']).stat();assert (current.st_dev,current.st_ino,current.st_size)==(item['device'],item['inode'],item['bytes'])
 libraries={x:sha(Path(x))for x in link if x.startswith('/') and Path(x).is_file()};assert sha(Path(compile_[0]))==e['runtime_artifacts']['cxx_compiler']['sha256']
 record={'schema':'orbit-poc-tangent-capture-diagnostic-build-v1','status':'building','original_build_manifest':p['inputs']['original_build_manifest'],'source_before':before,'source_after':after,'changed_native_file':installed,'original_object_sha256':originals,'link_libraries':libraries,'all_original_link_inputs':link_inputs,'compile_command':compile_,'link_command':link,'fit_attempts':0,'release_evidence':False}
 save(root/'inputs.json',record)
 env=dict(os.environ,PATH=str(paths['prefix']/'bin')+':/usr/bin:/bin',LD_LIBRARY_PATH=str(paths['prefix']/'lib'))
 def run(label,argv):
  with(root/(label+'.log')).open('x')as out:subprocess.run(argv,cwd=paths['build'],env=env,stdout=out,stderr=subprocess.STDOUT,check=True)
 run('baseline-link',link)
 assert sha(paths['build']/'groops')==p['native']['sha256'],'Copied original objects failed exact baseline link reproduction'
 run('compile',compile_)
 assert {name for name in object_names if sha(paths['build']/name)!=originals[name]}=={target}
 run('link',link);run('native-help',[str(paths['build']/'groops'),'--help'])
 assert files(paths['native_source']/'source')==after
 assert files(original_source/'source')==before and all(sha(original_build/name)==digest for name,digest in originals.items()) and all(sha(Path(name))==digest for name,digest in libraries.items()) and all(sha(Path(name))==digest for name,digest in link_inputs.items())
 native=paths['binaries']/('groops-capture-'+sha(paths['build']/'groops')[:16]);shutil.copy2(paths['build']/'groops',native);native.chmod(0o555)
 reader=paths['binaries']/'tangent-replay';reader_source=check(p['inputs']['reader_source']);reader_command=[compile_[0],'-O3','-DNDEBUG','-std=gnu++17','-I'+str(reader_source.parent/'include'),str(reader_source),'-o',str(reader)]
 run('reader-compile',reader_command)
 reader_loader=subprocess.check_output(['/usr/bin/ldd',str(reader)],env=env,text=True)
 reader_library_paths=[]
 for line in reader_loader.splitlines():
  for word in line.split():
   if word.startswith('/') and Path(word).is_file():reader_library_paths.append(word)
 reader_libraries=[{'path':name,'resolved':str(Path(name).resolve()),'sha256':sha(Path(name))}for name in sorted(set(reader_library_paths))]
 assert any('libstdc++.so' in x['path'] for x in reader_libraries)
 record.update(status='built_diagnostic_only',baseline_relinked_sha256=p['native']['sha256'],native={'path':str(native),'sha256':sha(native)},reader={'path':str(reader),'sha256':sha(reader)},reader_compile_command=reader_command,reader_loader_output=reader_loader,reader_libraries=reader_libraries,compiler_version=subprocess.check_output([compile_[0],'--version'],env=env,text=True),original_native=p['native'],candidate_source_sha256=hashlib.sha256(json.dumps(after,sort_keys=True,separators=(',',':')).encode()).hexdigest(),reused_object_count=len(object_names)-1,changed_object=target)
 save(root/'result.json',record)
 for x in p['inputs'].values():check(x)
 print(json.dumps({'status':record['status'],'native':record['native'],'reader':record['reader'],'reused_objects':record['reused_object_count']}))
if __name__=='__main__':main()
