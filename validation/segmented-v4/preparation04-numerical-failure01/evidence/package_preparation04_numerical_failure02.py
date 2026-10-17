from pathlib import Path
import json,hashlib,re,base64
B=Path('/mnt/d/orbit-segmented-v4');C=B/'control';O=B/'publication-preparation04-numerical-failure02'
def digest(b):return hashlib.sha256(b).hexdigest()
def pin(p):
 b=p.read_bytes();return {'path':str(p),'sha256':digest(b),'bytes':len(b)}
source=C/'preparation04-numerical-failure-readback01.json';b=source.read_bytes()
assert digest(b)=='94cae4290dbd3cbf7224cb503c4362df68eaa0c5509bb351fc1b3fd09822f4ec'
d=json.loads(b)
rawpath=C/'preparation04-numerical-failure-rawlogs-root-readback01.json'
assert pin(rawpath)['sha256']=='ea50014404ab16d056a1311ee3afa816075ec6a13093a9dc525aa6face04c41e'
raw={x['path']:x for x in json.loads(rawpath.read_text())['files']};assert len(raw)==4
O.mkdir(exist_ok=False);rows=[]
def put(rel,b,original=None,attribution=None):
 p=O/rel;p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('xb') as f:f.write(b)
 r={'path':rel,'sha256':digest(b),'bytes':len(b)}
 if original:r['original']=original
 if attribution:r['attribution']=attribution
 rows.append(r)
def js(rel,v):put(rel,(json.dumps(v,indent=2)+'\n').encode())
for p in [source,C/'preparation04-home-launch02-progress02.json',rawpath,C/'preparation04-numerical-failure-raw-logs01.json',C/'preparation04-numerical-failure-raw-logs01.stderr.log',C/'read_preparation04_raw_logs01.py',C/'preparation04-numerical-failure-publication01-copy-rejection.json',C/'package_preparation04_numerical_failure01.py',Path(__file__)]:put('evidence/'+p.name,p.read_bytes(),pin(p),'Exact local evidence bytes; embedded remote records retain original source attribution.')
original={};external={}
for i,f in enumerate(d['files'],1):
 orig={k:f[k] for k in ('path','sha256','bytes')}
 if 'text' in f:
  data=f['text'].encode()
  if f['path'] in raw:
   x=raw[f['path']];assert all(x[k]==orig[k]for k in orig);data=base64.b64decode(x['base64'],validate=True)
  assert len(data)==f['bytes'] and digest(data)==f['sha256'];name=f'original/{i:02d}-{Path(f["path"]).name}'
  put(name,data,orig,('Exact original bytes decoded from the root base64 log readback; original normalized-text readback and failed copy attempt preserved.' if f['path'] in raw else 'Exact original bytes decoded from the sealed remote readback; no new read.'));original[f['path']]={'pin':orig,'copy':name,'text':f['text']}
 else:external[f['path']]=orig
for x in d['external_arrays']+[v['record'] for v in d['components']]:
 if x['path'] not in original:external[x['path']]={k:x[k]for k in ('path','sha256','bytes')}
assert len(original)==21
pipeline=json.loads(next(x['text']for x in d['files']if x['path'].endswith('/control/pipeline.json')))
init=json.loads(next(x['text']for x in d['files']if x['path'].endswith('/initialization.json')))
log=next(x['text']for x in d['files']if x['path'].endswith('/iteration-03/propagate.log'))
assert 'relative_residual=5.2053902058798312e-12, tolerance=2e-12, iterations=120' in log
assert len(init['iterations'])==2 and all(x['returncode']==0 for x in init['executions'][:3]) and init['executions'][3]['returncode']==1
assert pipeline['status']=='failed_or_blocked' and pipeline['final_cleanup']['verified'] and not any(x['live_owned_processes']for x in pipeline['final_cleanup']['commands'])
assert all(x.get('absent') or x.get('state')=='Z' for x in d['current_owned_identities'])
completed=[x for x in d['components']if x['status']=='prepared'];assert len(completed)==7
assert sum(x['name'].startswith('prefix-')for x in completed)==5
assert d['benchmark_fits']==0
summary={'schema':'orbit-poc-v4-preparation04-numerical-failure-publication-v1','observed_at':d['observed_at'],'terminal_status':pipeline['status'],'finished_at':pipeline['finished_at'],'case':d['case'],'native':d['native'],'completed_generation_components':2,'completed_unique_prefixes':5,'failed_prefix':'753992c25b8ee35f52468f0d4439501f642bc531685eecd44942eac438ba7769','failed_operation':'Third nominal initialization propagation; inner physical-correction tangent solve','inner_relative_residual':5.2053902058798312e-12,'required_relative_residual':2e-12,'inner_iterations':120,'rhs_norm':4.8014353984884544e-6,'solution_norm':0.0076587054185056243,'epochs':51840,'first_two_nominal_propagations':'returned successfully but did not yet satisfy outer closure','initialization_converged':False,'outer_iterations_before_failure':init['iterations'],'outer_position_tolerance_m':init['position_tolerance_m'],'outer_velocity_tolerance_m_s':init['velocity_tolerance_m_s'],'native_timed_out':init['executions'][-1]['timed_out'],'final_cleanup_verified':True,'current_owned_identities_nonlive':len(d['current_owned_identities']),'benchmark_fits':0,'planned_benchmark_fits':68,'release_ready':False,'numerical_cause':'Unresolved; the log establishes failure of the unchanged true-residual guard, not a numerical-floor explanation.','scope':['Correct-HOME startup and actual launch succeeded, then preparation stopped on a different numerical failure; their dated evidence remains valid and unchanged.','The earlier 14-stage validation05 pass remains a bounded correctness result. It does not certify this unfinished 72-hour preparation or a fitted orbit.','No threshold relaxation, retry, correction, covariance or fit success is represented by this publication.','This package records the actual terminal failure from sealed controls; any subsequent independent terminal audit is a separate adjacent receipt.'],'source':pin(source),'prior_recovery_manifest':pin(B/'publication-preparation04-recovery02-01/manifest.json')}
js('summary.json',summary)
js('external-evidence.json',{'schema':'orbit-poc-external-evidence-inventory-v1','records':[dict(v,availability='external_not_copied_by_this_publication')for v in external.values()],'scope':'Only exact pins supplied in the sealed readback; no additional array or input rescan. Four small native logs were transferred as raw base64 to preserve original CR/LF bytes.'})
put('index.html',('''<!doctype html><html lang="en"><meta charset="utf-8"><title>Preparation04 numerical failure</title><style>body{font:16px system-ui;max-width:900px;margin:3rem auto;line-height:1.5}code{word-break:break-all}li{margin:.5rem 0}</style><h1>Preparation04 stopped on a numerical failure</h1><p>The corrected-HOME startup and preparation launch succeeded. Preparation then terminated at <strong>15:21:08 UTC on 16 October 2026</strong> after two continuous truth generations and five unique observation prefixes completed.</p><p>The 500 km disturbed/blackout 72-hour pulse prefix failed during its third nominal propagation. The corrected <code>eb41fabb…</code> executable reported true relative tangent residual <strong>5.2053902058798312e-12</strong>, above the unchanged <strong>2e-12</strong> limit after 120 inner iterations. The first two propagations returned successfully but had not reached outer trajectory closure.</p><p>The right-hand-side norm was 4.8014353984884544e-6; this recorded scale does not establish a numerical-floor cause. The underlying reason remains under diagnosis. Native timeout was false, and owned cleanup was verified.</p><p><strong>0/68 benchmark fits; no prepared benchmark manifest, accepted covariance or release readiness is claimed.</strong> The earlier all-14 validation05 pass and dated startup/launch evidence remain separate bounded results.</p><ul><li><a href="summary.json">Measured failure, completed components and exact identities</a></li><li><a href="original/23-propagate.log">Exact third-propagation failure log</a></li><li><a href="original/14-initialization.json">Exact initialization record and first two closure changes</a></li><li><a href="evidence/preparation04-numerical-failure-readback01.json">Sealed actual terminal readback and process observation</a></li><li><a href="external-evidence.json">External trajectory, request and execution pins</a></li><li><a href="manifest.json">Complete publication manifest and original-byte attribution</a></li></ul><p>Twenty-one original compact records are copied exactly. Bulky arrays and execution/request inventories remain external. The first publication copy guard rejected four normalized log strings; exact CR/LF bytes were then transferred for those four small logs only. Both narrow raw-log receipts and the rejected copy record are preserved. No native rerun or additional scientific check was performed to build this publication.</p></html>''').encode())
m={'schema':'orbit-poc-compact-publication-manifest-v1','files':rows,'file_count':len(rows),'total_bytes':sum(x['bytes']for x in rows),'scope':'Actual preparation04 numerical failure, no release or fit claim.'};(O/'manifest.json').write_text(json.dumps(m,indent=2)+'\n');print(json.dumps({'output':str(O),'manifest':pin(O/'manifest.json'),'file_count':len(rows),'total_bytes':m['total_bytes'],'copied_original_records':len(original),'external_records':len(external)},indent=2))
