"""Preserve and publish the separately reviewed analysis04 attribution appendix."""
from pathlib import Path
import json,gzip,hashlib,html,importlib.util
B=Path('@LOCAL_DATA_ROOT@/orbit-numerics-v3.1/correctness');C=B/'control';R=C/'d03-analysis-result-04/independent-analysis-04';O=B/'publication-source/validation/numerics-v3.1-correctness/recovery08-diagnostic-d03-analysis04';P=B/'preserved-row-trace-d03-analysis04'
def sha(b):return hashlib.sha256(b).hexdigest()
def enc(x):return (json.dumps(x,indent=2,sort_keys=True)+'\n').encode()
assert not O.exists() and not P.exists()
pins={'result.json':'0d8f32c7bb1729d5507515f7bc47bd6000ef297cfc39fb111646ac36d567da1e','receipt.json':'f65c9a94eb545b75377499f011db4b72172f4fec9466f1483e0fe3cc1c3bdfc9'}
raws={}
for p in sorted(R.iterdir()):
 assert p.is_file() and p.stat().st_size<16*1024*1024
 raw=p.read_bytes();assert p.name not in pins or sha(raw)==pins[p.name];raws['analysis-attempt04/'+p.name]=raw
extras={'d03-analysis04-attribution-review-01.json':'ccb45608af591fa6b5f1d0d962317801b40bd4740d98b00c4862ec9cba7d6a98','d03-exact-geometry-independent-result-review-01.json':'2c89d6a9976f93f4bea2d5a9923829719611fc8a8e1c5c2d2df5f2619ce780c3','row-trace-d03-analyzer-independent-review-03.json':'0feb62ed8cc1f3e9006a23f7412b90334fea0c5c87ef3754580b08b3a07bb29e','d03-analysis-invocation-04.json':'866db1cdbe0afd44b0dffb2846e5eddbc3cc65696b06993e02e7261e3293bad9','launch_d03_independent_analysis04.py':'4b46fd086942189aa0414e5bf0601755028d7be2add78895197eedf9d4e5bfd5'}
for n,pin in extras.items():
 raw=(C/n).read_bytes();assert sha(raw)==pin;raws['reviews/'+n]=raw
review=json.loads((C/'row-trace-d03-analyzer-independent-review-03.json').read_text())
for label in ['junit']:
 p=Path(review[label]['path']);raw=p.read_bytes();assert sha(raw)==review[label]['sha256'];raws['reviews/independent-tests.xml']=raw
for p in sorted((C/'row-trace-d03-analysis-03').iterdir()):
 if p.is_file():raws['analyzer-version03/'+p.name]=p.read_bytes()
assert sum(map(len,raws.values()))<64*1024*1024
P.mkdir();preserved={}
for n,raw in raws.items():p=P/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);preserved[n]={'sha256':sha(raw),'bytes':len(raw)}
(P/'manifest.json').write_bytes(enc({'schema':'orbit-poc-d03-analysis04-preservation-v1','files':preserved,'scientific_acceptance':False}))
A=C/'publish_bounded_retry.py';assert sha(A.read_bytes())=='0a2a33dde1906981dae09fce1dae1683e1c60783adad8c3d38d9af3545ccebf5';s=importlib.util.spec_from_file_location('scrub',A);M=importlib.util.module_from_spec(s);s.loader.exec_module(M)
files={};payload={}
def add(n,raw,original=True):
 data=M.scrub(raw.decode()).encode() if original else raw;z=original and Path(n).suffix in ('.json','.xml','.log');name=n+'.gz' if z else n;stored=gzip.compress(data,mtime=0) if z else data
 assert name not in files
 files[name]={'sha256':sha(stored),'bytes':len(stored),'published_expanded_sha256':sha(data),'published_expanded_bytes':len(data),'encoding':'gzip' if z else 'identity','transformation':'path tokenization' if original else 'generated presentation'}
 if original:files[name].update(original_sha256=sha(raw),original_bytes=len(raw))
 payload[name]=stored
for n,raw in raws.items():add(n,raw)
add('preservation/manifest.json',(P/'manifest.json').read_bytes())
r=json.loads((C/'d03-exact-geometry-independent-result-review-01.json').read_text());assert r['status']=='passed' and r['measurement_rows_in_every_component']==8064
summary={'schema':'orbit-poc-d03-analysis04-publication-v1','diagnostic_only':True,'scientific_acceptance':False,'covariance_authorized':False,'release_ready':False,'execution08_status':'failed','result_sha256':pins['result.json'],'scope':'Exact algebraic attribution of the frozen generation4 full-step distance-clock discrepancy; no corrected-forward-model counterfactual.','original_rows':9469,'measurement_rows_in_every_component':8064,'component_objective_effects':r['component_objective_effects'],'distance_clock_discrepancy':r['distance_clock_discrepancy'],'duration_addition_fraction':r['duration_addition_fraction'],'independent_component_sum_closure':r['independent_sum_minus_reported_actual_geometry_discrepancy'],'source_native_data_and_acceptance_limits_changed':False,'raw_traces_included':False,'preceding_snapshot_manifest_sha256':'38665dbd6587ad4258cf8daf012324b0aba1fbb2cddbe9108c197a97fe04c1c5'}
add('summary.json',enc(summary),False)
labels={'clock_geometry_component_clock_plus_travel_duration_arithmetic':'Clock-plus-travel duration addition','clock_geometry_component_transmitter_position_vs_captured_duration_kinematics':'Transmitter position versus captured-duration kinematics','clock_geometry_component_travel_distance_cast_and_division_arithmetic':'Travel-distance cast and division','clock_geometry_component_exact_fixed_point_minus_first_order_clock_coefficient':'Exact fixed-point versus first-order clock coefficient','clock_geometry_component_final_light_time_iteration_residual':'Final light-time iteration residual','clock_geometry_component_receiver_position_vs_moving_clock_kinematics':'Receiver position versus moving-clock kinematics','clock_geometry_component_coefficient_weight_scale_rounding':'Coefficient/weight scaling rounding','clock_geometry_component_range_projection_remainder':'Range-projection remainder'}
rows=[(labels[k],f'{float(v):+.9e}') for k,v in r['component_objective_effects'].items()]
intro='Analysis04 extends the sealed analyses01–03 snapshot with an exact algebraic decomposition of the same captured generation4 full trial. Every component includes all8,064 GNSS measurement rows; the full9,469-row objective accounting is unchanged. Both independent reviews passed, with component-sum closure within1.70e-107.'
claim='Clock-plus-travel duration addition contributes−2.68673436e-14 of the−2.68691010e-14 distance-clock discrepancy (99.9934596%). This is measured algebraic attribution around captured baseline kinematics. Query-arithmetic terms use the captured linear coefficient and retain explicit motion and closure residuals; it is not an executed corrected-forward-model counterfactual.'
limit='The smaller measured terms remain in the table and full result. This evidence supports testing a narrow arithmetic correction. It does not show that such a correction passes the unchanged objective gates, the failed second replay, covariance checks or the full v3.1 release requirements. The original execution08 result remains failed; no scientific gate or acceptance threshold is replaced.'
links=[('Preceding analyses01–03 snapshot','../recovery08-diagnostic-d03/index.html'),('Actual execution08 failure','../recovery07-08/index.html'),('Full analysis04 result','analysis-attempt04/result.json.gz'),('Actual invocation receipt','analysis-attempt04/receipt.json.gz'),('Attribution/runtime review','reviews/d03-analysis04-attribution-review-01.json.gz'),('Independent component review','reviews/d03-exact-geometry-independent-result-review-01.json.gz'),('Independent54-test review','reviews/row-trace-d03-analyzer-independent-review-03.json.gz'),('Summary','summary.json'),('Manifest','manifest.json')]
md='# D03 analysis04: clock-plus-travel arithmetic attribution\n\n'+intro+'\n\n'+claim+'\n\nEach table contribution is the sum of that normalized residual component change multiplied by the mean baseline/trial row residual; it is not a measured gain from a corrected native fit.\n\n| Component | Contribution |\n| --- | --- |\n'+''.join(f'| {a} | {b} |\n' for a,b in rows)+'\n'+limit+'\n\nThe new analyzer is separately versioned; its54 fabricated tests and independent review are preserved. Analyses01/02 failures and completed analysis03 remain unchanged in the preceding snapshot. No native fit was launched by this analysis. The three pinned raw traces (4,445,392,754bytes) remain external. Publication copies tokenize paths and record both original and published hashes.\n\n'+ '\n'.join(f'- [{a}]({b})' for a,b in links)+'\n'
add('README.md',md.encode(),False)
style='body{font:16px/1.55 system-ui;max-width:1000px;margin:40px auto;padding:0 20px;color:#16212a}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd5df;padding:9px;text-align:left}.status{padding:16px;background:#fff1d5;border-left:5px solid #9b6700}'
body='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>D03 analysis04 — algebraic attribution only</title><style>'+style+'</style><div class="status">Execution08 remains failed. No corrected native fit, covariance or release authorization.</div><h1>D03 analysis04: clock-plus-travel arithmetic attribution</h1>'
body+=''.join('<p>'+html.escape(x)+'</p>' for x in [intro,claim])+'<p>Each table contribution is the sum of that normalized residual component change multiplied by the mean baseline/trial row residual; it is not a measured gain from a corrected native fit.</p><table><tr><th>Component</th><th>Contribution</th></tr>'+''.join('<tr><td>'+html.escape(a)+'</td><td>'+html.escape(b)+'</td></tr>' for a,b in rows)+'</table><p>'+html.escape(limit)+'</p><p>The full source,54-test evidence and reviews are retained. Raw4.445GB traces remain external. Paths are tokenized; all original and published hashes are recorded.</p><ul>'+''.join(f'<li><a href="{b}">{a}</a></li>' for a,b in links)+'</ul></html>'
add('index.html',body.encode(),False);O.mkdir()
for n,raw in payload.items():p=O/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
f={'schema':'orbit-poc-d03-analysis04-publication-manifest-v1','files':files,'bytes':sum(map(len,payload.values())),'preservation_manifest_sha256':sha((P/'manifest.json').read_bytes()),'diagnostic_only':True,'scientific_acceptance':False};(O/'manifest.json').write_bytes(enc(f))
print(json.dumps({'path':str(O),'files':len(files),'bytes':f['bytes'],'manifest_sha256':sha((O/'manifest.json').read_bytes()),'preservation_manifest_sha256':f['preservation_manifest_sha256']}))
