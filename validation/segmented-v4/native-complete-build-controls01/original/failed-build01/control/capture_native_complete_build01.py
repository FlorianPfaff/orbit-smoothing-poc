from pathlib import Path
import argparse,base64,datetime,hashlib,json
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args();R=a.root
def pin(p):
 b=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
files=[];external=[]
for directory in (R/'control',R/'run/build-result'):
 if directory.exists():
  for f in sorted(directory.iterdir()):
   if not f.is_file() or f.suffix not in ('.json','.log','.stdout','.stderr','.py'):continue
   item=pin(f)
   if f.name in ('complete-build.stdout','candidate-command-inventory.stdout','candidate-command-inventory.json','candidate-dependency-inventory.stdout','complete-compile-evidence.json'):
    external.append(item)
   else:files.append(dict(item,base64=base64.b64encode(f.read_bytes()).decode()))
for name in ('CMakeCache.txt','build-manifest.json','.ninja_log'):
 f=R/'build'/name
 if f.exists():
  item=pin(f)
  if name=='.ninja_log':external.append(item)
  else:files.append(dict(item,base64=base64.b64encode(f.read_bytes()).decode()))
j=json.loads((R/'control/pipeline.json').read_text());assert j['status']!='running' and j['final_cleanup']['verified']
launch=json.loads((R/'control/native-complete-launch.json').read_text());ids=[launch['driver_process']]
for command in j['final_cleanup']['commands']:ids+=command['identities']
observed=[]
for x in ids:
 proc=Path('/proc')/str(x['pid'])/'stat'
 try:
  q=proc.read_text().rsplit(')',1)[1].split();observed.append(dict(expected=x,current_start_ticks=int(q[19]),state=q[0],live=int(q[19])==x['start_ticks'] and q[0]!='Z'))
 except (FileNotFoundError,ProcessLookupError):observed.append(dict(expected=x,absent=True,live=False))
print(json.dumps({'schema':'orbit-poc-native-complete-build-compact-v1','observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'root':str(R),'files':files,'external':external,'owned_processes':observed,'candidate_object_paths':[str(x.relative_to(R)) for x in (R/'build').rglob('*.o')],'fit_attempts':0},indent=2))
