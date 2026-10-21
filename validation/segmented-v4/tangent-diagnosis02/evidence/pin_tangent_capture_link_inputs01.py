from pathlib import Path
import json,hashlib,importlib.util
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');C=B/'preparation-03/control';s=importlib.util.spec_from_file_location('d',B/'validation-04/control/owned_driver09.py');d=importlib.util.module_from_spec(s);s.loader.exec_module(d);e=json.loads((C/'execution.json').read_text());b=B/'engineering-02/build'
import subprocess
text=subprocess.check_output(['/usr/bin/ninja','-C',str(b),'-t','deps','groops'],text=True);lines=text.splitlines();assert lines[0].startswith('groops: #deps 637,')and'(VALID)'in lines[0]
rows=[]
for name in lines[1:]:
 name=name.strip()
 if not name:continue
 path=name if Path(name).is_absolute()else str(b/name);physical=d.resolved_host_path(path,e);raw=physical.read_bytes();st=physical.stat();rows.append({'path':path,'physical_path':str(physical.resolve()),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'device':st.st_dev,'inode':st.st_ino})
assert len(rows)==637
print(json.dumps({'schema':'orbit-poc-tangent-capture-original-link-inputs-v1','execution':{'path':str(C/'execution.json'),'sha256':hashlib.sha256((C/'execution.json').read_bytes()).hexdigest()},'dependencies':rows,'ninja_dependency_block':text}))
