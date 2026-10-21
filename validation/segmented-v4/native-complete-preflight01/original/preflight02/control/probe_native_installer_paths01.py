from pathlib import Path
import json,hashlib,importlib.util,sys
I=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/native-complete-inputs-01');J=I.with_name('native-complete-inputs-02');sp=importlib.util.spec_from_file_location('helper',I/'verify_native_installer_equivalence02.py');h=importlib.util.module_from_spec(sp);sp.loader.exec_module(h);r=json.loads((J/'installation-request.json').read_text());out=[]
for key,value in r.items():
 if not isinstance(value,dict)or'path'not in value:continue
 path=Path(value['path']);resolved=path.resolve();row={'key':key,'declared':value,'resolved_path':str(resolved),'resolved_sha256':hashlib.sha256(resolved.read_bytes()).hexdigest()}
 try:h.safe_path(value['path'],'file');row['declared_guard']='passed'
 except Exception as e:row['declared_guard']=repr(e)
 h.safe_path(str(resolved),'file');out.append(row)
for key in('git_dir',):h.safe_path(r[key],'directory')
repo=json.loads(Path(r['repository_inventory']['path']).read_text());h.safe_path(repo['root'],'directory')
print(json.dumps({'schema':'orbit-poc-native-installer-actual-paths-v1','request':{'path':str(J/'installation-request.json'),'sha256':hashlib.sha256((J/'installation-request.json').read_bytes()).hexdigest()},'inputs':out,'interpreter':{'sys_executable':sys.executable,'resolved':str(Path(sys.executable).resolve())},'native_commands':0},indent=2))
