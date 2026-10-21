from pathlib import Path
import json,hashlib
c=Path('/mnt/d/orbit-segmented-v4/control');b=c.parent
pin=lambda p:dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def read(name):return json.loads((c/name).read_text())
def walk(v):
 if isinstance(v,dict):
  if isinstance(v.get('path'),str)and isinstance(v.get('sha256'),str):yield v
  for item in v.values():yield from walk(item)
 elif isinstance(v,list):
  for item in v:yield from walk(item)
a=read('tangent-rhs-family-run02-independent-terminal-review01.json');pre=read('tangent-rhs-family-preflight03-independent-family-review01.json');old=read('tangent-rhs-family-publication-recipe03.json')
r={k:old[k]for k in ('local_control_root','failed_preflight_audit','baseline_attribution','audit_bindings')}
r.update(schema='orbit-poc-rhs-family-repeat-publication-recipe-v1',output=str(b/'publication-tangent-rhs-family02'),terminal_audit=pin(c/'tangent-rhs-family-run02-independent-terminal-review01.json'),passed_preflight_audit=pin(c/'tangent-rhs-family-preflight03-independent-family-review01.json'),replacement_source_audit=pre['source_review'],previous_terminal_audit=old['terminal_audit'],previous_preflight_audit=old['passed_preflight_audit'],previous_family_manifest=old['family_manifest'])
for key in ('family_manifest','result','run_capture','binary'):r[key]=a[key]
r['raw_captures']=[old['raw_captures'][0],old['raw_captures'][1],dict(label='passed-preflight03',pin=pre['raw_capture']),dict(label='family-run02',pin=a['run_capture'])]
files={};pending=[]
def add(p,expected=None):
 p=Path(p)
 if not p.is_relative_to(c)or not p.is_file()or p.is_symlink()or'__pycache__'in p.parts:return
 record=pin(p)
 if expected and record['sha256']!=expected:return
 if record['path']in files:return
 data=p.read_bytes()
 try:data.decode('utf-8')
 except UnicodeError:return
 if b'\0'in data:return
 files[record['path']]=record
 if p.suffix=='.json':
  try:pending.append(json.loads(data))
  except ValueError:pass
for key in ('terminal_audit','passed_preflight_audit','replacement_source_audit','previous_terminal_audit','previous_preflight_audit','failed_preflight_audit','baseline_attribution'):add(r[key]['path'],r[key]['sha256'])
for item in r['raw_captures']:add(item['pin']['path'],item['pin']['sha256'])
for name in ('tangent-rhs-family-repeat-baseline-attribution01.json','tangent-rhs-family01-publication-independent-review01.json','tangent-rhs-family-presenter06-independent-review01.json','rhs-family-presenter05-author-tests01.log','rhs-family-presenter06-author-tests01.log','rhs-family-presenter07-author-tests01.log','rhs-family-presenter08-author-tests01.log','present_tangent_rhs_family05.py','present_tangent_rhs_family06.py','present_tangent_rhs_family07.py','present_tangent_rhs_family08.py','test_present_tangent_rhs_family05.py','test_present_tangent_rhs_family06.py','test_present_tangent_rhs_family07.py','test_present_tangent_rhs_family08.py','prepare_rhs_repeat02_publication_recipe01.py'):
 add(c/name)
for p in sorted((c/'tangent-wide-candidate03').rglob('*')):add(p)
while pending:
 for ref in walk(pending.pop()):add(ref['path'],ref['sha256'])
r['local_files']=sorted(files.values(),key=lambda x:x['path'])
out=c/'tangent-rhs-family-repeat02-publication-recipe01.json';out.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(recipe=pin(out),local_count=len(files)),indent=2))
