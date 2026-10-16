from pathlib import Path
import datetime,hashlib,html,json
C=Path('/mnt/d/orbit-segmented-v4/control');O=C.parent/'publication-preparation04-startup01-failure01'
def pin(p):b=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,sort_keys=True,indent=2)+'\n')
r=C/'preparation04-startup01-failure-readback01.json';assert pin(r)['sha256']=='f29a1ee09bd070024e6a68a6bf72b6466a0dc4c38aa2d211df5ed2c605a4a278';v=json.loads(r.read_bytes());assert len(v['files'])==13
assert not O.exists();O.mkdir();copies=[];documents={}
for i,item in enumerate(v['files']):
 b=item['text'].encode();assert len(b)==item['bytes'] and hashlib.sha256(b).hexdigest()==item['sha256']
 source=Path(item['path']);relative=Path('evidence')/(str(i+1).zfill(2)+'-'+source.name);p=O/relative;p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('xb') as f:f.write(b)
 copies.append({'path':str(relative),'sha256':item['sha256'],'bytes':item['bytes'],'original':{k:item[k] for k in ('path','sha256','bytes')}})
 if source.suffix=='.json':documents[item['path']]=json.loads(b)
for source,name in [(r,r.name),(Path(__file__),Path(__file__).name)]:
 p=O/'evidence'/name;p.write_bytes(source.read_bytes());copies.append({'path':str(p.relative_to(O)),**{k:z for k,z in pin(p).items() if k!='path'},'original':pin(source)})
B='/mnt/seagate10tb/orbit-segmented-v4-florianpfaff'
pipeline=documents[B+'/validation05-continuation-01/control/pipeline.json'];probe=documents[B+'/validation-05/staging/preparation-04/startup-01/temporary/probe-result/result.json'];process=documents[B+'/validation-05/staging/preparation-04/startup-01/process.json']
assert pipeline['status']=='failed' and pipeline['finished_at']=='2026-10-16T08:52:43.105580+00:00' and pipeline['final_cleanup']['verified'] is True
assert probe['status']=='failed' and probe['benchmark_fits']==probe['physical_propagations']==0
assert '/validation05-continuation-01/control/.tudat/resource/quadrature/gaussianNodes.txt' in probe['error']
assert v['prep_launch_exists'] is v['prep_pipeline_exists'] is False and not any(v['public_output_markers'].values())
assert all(p.get('absent') is True for p in v['tracked_processes'].values())
summary={'schema':'orbit-poc-preparation04-startup01-failure-publication-v1','failure_finished_at':pipeline['finished_at'],'readback_observed_at':v['observed_at'],'status':'failed_before_generation','error':probe['error'],'physical_propagations':0,'benchmark_fits':0,'release_ready':False,'validation05_terminal_audit':pipeline['independent_audit'],'preserved_controller':pipeline['validation_controller'],'cleanup_verified':True,'current_readback_process_absence':v['tracked_processes'],'public_output_absence':v['public_output_markers'],'scope':'Actual first preparation04 startup failure only. Validation05 had already passed its separate14-stage audit. This failure does not invalidate that dated validation, nor does it claim preparation or a subsequent restart succeeded. No new numerical execution or data acquisition occurs in this publication.','resource_resolution':{'host_account':v['host_account'],'read_only_bindings':v['tudat_bindings'],'failed_lookup':B+'/validation05-continuation-01/control/.tudat/resource/quadrature/gaussianNodes.txt'},'sources':copies}
write(O/'summary.json',summary)
(O/'index.html').write_text('''<!doctype html><meta charset="utf-8"><title>Preparation04 startup01: preserved dependency failure</title><style>body{font:16px system-ui;max-width:1000px;margin:3em auto;padding:0 1em;line-height:1.5}code{overflow-wrap:anywhere}</style><h1>Preparation04 startup01 failed before generation</h1><p>The first preparation startup failed at08:52:43UTC on October16,2026. Tudat attempted to read <code>'''+html.escape(summary['resource_resolution']['failed_lookup'])+'''</code>, although the frozen resource binding was under the account home <code>/home/florianpfaff/.tudat/resource</code>. The inherited HOME therefore resolved the resource path to the continuation control directory.</p><p>The probe recorded zero physical propagations and zero benchmark fits. The continuation preserved its failure and verified owned-process cleanup. A separate read-only observation at14:56:17UTC found the tracked processes absent, no preparation launch/pipeline, and no public preparation or attempt outputs.</p><p>Validation05 had already completed and passed its independent14-stage audit. These are separate outcomes: the startup failure is not a failed scientific validation, and the passed validation is not a successful preparation. The copied13 records are exact original bytes; the raw readback and publication helper are also preserved. A later corrected startup or launch requires its own actual receipts and is outside this dated package.</p><p><a href="summary.json">Machine-readable failure</a> · <a href="manifest.json">Exact evidence inventory</a> · <a href="../validation05/index.html">Separate validation05 report</a></p></html>''')
files=[{'path':str(p.relative_to(O)),**{k:z for k,z in pin(p).items() if k!='path'}} for p in sorted(O.rglob('*')) if p.is_file()]
write(O/'manifest.json',{'schema':'orbit-poc-compact-failure-publication-manifest-v1','files':files,'file_count':len(files),'bytes':sum(x['bytes'] for x in files),'scope':'Preserved preparation startup failure; no execution or readiness promotion.'})
print(json.dumps({'manifest':pin(O/'manifest.json'),'files':len(files),'bytes':sum(x['bytes'] for x in files)}))
