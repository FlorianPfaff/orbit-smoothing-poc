from pathlib import Path
import json,hashlib,importlib.util,datetime,socket
R=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/shifted-diagnostic-01')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert sha(R/'control/execution.json')=='49d7ecfcf33cf1d413fe187926217451384f9b9a6faf0e401b2983a978adba3c'
assert sha(R/'control/plan.json')=='7e8a00946a84a5fceb29e75dc802b13710d70e31ce7faddf24966358272ee031'
p=json.loads((R/'control/plan.json').read_text());e=json.loads((R/'control/execution.json').read_text())
for k in ('driver','runner','diagnostic','runtime_checker','solver','source_freeze','controller','pipeline','config','execution'):assert sha(p[k]['path'])==p[k]['sha256'],k
assert p['driver']['sha256']=='72ac591a4c0b1d18b67b2739d694be40e271ec09d7b0f9b3dcad4287cb88fdcd'
spec=importlib.util.spec_from_file_location('d',p['driver']['path']);d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
source=d.source_receipt(Path(e['paths']['source']));freeze=json.loads(Path(p['source_freeze']['path']).read_text());assert source==freeze['source'] and len(source['files'])==384
runtime={}
for key,pin in e['runtime_artifacts'].items():
 resolved=d.resolved_host_path(pin['path'],e);h=sha(resolved);assert h==pin['sha256'],key;runtime[key]={'path':pin['path'],'resolved':str(resolved),'sha256':h}
for key,pin in p['validations'].items():assert sha(pin['path'])==pin['sha256']
absent={k:not Path(e['paths'][k]).exists() and not Path(e['paths'][k]).is_symlink() for k in ['native_source','build','binaries','run','temporary']};assert all(absent.values())
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();assert boot==e['host']['boot_id'] and socket.gethostname()==e['host']['hostname']
print(json.dumps({'schema':'orbit-poc-shifted-independent-actual-static-verification-v1','passed':True,'observed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'host':e['host'],'source_sha256':source['sha256'],'source_file_count':len(source['files']),'runtime_pins':runtime,'production_outputs_absent':absent,'scope':'Read-only source, actual host path and frozen plan/runtime identity checks; no native workload or idle-host admission while owned smoke may run.'},sort_keys=True,indent=2))
