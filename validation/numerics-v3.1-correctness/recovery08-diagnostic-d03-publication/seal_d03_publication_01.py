"""Seal the bounded D03 analysis01–03 snapshot. No native execution."""
from pathlib import Path
import json,gzip,hashlib,html,importlib.util,shutil
B=Path('@LOCAL_DATA_ROOT@/orbit-numerics-v3.1/correctness');C=B/'control';S=B/'staging-d03-publication';O=B/'publication-source/validation/numerics-v3.1-correctness/recovery08-diagnostic-d03'
def sha(b):return hashlib.sha256(b).hexdigest()
def enc(x):return (json.dumps(x,indent=2,sort_keys=True)+'\n').encode()
assert sha((S/'staging-manifest.json').read_bytes())=='2d77be95f15f16de38a07bdf78dd2c7a47291908d58a03a28c04632892bcdf4d'
A=C/'publish_bounded_retry.py';assert sha(A.read_bytes())=='0a2a33dde1906981dae09fce1dae1683e1c60783adad8c3d38d9af3545ccebf5'
s=importlib.util.spec_from_file_location('scrub',A);M=importlib.util.module_from_spec(s);s.loader.exec_module(M)
assert not O.exists();manifest=json.loads((S/'staging-manifest.json').read_text());files={};payload={}
for name,r in manifest['files'].items():
 raw=(S/name).read_bytes();assert sha(raw)==r['sha256'] and len(raw)==r['bytes'];decoded=gzip.decompress(raw) if r['encoding']=='gzip' else raw
 assert sha(decoded)==r['published_expanded_sha256'] and len(decoded)==r['published_expanded_bytes'];files[name]=r;payload[name]=raw
extra={
 'd03-independent-row-math-summary-01.json':'5b4cf194fb9a8eaaae07aaabef6cc91641a1d6b7b28cc2bc44d084bf064ddd94',
 'd03-independent-row-math-invocation-01.json':'f13e7d37bf71a2cf3c4644ee58df2eee64d135877cde736865c62dfd374d8317',
 'd03-independent-row-math-tests-01.json':None,
 'independent_d03_row_math.py':'4613b6fa4f1dc25c9b6c95f35ece22cdb2d8a8a2ffde263e9eee7c83148b6aaf',
 'test_independent_d03_row_math.py':'e316182b012d32d63a96e37949e813ec9f157a4855f967f502ecc0e157a27a14',
}
def add(name,raw,original=True):
 assert name not in payload and len(raw)<=16*1024*1024
 data=M.scrub(raw.decode()).encode() if original else raw
 compressed=Path(name).suffix in ('.json','.xml','.log');target=name+'.gz' if compressed and original else name
 stored=gzip.compress(data,mtime=0) if compressed and original else data
 payload[target]=stored;files[target]={'sha256':sha(stored),'bytes':len(stored),'published_expanded_sha256':sha(data),'published_expanded_bytes':len(data),'encoding':'gzip' if compressed and original else 'identity','transformation':'path tokenization' if original else 'generated presentation'}
 if original:files[target].update(original_sha256=sha(raw),original_bytes=len(raw))
for name,pin in extra.items():
 raw=(C/name).read_bytes();assert pin is None or sha(raw)==pin;add('independent-row-accounting/'+name,raw)
tests=json.loads((C/'d03-independent-row-math-tests-01.json').read_text())
for record in tests['files']:
 if record['path'].endswith('.xml'):
  raw=Path(record['path']).read_bytes();assert sha(raw)==record['sha256'];add('independent-row-accounting/'+Path(record['path']).name,raw)
# Preserve the earlier fabricated-test discrepancy, without representing it as a scientific failure.
p=Path(tests['prior_fixture_failure']['path'])
if p.exists():add('independent-row-accounting/'+p.name,p.read_bytes())
add('preservation/staging-manifest.json',(S/'staging-manifest.json').read_bytes())
r=json.loads((C/'d03-analysis-result-03/independent-analysis-03/result.json').read_text());a=json.loads((C/'d03-independent-row-math-summary-01.json').read_text())
assert r['status']=='completed' and r['original_objective_rows']==9469 and r['scientific_validation_complete'] is False
assert a['status']=='passed' and a['original_objective_rows']==9469 and a['covariance_authorized'] is False
summary={'schema':'orbit-poc-d03-publication-summary-v1','diagnostic_only':True,'scientific_validation_complete':False,'covariance_authorized':False,'release_ready':False,'main_execution08_scientific_status':'failed','source_commit':'8e4d36f7c47d57acdb9fa30d15a6005189bbf221','native_sha256':'3a113ae1a88954a33f81f6e251ecffb98a757058821568965aae11658be8e251','diagnostic':{'equivalence_checks':52,'equivalence_passed':True,'generations':4,'trace_off':'incomplete_stop_before_generation5','trace_on':'incomplete_stop_before_generation5','cleanup_verified':True},'analysis_scope':'Sealed analysis attempts01–03 and independent all-row accounting; causal attribution unresolved in this snapshot. Later analyses are separate.','analysis_attempts':{'01':'interpreter_failure_before_parsing','02':'failed_precise_row_consistency_check','03':'completed'},'rows':{'gnss_measurements':8064,'local_stec_priors':1344,'separate_constraints':61,'total':9469},'global_parameters':386,'equation_blocks':1344,'native_predicted_reduction':r['native_profile_prediction'],'independent_requested_prediction':r['requested_original_row_prediction'],'independent_full_row_accounting':'passed','independent_accounting_precision_digits':128,'independent_accounting_actual_difference':a['checks_minus_reported']['actual_1'],'trace_inventory':r['artifacts']['traces'],'trace_bytes':sum(x['bytes'] for x in r['artifacts']['traces']),'raw_trace_contents_included':False,'limitations':['Outcome-selected diagnostic of generation4 only; original failed density run continues to generation52.','Both bounded native replays are explicitly incomplete, not accepted fits.','Complete objective-row accounting does not uniquely attribute component discrepancy to an arithmetic or derivative cause.','No counterfactual corrected native run; no orbit accuracy, covariance, scientific acceptance or speed claim.','The independent accounting tolerance is diagnostic arithmetic agreement, not an estimator acceptance threshold.','No original106 test, objective, refinement or replay gate is replaced.','The original frozen150-attempt benchmark and v3 campaign remain separate.','Path-tokenized copies differ from original bytes; every original and published digest is recorded.']}
add('summary.json',enc(json.loads(M.scrub(json.dumps(summary)))),False)
text=(C/'d03-report-draft.md').read_text().replace('Draft pending the independent full-row support/math cross-review. No publication or scientific acceptance is implied by this draft.','Sealed snapshot of analysis attempts01–03 and their independent all-row cross-check. Scientific correctness remains unresolved; later causal analysis is published separately.')
text=text.replace('The requested linear step predicts a decrease,', 'A separate 128-digit reconstruction independently reproduced all original-row costs and predictions; its actual-reduction difference was below 8.9e-109. It additionally checked 20 selected component rows. The 1e-90 arithmetic agreement tolerance is diagnostic only and does not change an estimator gate.\n\nThe requested linear step predicts a decrease,')
links=[('Execution08 full failure report','../recovery07-08/index.html'),('Machine-readable summary','summary.json'),('Completed analysis03','analysis-attempt03/result.json.gz'),('Independent all-row accounting','independent-row-accounting/d03-independent-row-math-summary-01.json.gz'),('Independent native lifecycle audit','controls-review/d03-terminal-independent-audit-02.json.gz'),('Exact equivalence','actual-d03/diagnostic/equivalence.json.gz'),('Publication manifest','manifest.json'),('Complete evidence index','evidence.html')]
text+='\nEvidence: '+', '.join(f'[{label}]({path})' for label,path in links)+'.\n'
add('README.md',text.encode(),False)
# Plain semantic Markdown rendered as paragraphs, headings and tables without external dependencies.
def render(md):
 out=[];table=False
 for line in md.splitlines():
  if line.startswith('|'):
   if set(line.replace('|','').replace(' ','').replace('-',''))==set():continue
   if not table:out.append('<table>');table=True
   out.append('<tr>'+''.join('<td>'+html.escape(x.strip())+'</td>' for x in line.strip('|').split('|'))+'</tr>');continue
  if table:out.append('</table>');table=False
  if line.startswith('# '):out.append('<h1>'+html.escape(line[2:])+'</h1>')
  elif line:out.append('<p>'+html.escape(line)+'</p>')
 if table:out.append('</table>')
 return '\n'.join(out)
style='body{font:16px/1.55 system-ui;max-width:1000px;margin:40px auto;padding:0 20px;color:#16212a}table{border-collapse:collapse;width:100%;margin:20px 0}td,th{border:1px solid #ccd5df;padding:9px;text-align:left}a{color:#064ba1}code{overflow-wrap:anywhere}.status{padding:16px;background:#fff1d5;border-left:5px solid #9b6700}'
header='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><style>'+style+'</style>'
body=render(text.split('\nEvidence:')[0]);nav='<ul>'+''.join(f'<li><a href="{html.escape(path)}">{html.escape(label)}</a></li>' for label,path in links)+'</ul>'
add('index.html',(header+'<title>D03 bounded diagnostic — correctness unresolved</title><div class="status">Diagnostic evidence only. Execution08 remains failed. No covariance or release authorization.</div>'+body+nav+'</html>').encode(),False)
items=''.join(f'<tr><td><a href="{html.escape(n)}">{html.escape(n)}</a></td><td>{r["bytes"]:,}</td><td><code>{r["sha256"]}</code></td></tr>' for n,r in sorted(files.items()))
add('evidence.html',(header+'<title>D03 evidence inventory</title><h1>D03 evidence inventory</h1><p>Compressed receipts preserve expanded tokenized contents; original digests are in the manifest. Raw trace contents are external.</p><table><tr><th>File</th><th>Stored bytes</th><th>Stored SHA-256</th></tr>'+items+'</table></html>').encode(),False)
assert sum(map(len,payload.values()))<=64*1024*1024
O.mkdir(parents=True)
for n,raw in payload.items():p=O/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
final={'schema':'orbit-poc-d03-bounded-publication-manifest-v1','files':files,'bytes':sum(map(len,payload.values())),'source_staging_manifest_sha256':sha((S/'staging-manifest.json').read_bytes()),'diagnostic_only':True,'scientific_gate_substitution':False,'raw_trace_contents_included':False,'source_assembler':{'path':str(Path(__file__)), 'sha256':sha(Path(__file__).read_bytes())}}
(O/'manifest.json').write_bytes(enc(final));print(json.dumps({'path':str(O),'files':len(files),'bytes':final['bytes'],'manifest_sha256':sha((O/'manifest.json').read_bytes())}))
