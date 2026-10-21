"""Pins existing exact evidence only; does not present or execute diagnostics."""
from pathlib import Path
import hashlib,json
C=Path('/mnt/d/orbit-segmented-v4/control');B=C.parent

def pin(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def load(n):return json.loads((C/n).read_bytes())
def walk(v):
 if isinstance(v,dict):
  if isinstance(v.get('path'),str)and isinstance(v.get('sha256'),str):yield v
  for x in v.values():yield from walk(x)
 elif isinstance(v,list):
  for x in v:yield from walk(x)
actual=load('tangent-rhs-family-run01-independent-terminal-review01.json')
assert pin(C/'tangent-rhs-family-run01-independent-terminal-review01.json')['sha256']=='192962a052de5e06b754daaa84932a5804a1f585ebead7bf9415b8e55c851d45'
failed=load('tangent-rhs-family01-independent-terminal-review01.json');passed=load('tangent-rhs-family-preflight02-independent-family-review01.json')
assert actual['passed']and actual['recorded_calls']==actual['planned_calls']==54
names=['tangent-rhs-family-run01-independent-terminal-review01.json','tangent-rhs-family01-independent-terminal-review01.json','tangent-rhs-family-preflight02-independent-family-review01.json','tangent-wide-candidate02-independent-source-review01.json','tangent-rhs-family-run01-independent-packet-review01.json','tangent-rhs-family-run01-independent-live-review01.json','tangent-rhs-family-run01-baseline-comparison01.json','analyze_rhs_family_baseline01.py','tangent-rhs-family01-independent-control-review01.json','tangent-rhs-family02-independent-control-review01.json','tangent-rhs-family01-author-tests01.log','tangent-rhs-family01-author-tests02.log','tangent-rhs-family01-author-tests03.log','tangent-rhs-family01-author-validation01.json','test_tangent_rhs_family01-failed-fixture.py','replay_tangent_rhs_family01-draft.py','rhs-family-presenter-author-history01.json',Path(__file__).name]
for i in range(1,5):
 names += [f'present_tangent_rhs_family0{i}.py',f'test_present_tangent_rhs_family0{i}.py',f'rhs-family-presenter0{i}-author-tests01.log']
files={C/n for n in names};historical_mismatches=[]
for d in ['tangent-wide-candidate01','tangent-wide-candidate02']:
 for p in(C/d).rglob('*'):
  if p.is_file()and'__pycache__'not in p.parts and p.suffix in {'.py','.cpp','.h','.json','.log'}:files.add(p)
pending=list(files)
while pending:
 p=pending.pop();assert p.is_file()and not p.is_symlink(),str(p)
 data=p.read_bytes();data.decode();assert b'\0'not in data
 if p.suffix!='.json':continue
 value=json.loads(data)
 for r in walk(value):
  q=Path(r['path'])
  if q.is_absolute()and q.is_relative_to(C)and q.is_file()and not q.is_symlink()and q.stat().st_size<1500000 and q.suffix not in {'.gz','.tar','.bin','.so','.pyc'}:
   b=q.read_bytes()
   if hashlib.sha256(b).hexdigest()!=r['sha256']:
    historical_mismatches.append({'referenced_in':pin(p),'historical_pin':r,'current_local_file':pin(q),'disposition':'Historical pin retained as external; current bytes are not substituted for the earlier version.'})
    continue
   if 'bytes'in r:assert len(b)==r['bytes']
   try:b.decode()
   except UnicodeDecodeError:continue
   if b'\0'in b:continue
   if q not in files:files.add(q);pending.append(q)
history=C/'rhs-family-publication-recipe-history02.json'
with history.open('x')as f:json.dump({'schema':'orbit-poc-publication-history-resolution-v1','earlier_recipe_author':pin(C/'prepare_rhs_family_publication_recipe01.py'),'earlier_outcome':'Stopped before recipe creation on mismatched historical stage_tangent_rhs_family02.py pin; traceback was observed in tool output, not saved as a raw stderr artifact. No publication output created.','unavailable_historical_bytes':historical_mismatches,'scope':'Preserved original audit references are not changed or replaced with later local bytes.'},f,indent=2);f.write('\n')
files.add(history)
recipe={'schema':'orbit-poc-rhs-family-publication-recipe-v1','local_control_root':str(C),'output':str(B/'publication-tangent-rhs-family01'),
 'terminal_audit':pin(C/'tangent-rhs-family-run01-independent-terminal-review01.json'),
 'failed_preflight_audit':pin(C/'tangent-rhs-family01-independent-terminal-review01.json'),
 'passed_preflight_audit':pin(C/'tangent-rhs-family-preflight02-independent-family-review01.json'),
 'replacement_source_audit':passed['source_review'],
 'raw_captures':[{'label':'failed-preflight01','pin':failed['capture']},{'label':'passed-preflight02','pin':passed['raw_capture']},{'label':'family-run01','pin':actual['run_capture']}],
 'baseline_attribution':pin(C/'tangent-rhs-family-baseline-attribution01.json'),
 'local_files':[pin(p)for p in sorted(files)],
 'audit_bindings':{k:[k]for k in ['family_manifest','result','run_capture','binary','planned_calls','recorded_calls']},
 **{k:actual[k]for k in ['family_manifest','result','run_capture','binary']}}
path=C/'tangent-rhs-family-publication-recipe02.json'
with path.open('x')as f:json.dump(recipe,f,indent=2);f.write('\n')
print(json.dumps({'recipe':pin(path),'local_pinned_files':len(files),'scope':'Actual audited first54 diagnostic calls; later candidate03 excluded. Presentation not executed.'},indent=2))
