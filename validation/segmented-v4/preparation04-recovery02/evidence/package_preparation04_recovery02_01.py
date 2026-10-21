from pathlib import Path
import hashlib, json, html
B=Path('/mnt/d/orbit-segmented-v4'); C=B/'control'; O=B/'publication-preparation04-recovery02-01'
def digest(b): return hashlib.sha256(b).hexdigest()
def pin(p):
 b=p.read_bytes(); return {'path':str(p),'sha256':digest(b),'bytes':len(b)}
def load(n): return json.loads((C/n).read_text())
O.mkdir(exist_ok=False)
rows=[]
def put(rel,b,original=None,attribution=None):
 p=O/rel;p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('xb') as f:f.write(b)
 row={'path':rel,'sha256':digest(b),'bytes':len(b)}
 if original:row['original']=original
 if attribution:row['attribution']=attribution
 rows.append(row)
def js(rel,v):put(rel,(json.dumps(v,indent=2)+'\n').encode())
names=[
'recover_preparation04_startup03.py','test_preparation04_home_recovery03.py',
'recover_preparation04_startup02.py','test_preparation04_home_recovery02.py',
'preparation04-home-recovery03-author-tests01.log',
'preparation04-home-recovery03-independent-tests01.log','preparation04-home-recovery03-independent-tests01.xml',
'preparation04-home-recovery02-independent-code-review01.json',
'preparation04-home-recovery02-independent-tests01.log','preparation04-home-recovery02-independent-tests01.xml',
'preparation04-home-recovery02-author-tests01.log','preparation04-home-recovery02-author-tests02.log',
'preparation04-home-recovery03-independent-packet-review01.json',
'preparation04-home-recovery03-staging.json','preparation04-home-recovery03-own-check01.json','preparation04-home-recovery03-own-check01.stderr.log',
'preparation04-home-recovery02-staging.json','preparation04-home-recovery02-staging02.json',
'preparation04-home-recovery-packet-independent-readback03.json','preparation04-home-recovery-packet-independent-readback03.stderr.log',
'audit_preparation04_home_recovery_packet01.py','audit_preparation04_home_recovery_packet02.py','audit_preparation04_home_recovery_packet03.py',
'preparation04-home-recovery-preflight-failures01.json',
'preparation04-home-startup02-independent-review01.json','preparation04-home-startup02-independent-readback02.json',
'preparation04-home-startup02-independent-readback02.stderr.log','preparation04-home-startup02-independent-readback01.json','preparation04-home-startup02-independent-readback01.stderr.log',
'audit_preparation04_home_startup02.py','audit_preparation04_home_startup02_02.py',
'preparation04-home-launch-independent-review01.json','preparation04-home-launch-independent-readback01.json','preparation04-home-launch-independent-readback01.stderr.log','audit_preparation04_home_launch01.py',
]
for p in load('preparation04-home-recovery-preflight-failures01.json')['records']:
 src=Path(p['path']);assert pin(src)==p;names.append(src.name)
names.append(Path(__file__).name)
for n in dict.fromkeys(names):
 p=C/n;put('evidence/'+n,p.read_bytes(),pin(p),'Exact local evidence bytes; embedded remote records retain their original attribution.')
for name,category in [('preparation04-home-startup02-independent-readback02.json','startup'),('preparation04-home-launch-independent-readback01.json','launch')]:
 doc=load(name)
 for i,f in enumerate(doc['files'],1):
  data=f['text'].encode();assert digest(data)==f['sha256'] and len(data)==f['bytes']
  put(f'original/{category}-{i:02d}-{Path(f["path"]).name}',data,{k:f[k] for k in ('path','sha256','bytes')},'Exact original remote bytes decoded from the pinned independent readback; no new remote read.')
launch=load('preparation04-home-launch-independent-review01.json'); startup=load('preparation04-home-startup02-independent-review01.json'); packet=load('preparation04-home-recovery03-independent-packet-review01.json')
assert all(x['passed'] for x in (launch,startup,packet))
prior=B/'publication-preparation04-startup01-failure01'/'manifest.json'
summary={'schema':'orbit-poc-v4-preparation04-recovery-publication-v1','status':'launched_and_running_at_observation','observed_at':launch['observed_at'],'durable_launch_at':'2026-10-16T15:11:32+00:00','source_of_observation':pin(C/'preparation04-home-launch-independent-review01.json'),'startup_audit':pin(C/'preparation04-home-startup02-independent-review01.json'),'packet_audit':pin(C/'preparation04-home-recovery03-independent-packet-review01.json'),'process':launch['process'],'actual_environment':launch['actual_environment'],'before_check':'complete','public_preparation_pid':2675490,'benchmark_fits':0,'planned_benchmark_fits':68,'preparation_complete':False,'release_ready':False,'prior_startup_failure_manifest':pin(prior),'scope':['The control-only recovery supplies the actual account HOME to startup and preparation; scientific source, native executables, settings and numerical thresholds are unchanged.','The final recovery helper passed 27 independent pure tests. The actual startup passed with owned cleanup and zero physical propagations or fits.','The durable driver and running public preparation were independently attributed to exact PID/start/boot and the original shared lock at the observation time. This snapshot does not imply ongoing status after that time.','Both preflight failures and the reviewer lookup failure remain separately preserved. They occurred in control or readback tooling, not scientific fitting.','The earlier wrong-HOME startup01 failure is preserved in its separate immutable package; validation05 results are separate. No preparation completion or benchmark result is inferred.']}
js('summary.json',summary)
put('index.html',('''<!doctype html><html lang="en"><meta charset="utf-8"><title>Preparation04 recovered startup and launch</title><style>body{font:16px system-ui;max-width:900px;margin:3rem auto;line-height:1.5}code{word-break:break-all}li{margin:.5rem 0}</style><h1>Preparation04 restarted with the correct HOME</h1><p>The recovered startup passed, and preparation launched at <strong>15:11:32 UTC on 16 October 2026</strong>. Independent observation at <strong>15:12:31 UTC</strong> verified the owned driver, completed before-check and running public preparation.</p><p>Driver PID2675192 (start114711538); public preparation PID2675490; HOME <code>/home/florianpfaff</code>. The original shared lock and current host identities were verified. The snapshot establishes running preparation at that time only.</p><p><strong>0/68 benchmark fits; preparation completion and release readiness are not claimed.</strong> No scientific source, native executable, physics, prior, weight or numerical threshold changed in this recovery.</p><ul><li><a href="evidence/preparation04-home-recovery03-independent-packet-review01.json">Final recovery packet and 27-test independent review</a></li><li><a href="evidence/preparation04-home-startup02-independent-review01.json">Actual startup and cleanup audit</a></li><li><a href="evidence/preparation04-home-launch-independent-review01.json">Actual durable launch and live ownership audit</a></li><li><a href="evidence/preparation04-home-recovery-preflight-failures01.json">Preserved preflight failures</a>: canonical interpreter symlink and exact absent dense-solver sentinel. Neither launched startup or propagation.</li><li>The startup reviewer first queried an absent success-result field; that read-only tooling failure and corrected exact-attribution audit are preserved separately.</li></ul><p>The original wrong-HOME startup01 failure remains in its separate immutable package, pinned in <a href="summary.json">summary.json</a>. Passed validation05 and its numerical audit remain separate evidence.</p><p><a href="manifest.json">Complete file and original-source manifest</a></p></html>''').encode())
manifest={'schema':'orbit-poc-compact-publication-manifest-v1','scope':'Dated preparation04 startup recovery and live handoff, not completed preparation or fitting.','files':rows,'file_count':len(rows),'total_bytes':sum(x['bytes'] for x in rows)}
(O/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'output':str(O),'manifest':pin(O/'manifest.json'),'file_count':len(rows),'total_bytes':manifest['total_bytes']},indent=2))
