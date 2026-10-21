from pathlib import Path
import argparse,base64,datetime,hashlib,json
ap=argparse.ArgumentParser();ap.add_argument('--root',required=True,choices=('tangent-complete-supplemental-01','tangent-complete-single-01','tangent-complete-single-02','tangent-complete-closure-01','tangent-complete-closure-02'));a=ap.parse_args()
D=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff')/a.root;C=D/'control';R=D/'run/replay'
pipeline=json.loads((C/'pipeline.json').read_text());assert pipeline.get('finished_at')and pipeline['final_cleanup']['verified'];assert pipeline['status']in('passed_diagnostic','failed_diagnostic','failed')
launch_name='native-supplemental'if a.root=='tangent-complete-supplemental-01'else('native-single'if '-single-'in a.root else'native-closure')
names=['control/plan.json','control/execution.json','control/staging.json','control/'+launch_name+'-launch.json','control/pipeline.json','control/native-replay.log','control/'+launch_name+'-driver.log']
files=[];external=[]
for p in sorted(R.rglob('*')):
 if not p.is_file():continue
 if p.suffix in('.json','.xml','.log'):names.append(str(p.relative_to(D)))
 else:external.append({'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size})
for name in names:
 p=D/name;b=p.read_bytes();assert len(b)<3000000
 files.append({'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b),'base64':base64.b64encode(b).decode()})
identities={x['pid']:x for command in pipeline['final_cleanup']['commands']for x in command['identities']};launch=json.loads((C/(launch_name+'-launch.json')).read_text());identities[launch['driver_process']['pid']]=launch['driver_process'];checks=[]
for pid,ident in identities.items():
 try:parts=(Path('/proc')/str(pid)/'stat').read_text().rsplit(')',1)[1].split();live=int(parts[19])==ident['start_ticks']and parts[0]not in('Z','X')
 except(FileNotFoundError,ProcessLookupError):live=False
 checks.append({'pid':pid,'start_ticks':ident['start_ticks'],'live':live})
assert not any(x['live']for x in checks)
print(json.dumps({'schema':'orbit-poc-native-complete-check-terminal-v1','root':a.root,'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'files':files,'external_arrays_and_binaries':external,'owned':checks,'fit_attempts':0,'release_evidence':False},indent=2))
