from pathlib import Path
import hashlib,importlib.util,json,os
D=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/native-complete-build-02');C=D/'control';e=json.loads((C/'execution.json').read_text());p=json.loads((C/'plan.json').read_text());tool=json.loads(Path(p['inputs']['toolchain']['path']).read_text());spec=importlib.util.spec_from_file_location('d',C/'owned_driver09.py');d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
rows=[]
for label,path in [('execution_python',e['paths']['python']),('toolchain_python',tool['python']['path'])]:
 physical=d.resolved_host_path(path,e);s=physical.stat();rows.append({'label':label,'canonical':path,'physical':str(physical),'resolved':str(physical.resolve()),'sha256':hashlib.sha256(physical.read_bytes()).hexdigest(),'device':s.st_dev,'inode':s.st_ino,'bytes':s.st_size,'symlink':physical.is_symlink(),'linktext':os.readlink(physical)if physical.is_symlink()else None})
print(json.dumps({'execution_python_pin':e['runtime_artifacts']['python'],'toolchain_python_pin':tool['python'],'rows':rows,'same_inode':rows[0]['device']==rows[1]['device']and rows[0]['inode']==rows[1]['inode'],'same_bytes':rows[0]['sha256']==rows[1]['sha256']},indent=2))
