"""Build an immutable offline-only checker evidence packet; never read fits."""
from pathlib import Path
import hashlib, html, importlib.metadata, json, shutil, sys
import xml.etree.ElementTree as ET

BASE=Path('/home/emper/orbit-nuisance-performance')
SOURCE=BASE/'source'
OUT=SOURCE/'validation/nuisance-performance/wholefit-checker01'
TIMESTAMP='2026-10-19T09:00:23+00:00'
SOURCE_COMMIT='6a917783896688f3bbc24f169a31bc9e3a238a63'
EXPECTED={
 'checker':'6316cd37b23edadc678e1a3a083802780488882db37c7ca9d686691f93e74836',
 'tests':'abf56cbf9e1a1efb254d9fbce289a034213cdc6664cc68cf21b2ebb65bc7646c',
 'review':'54189e9d82ec5e13c02de4b5596a61ec165cb2e85b9dba9559d7159b6c5b8944'}

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(rel,value):
 p=OUT/rel;p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n')
 return p

def copy(path,rel):
 p=OUT/rel;p.parent.mkdir(parents=True,exist_ok=True)
 raw=path.read_bytes();p.write_bytes(raw)
 assert p.read_bytes()==raw
 COPIES.append({'relative_path':rel,'source_path':str(path),'sha256':sha(p),'bytes':p.stat().st_size})
 return p

assert sha(SOURCE/'scripts/analyze_nuisance_wholefit.py')==EXPECTED['checker']
assert sha(SOURCE/'tests/test_nuisance_wholefit_analysis.py')==EXPECTED['tests']
assert sha(BASE/'control/wholefit-checker-review03/independent-review03.json')==EXPECTED['review']
OUT.mkdir(parents=True,exist_ok=False)
COPIES=[]
for n in ('01','02','03'):
 folder=BASE/f'control/wholefit-checker-review{n}'
 for p in sorted(folder.iterdir()):
  if p.is_file():copy(p,f'reviews/review{n}/'+p.name)
 copy(BASE/f'analysis/wholefit-checker-tests{n}.xml',f'author-tests/round{n}.xml')
for rel in ['scripts/analyze_nuisance_profile.py','scripts/check_nuisance_performance_pair.py',
            'tests/test_nuisance_performance_pair.py']:
 copy(SOURCE/rel,'dependencies/'+rel)
copy(Path(__file__),'controls/build_wholefit_checker_packet01.py')

runtime={'python_version':sys.version,'python_executable':str(Path(sys.executable).resolve()),
 'python_sha256':sha(Path(sys.executable).resolve()),
 'packages':{key:importlib.metadata.version(key) for key in ['numpy','pytest']},
 'scope':'Offline test runtime only; no native executable or satellite dataset is included.'}
write('offline-runtime.json',runtime)
reviews=[]
for n in ('01','02','03'):
 folder=OUT/f'reviews/review{n}'
 review=json.loads((folder/f'independent-review{n}.json').read_text())
 suites=ET.parse(OUT/f'author-tests/round{n}.xml').getroot()
 cases=list(suites.iter('testcase'))
 stats={'tests':len(cases),'failures':len(list(suites.iter('failure'))),
        'errors':len(list(suites.iter('error'))),'skipped':len(list(suites.iter('skipped')))}
 reviews.append({'round':n,'review_status':review['status'],
  'author_tests':stats,'independent_tests':review.get('independent_tests'),
  'checker_sha256':review['checker']['sha256'],'test_sha256':review['author_fixtures']['sha256'],
  'review':f'reviews/review{n}/independent-review{n}.json',
  'counterexamples':f'reviews/review{n}/counterexamples.json'})
final_counter=json.loads((OUT/'reviews/review03/counterexamples.json').read_text())
modules=final_counter['records'][0]['scientific_gate_modules']
gates=[]
for name,item in sorted(modules.items()):
 rel='src/'+item['path'].split('/source/src/',1)[1]
 assert sha(SOURCE/rel)==item['sha256']
 gates.append({'module':name,'repository_path':rel,'sha256':item['sha256']})
write('frozen-gate-sources.json',{'source_commit':SOURCE_COMMIT,'modules':gates})
summary={'schema':'orbit-poc-wholefit-checker-publication-v1','packet_timestamp_utc':TIMESTAMP,
 'status':'offline_checker_validation_accepted','checker_sha256':EXPECTED['checker'],
 'test_sha256':EXPECTED['tests'],'independent_review_sha256':EXPECTED['review'],
 'actual_fit_outcomes':'unassessed','native_runs_for_this_validation':0,
 'accepted_covariance':False,'release_authority':False,'timing_claims_authorized':False,
 'scope':'Offline reporting-tool fixtures and independent review. No actual full-fit results or live output trees were read.',
 'source_repository':'https://github.com/FlorianPfaff/orbit-smoothing-poc',
 'scientific_source_commit':SOURCE_COMMIT,'reviews':reviews,
 'limitations':[
  'Passing fixture tests and checker review do not establish whole-fit convergence, covariance validity, numerical equivalence, cache benefit or release readiness.',
  'Actual cache-off/on fit outcomes are unassessed in this packet. No native executable, satellite data or live-fit data is included.',
  'The host clock discrepancy and its timing interpretation are retained separately by the passive result reporter. This packet makes no timing/speedup claim.',
  'Malformed partial artifacts from a rejected native trial in an ultimately complete fit conservatively invalidate analysis; preserve any first actual invalid analysis before a separately reviewed extension.',
  'Deleted intermediate factors use recorded pre-release identities, distinguished from retained-byte comparisons.',
  'All earlier reviews and measured counterexamples are retained. The first two review candidates were not accepted despite passing their existing fixture suites.',
  'The packet timestamp is a fixed publication label, not elapsed-time evidence.'
 ]}
write('summary.json',summary)
write('source-copies.json',{'schema':'orbit-poc-exact-source-copies-v1','copies':COPIES})

reproduce='''Offline reproduction (no estimator or satellite data)

The source and fixture snapshots are exact copies. Archived JSON reports contain
historical absolute temporary paths; do not interpret those paths as live inputs.
New fixture executions naturally use new paths and timings. Compare test outcomes
and classifications rather than expecting identical newly generated report bytes.

1. Use a disposable checkout of the repository at scientific source commit:
   6a917783896688f3bbc24f169a31bc9e3a238a63
   https://github.com/FlorianPfaff/orbit-smoothing-poc
   Never apply these snapshots to the frozen running fit source.
2. Copy dependencies/scripts/*.py into checkout/scripts/, and
   dependencies/tests/test_nuisance_performance_pair.py into checkout/tests/.
3. Select one archived review round. Copy its analyze_nuisance_wholefit.py into
   checkout/scripts/ and test_nuisance_wholefit_analysis.py into checkout/tests/.
4. Use a Python environment matching offline-runtime.json and install this
   checkout's declared Python requirements. Set OPENBLAS_NUM_THREADS=1 and
   OMP_NUM_THREADS=1. On an admitted Linux host with CPU4 available, run:

   taskset -c 4 python -B -m pytest -q -p no:cacheprovider \\
     tests/test_nuisance_wholefit_analysis.py \\
     --basetemp=/tmp/new-wholefit-checker-fixtures \\
     --junitxml=/tmp/new-wholefit-checker-tests.xml

   Choose fresh output paths. Run only on reserved resources.
5. Expected author suite counts are 46, 53 and 56 for rounds 01, 02 and 03,
   with no failures or skips. Passing the early suites did not make those
   candidates correct: retain and inspect the independent counterexamples.
6. reviews/review02/replay_counterexamples.py and review03's corresponding
   script preserve the independent negative cases. Their SOURCE/OUT constants
   or hard-coded analysis paths describe the original environment; adapt those
   locations in a fresh copy before replay, recording the adapted script hash.
   The original scripts and counterexample outputs must remain unchanged.
7. The final round rejects stale optimizer records, missing one/both complete
   point directories and nonpositive completed-run wall durations. Source gate
   loading uses only pinned frozen module bytes, including lazy dependencies.

Validate the packet's payload identities against manifest.json. The manifest
lists every other file, including the exact-copy ledger and this instruction.
No payload claims a result from either actual 24-hour full-fit attempt.
'''
(OUT/'REPRODUCE.txt').write_text(reproduce)
rows=[]
for row in reviews:
 n=row['round'];r=row['review_status'];count=row['author_tests']['tests']
 independent=(str(row['independent_tests']['passed'])+' passed') if row['independent_tests'] else 'Measured counterexamples and source review'
 rows.append('<tr><td>'+n+'</td><td>'+str(count)+' passed</td><td>'+html.escape(independent)+'</td><td>'+html.escape(r)+'</td><td><a href="'+row['review']+'">Review</a> · <a href="'+row['counterexamples']+'">Counterexamples</a> · <a href="author-tests/round'+n+'.xml">Author JUnit</a></td></tr>')
source_links=[]
for n in ('01','02','03'):
 source_links.append('<li>Round '+n+': <a href="reviews/review'+n+'/analyze_nuisance_wholefit.py">checker</a>, <a href="reviews/review'+n+'/test_nuisance_wholefit_analysis.py">fixtures</a></li>')
page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Whole-fit checker validation — offline only</title><style>body{max-width:1120px;margin:32px auto;padding:0 22px;font:16px/1.55 system-ui;color:#172331;background:#f6f8fb}main{background:white;padding:30px;border:1px solid #dbe1e8;border-radius:12px}h1{font-size:29px;line-height:1.2}h2{font-size:21px;margin-top:32px}.notice{padding:16px;border-left:5px solid #b56a00;background:#fff5e0}.success{padding:16px;border-left:5px solid #217d51;background:#eef9f2}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:10px;border-bottom:1px solid #dbe1e8;vertical-align:top}code{overflow-wrap:anywhere}a{color:#1559a2}small{color:#506071}.scroll{overflow:auto}li{margin:8px 0}</style><main>
<h1>Whole-fit checker validation</h1><p><small>Fixed publication label: '''+TIMESTAMP+''' · Offline fixtures and independent review</small></p>
<div class="success"><strong>The final checker passed 56 author tests and 56 independent tests, with no failures or skips.</strong> Independent review accepted the corrected reporting tool.</div>
<p class="notice"><strong>The actual 24-hour orbit-fit outcomes are unassessed here.</strong> This packet authorizes no covariance, equivalence, performance or release claim. No estimator was run for this validation and no live-fit data is included. The host clock discrepancy and timing interpretation are held separately by the passive result reporter.</p>
<p>The checker preserves missing, failed, interrupted and timed-out attempts. It requires verified cleanup before reading a terminal point tree. Completed-fit evidence is bound to the worker, optimizer history and native execution ledger. Scientific gates run from the pinned frozen source, including lazy imports. Exact scientific equality is separate from a valid outcome analysis.</p>
<h2>Preserved review sequence</h2><div class="scroll"><table><thead><tr><th>Round</th><th>Author tests</th><th>Independent checks</th><th>Review decision</th><th>Evidence</th></tr></thead><tbody>'''+''.join(rows)+'''</tbody></table></div>
<p>Round 01 incorrectly accepted identical stale optimizer records and lost completed-point evidence; its scientific gate imports were not bound to frozen source. Round 02 corrected those findings but crashed on a zero completed-run wall duration. Round 03 rejects those malformed receipts and a nonfinite time ratio. Earlier passing fixture suites are retained alongside their failed reviews; they are not presented as accepted versions.</p>
<h2>Final source identities</h2><p>Checker: <code>'''+EXPECTED['checker']+'''</code><br>Fixtures: <code>'''+EXPECTED['tests']+'''</code><br>Independent review: <code>'''+EXPECTED['review']+'''</code></p>
<ul>'''+''.join(source_links)+'''<li><a href="reviews/review03/tests.xml">Independent final JUnit</a> · <a href="reviews/review03/tests.log">Independent test output</a> · <a href="reviews/review03/replay_counterexamples.py">Counterexample replay source</a></li><li><a href="reviews/review03/nuisance-performance.md">Reviewed documentation snapshot</a> · <a href="frozen-gate-sources.json">Frozen scientific gate identities</a></li></ul>
<h2>Reproduction and interpretation</h2><p><a href="REPRODUCE.txt">Offline reproduction instructions</a> · <a href="offline-runtime.json">Python runtime</a> · <a href="summary.json">Machine-readable summary</a> · <a href="source-copies.json">Exact-copy provenance</a> · <a href="manifest.json">Payload SHA-256 manifest</a></p>
<p>Exit code zero means valid outcome analysis; it does not mean the fits converged or agreed. Recorded pre-release factor identities are distinguished from direct retained-byte comparisons. A successful fit with malformed partial artifacts from a rejected native trial currently invalidates analysis conservatively. Preserve any such first analysis before a separately reviewed extension. A single eventual treatment pair cannot establish a statistical speedup.</p>
<p>Scientific models, tolerances, physical inputs, native executable and the frozen campaign were not changed by this offline checker work.</p></main></html>'''
(OUT/'index.html').write_text(page)
files=[]
for p in sorted(OUT.rglob('*')):
 if p.is_file():files.append({'path':str(p.relative_to(OUT)),'bytes':p.stat().st_size,'sha256':sha(p)})
write('manifest.json',{'schema':'orbit-poc-immutable-publication-manifest-v1','packet_timestamp_utc':TIMESTAMP,
 'scope':'Every payload except this manifest itself; immutable after independent review.','files':files})
print(json.dumps({'root':str(OUT),'payloads':len(files),'bytes':sum(p['bytes'] for p in files),
 'copies':len(COPIES),'manifest_sha256':sha(OUT/'manifest.json')},sort_keys=True))
