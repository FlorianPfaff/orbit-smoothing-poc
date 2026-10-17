from pathlib import Path
import argparse,json,hashlib,base64,datetime
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args();R=a.root

def pin(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}
files=[]
for directory in (R/'control',R/'run/preflight',R/'native_source/reproduction'):
 if directory.exists():
  for f in sorted(directory.iterdir()):
   if f.is_file() and f.suffix in('.json','.log','.stdout','.stderr','.py'):
    files.append(dict(pin(f),base64=base64.b64encode(f.read_bytes()).decode()))
j=json.loads((R/'control/pipeline.json').read_text());assert j['status']!='running'and j['final_cleanup']['verified'];launch=json.loads((R/'control/native-complete-launch.json').read_text());ids=[launch['driver_process']]
for command in j['final_cleanup']['commands']:ids+=command['identities']
observed=[]
for x in ids:
 p=Path('/proc')/str(x['pid'])/'stat'
 try:
  q=p.read_text().rsplit(')',1)[1].split();observed.append(dict(expected=x,current_start_ticks=int(q[19]),state=q[0],live=int(q[19])==x['start_ticks']and q[0]!='Z'))
 except(FileNotFoundError,ProcessLookupError):observed.append(dict(expected=x,absent=True,live=False))
print(json.dumps({'schema':'orbit-poc-native-complete-preflight-compact-v1','observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'root':str(R),'files':files,'owned_processes':observed,'candidate_build_files':[str(x.relative_to(R))for x in(R/'build').rglob('*')if x.is_file()],'fit_attempts':0},indent=2))
