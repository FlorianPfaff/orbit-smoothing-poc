"""Render a portable evidence report and content manifest; no native execution."""
from pathlib import Path
import datetime, hashlib, html, json, shutil
P=Path(__file__).parent/'packet'
r=json.loads((P/'report.json').read_text())
source_map={f['source']:f['path'] for f in json.loads((P/'source-map.json').read_text())['files']}
for role, identity in r['independent_audits'].items():
    p=P/source_map[identity['path']]
    assert hashlib.sha256(p.read_bytes()).hexdigest()==identity['sha256'], role
    audit=json.loads(p.read_text())
    assert audit.get('approved',audit.get('passed')) is True and audit['checks'] and all(c['passed'] for c in audit['checks']), role
esc=html.escape
def link(p,label): return '<a href="'+esc(p)+'">'+esc(label)+'</a>'
rows=[]
for s in r['stages']:
    d='evidence/reference-gates14-run01/'+s['stage']
    evidence=s['evidence']
    if 'maximum_fraction_of_sigma' in evidence: detail=f"{evidence['maximum_fraction_of_sigma']:.9g} sigma; limit 0.01"
    elif 'accepted_scales' in evidence: detail='Consecutive scales '+str(evidence['accepted_scales'])
    else: detail=f"Strict={evidence['strict']}; final update {evidence['raw_update_m']:.9g} m"
    vals=[esc(s['stage']),esc(s['status']),esc(detail),f"{s['scientific_seconds']:.1f}",f"{s['supervised_seconds']:.1f}",f"{s['peak_process_tree_rss_bytes']/1024**3:.3f}",link(d+'/strict-result.json','Result')+' / '+link(d+'/supervisor.json','Execution')]
    rows.append('<tr>'+''.join('<td>'+v+'</td>' for v in vals)+'</tr>')
audits=[P/source_map[v['path']] for v in r['independent_audits'].values()]
assert audits, 'Independent terminal audit must exist before publication'
body='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Recovery14: eight-check validation</title><style>body{font:16px/1.55 system-ui;max-width:1200px;margin:32px auto;padding:0 24px;background:#f8fafc;color:#203044}table{border-collapse:collapse;width:100%;background:white}td,th{padding:9px;border-bottom:1px solid #d7dfe8;text-align:left}th{background:#e8eef5}.notice{padding:16px;border-left:4px solid #49758b;background:#eaf2f7}a{color:#0756a6}code{overflow-wrap:anywhere}.table{overflow:auto}</style><h1>Recovery14: all eight checks passed</h1>'''
body+='<p>Completed 24 October 2026 at 14:38 Europe/Berlin. Publication is separate from the frozen v3.1 and v4 campaigns.</p>'
body+='<p class="notice">Candidate04 reference-preservation evidence. No complete nonlinear fit, accepted orbital covariance, speedup, candidate05 qualification or release readiness is established. No new fit was launched.</p>'
body+='<p>'+link('README.md','Explanation and limitations')+' · '+link('report.json','Machine-readable results')+' · '+link('summary.csv','CSV')+' · '+link('manifest.json','Package hashes')+' · '+link('source-map.json','Evidence locator map')+'</p>'
body+='<div class="table"><table><tr><th>Gate</th><th>Outcome</th><th>Evidence</th><th>Numerical seconds</th><th>Supervised seconds</th><th>Peak GiB</th><th>Receipts</th></tr>'+''.join(rows)+'</table></div>'
body+='<p>All 32 objective profiles and both distinct replays achieved strict nuisance convergence; none relied on floor-limited acceptance. Density scales 1, 0.5 and 0.25 failed the directional test and remain recorded; prescribed successive scales 0.125 and 0.0625 passed without changing the 1e-4 criterion. Stage totals include inventory I/O and are not fit speed comparisons.</p>'
body+='<h2>Independent audit</h2><p>The approved final terminal and objective audits below bind the published evidence. Earlier audit-checker mistakes are preserved in the evidence directory and do not represent native execution failures.</p><ul>'+''.join('<li>'+link(str(p.relative_to(P)),str(p.relative_to(P)))+'</li>' for p in audits)+'</ul>'
body+='<p>359 overall checks and 381 objective checks passed. Density’s first passing total relative error is 9.82621e-5 against 1e-4: a narrow margin. Frozen retention removed the base tangent factors, so the independent finite-difference audit compares against the recorded native derivative scalar, not a second tangent-factor solve. '+link('evidence/terminal-audit14-01/report.txt','Independent audit report')+'</p>'
body+='<h2>Preserved failures and scope</h2><p>Run12 had two output-routing failures before objective evaluation. Run13 failed preparation before native computation. Run14 ran all eight checks afresh; no prior pass was reused. The original four long regression attempts and four candidate05 GNSS diagnostics remain timeouts. Small-check correctness does not resolve the initial cold-nuisance bottleneck.</p>'
for label,rel in [('Run12 terminal result','reference-gates12-run01/result.json'),('Run13 preparation failure','preparation04/result.json'),('Interruption record','interruption-audit/interruption.json'),('Original regression timeout audit','timeout-audit/audit.json'),('Separate candidate05 timeout audit','gnss-timeout-audit01/audit.json')]:
    body+='<p>'+link('evidence/'+rel,label)+'</p>'
body+='<p>The flight check uses a standalone 30-minute fixed-state window and the existing flight_gravity_drag_v1 approximation. It omits thermal-history sensitivities, other force gradients and atmospheric event-time derivatives.</p>'
body+='<h2>Next full-fit regressions</h2><p>Two existing one-hour cold full fits, pulse and density, with original GNSS-only initialization and unchanged limits. Qualify candidate05 separately before OFF/ON full-fit comparisons. Retry the exact 72-hour pulse and 48-hour density cases only after a measured improvement completes their initial cold solve strictly.</p><p>'+link('evidence/next-full-fit-plan01/README.md','Prioritized test plan')+' · '+link('evidence/next-full-fit-plan01/plan.json','Exact cases, hashes and prerequisites')+'</p>'
body+='<p>Native SHA256: <code>'+r['native_sha256']+'</code>. Original binary, datasets and large row archives remain external. Archived scripts require the pinned runtime and environment; this packet is not a self-contained execution environment.</p></html>'
(P/'index.html').write_text(body)
shutil.copyfile(Path(__file__).parent/'README.template.md',P/'README.md')
shutil.copyfile(__file__,P/'finalize_packet.py')
# Nested source manifests remain covered; only this root manifest is self-excluded.
files=[{'path':str(p.relative_to(P)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(P.rglob('*')) if p.is_file() and p!=P/'manifest.json']
(P/'manifest.json').write_text(json.dumps({'schema':'orbit-poc-evidence-packet-manifest-v1','scope':'Every published file except this root manifest; original evidence bytes unchanged','files':files,'file_count':len(files),'total_bytes':sum(x['bytes'] for x in files)},indent=2)+'\n')
print(json.dumps({'files':len(files),'bytes':sum(x['bytes'] for x in files),'manifest_sha256':hashlib.sha256((P/'manifest.json').read_bytes()).hexdigest()}))
