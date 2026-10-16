from pathlib import Path
import json,importlib.util
I=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/native-complete-inputs-01');sp=importlib.util.spec_from_file_location('u',I/'build_native_source_delta01.py');u=importlib.util.module_from_spec(sp);sp.loader.exec_module(u)
rows=json.loads((I/'link-inventory.json').read_text())['inputs'];different=[];actual=[]
for row in rows:
 now=u.file_identity(row['path']);actual.append(now)
 if now!=row:different.append({'declared':row,'actual':now,'fields':[k for k in row if row[k]!=now[k]]})
deps=json.loads((I/'dependency-inventory.json').read_text());actual_deps=[u.file_identity(row['path']) for row in deps['files']]
print(json.dumps({'schema':'orbit-poc-native-namespace-identities-v1','link_inventory':u.source_digest(rows),'count':len(rows),'different':different,'actual_links':actual,'actual_dependencies':actual_deps,'dependency_differences':[{'declared':old,'actual':new,'fields':[k for k in old if old[k]!=new[k]]}for old,new in zip(deps['files'],actual_deps)if old!=new],'native_commands':0},indent=2))
