"""Assemble exact preflight evidence; never run a scientific workload."""
from pathlib import Path
import json,hashlib,shutil,html,collections,xml.etree.ElementTree as ET,datetime,subprocess
C=Path('/mnt/d/orbit-segmented-v4/control');S=Path('/mnt/d/orbit-segmented-v4/source');OUT=Path('/mnt/d/orbit-segmented-v4/publication-preflight-01')
MAX_FILE=4*1024**2;MAX_TOTAL=16*1024**2

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')
def pin(path):p=Path(path);return {'path':str(p),'sha256':digest(p),'bytes':p.stat().st_size}
def load(path):return json.loads(Path(path).read_text())
def junit(path):
 cases=ET.parse(path).findall('.//testcase');rows=[]
 for case in cases:
  status='failed' if case.find('failure') is not None else 'error' if case.find('error') is not None else 'skipped' if case.find('skipped') is not None else 'passed'
  rows.append({'classname':case.get('classname',''),'name':case.get('name',''),'status':status})
 if len({(x['classname'],x['name']) for x in rows})!=len(rows):raise ValueError('Duplicate test identity within invocation')
 return rows

def main():
 OUT.mkdir(exist_ok=False);mapping={};records=[];omitted=[];seen=set();total=0
 def copy(path,category='evidence',expected=None):
  nonlocal total
  path=Path(path)
  if str(path) in mapping:return mapping[str(path)]
  if not path.is_file():raise ValueError('Missing required evidence '+str(path))
  item=pin(path)
  if expected is not None and (item['sha256']!=expected['sha256'] or 'bytes'in expected and item['bytes']!=expected['bytes']):raise ValueError('Changed raw evidence '+str(path))
  if item['bytes']>MAX_FILE or total+item['bytes']>MAX_TOTAL:raise ValueError('Preflight evidence bound exceeded')
  name=f'raw/{category}/{item["sha256"][:12]}-{path.name}';target=OUT/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target);assert digest(target)==item['sha256'];total+=item['bytes'];mapping[str(path)]=name;records.append({'path':name,'original':str(path),'sha256':item['sha256'],'bytes':item['bytes'],'encoding':'identity'})
  return name
 def refs(value):
  if isinstance(value,dict):
   if isinstance(value.get('path'),str) and isinstance(value.get('sha256'),str):yield value
   for x in value.values():yield from refs(x)
  elif isinstance(value,list):
   for x in value:yield from refs(x)
 def closure(path,depth=0):
  if str(path) in seen:return
  seen.add(str(path));copy(path,'reviews')
  for ref in refs(load(path)):
   q=Path(ref['path'])
   if q.suffix not in ('.xml','.log','.json') or str(q).startswith(str(S)) or not (str(q).startswith(str(C)) or str(q).startswith('/tmp/')):
    continue
   if not q.is_file() or digest(q)!=ref['sha256']:
    omitted.append({'artifact':ref,'reason':'historical source or external dependency not available with its recorded identity; not used in301passing-union or scientific claim'});continue
   copy(q,expected=ref)
   if q.suffix=='.json' and depth<3:closure(q,depth+1)
 selected=[
 'segmented-protocol-author-validation-04.json','segmented-protocol-author-validation-05.json',
 'segmented-protocol-independent-review-01.json','segmented-protocol-independent-review-02.json','segmented-protocol-independent-review-03.json',
 'segmented-owned-supervisor-author-validation-01.json','segmented-owned-supervisor-independent-review-01.json',
 'segmented-production-residual-independent-review-01.json','segmented-products-independent-review-01.json',
 'segmented-native-qr-author-validation-03.json','segmented-native-qr-independent-review-02.json',
 'segmented-backend-independent-review-01.json','segmented-tangent-author-validation-02.json','segmented-tangent-independent-review-02.json',
 'segmented-linearization-gate-author-validation-03.json','segmented-linearization-gate-independent-review-03.json',
 'segmented-validation-controller-author-review-02.json','segmented-validation-outer-independent-review-01.json','segmented-validation-outer-independent-review-02.json',
 'segmented-balanced-order-independent-review-01.json','segmented-balanced-order-independent-review-02.json',
 'profile-order-counterexample-01.json','profile-order-correction-01/validation.json','profile-order-correction-02/validation.json','profile-order-correction-03/validation.json',
 'flight-normalization-independent-01/review.json']
 for name in selected:closure(C/name)
 runs=[];inventory={}
 for label,path,expected in [('broad_structural',Path('/tmp/v4-structural-tests-01.xml'),289),('final_solver',C/'local-solver-residual-01.xml',19),('final_protocol',Path('/tmp/v4-profile-order-03.xml'),50)]:
  rows=junit(path);assert len(rows)==expected and all(x['status']=='passed' for x in rows)
  stored=copy(path,'junit');runs.append({'id':label,'tests':len(rows),'passed':len(rows),'failures':0,'errors':0,'skipped':0,'junit':stored,'sha256':digest(path)})
  for row in rows:
   key=(row['classname'],row['name']);entry=inventory.setdefault(key,{**row,'passing_runs':[]});entry['passing_runs'].append(label)
 assert len(inventory)==301
 failure=Path('/tmp/segmented-final-protocol-independent-01.xml');retry=Path('/tmp/segmented-final-protocol-independent-02.xml');frows=junit(failure);rrows=junit(retry);failed=[x for x in frows if x['status']=='failed'];assert len(frows)==100 and len(failed)==1 and len(rrows)==1 and rrows[0]['status']=='passed' and (failed[0]['classname'],failed[0]['name'])==(rrows[0]['classname'],rrows[0]['name'])
 startup={'original':{'junit':copy(failure,'junit'),'tests':100,'passed':99,'failed':1,'errors':0,'skipped':0},'unchanged_retry':{'junit':copy(retry,'junit'),'tests':1,'passed':1,'failed':0},'failed_test':failed[0],'disposition':load(C/'segmented-owned-supervisor-independent-review-01.json')['startup_failure_disposition']}
 order=load(C/'profile-order-correction-03/balanced-attempts.json');copy(C/'profile-order-correction-03/balanced-attempts.json','order');assert len(order['attempts'])==68
 for folder in ('profile-order-correction-01','profile-order-correction-02','profile-order-correction-03'):
  for name in ('protocol.py','test_segmented_protocol.py'):
   copy(C/folder/name,'historical-source')
 copy(C/'prior-seed-scan-01/scan.json','seed-scan');copy(C/'prior-seed-scan-01/scan_v4_prior_seeds01.py','seed-scan')
 source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=S,text=True).strip();source_files={}
 for name in ('src/orbit_poc/segmented/protocol.py','src/orbit_poc/segmented/validation.py','src/orbit_poc/segmented/solver.py','src/orbit_poc/segmented/supervisor.py','tests/test_segmented_protocol.py','tests/test_segmented_solver.py','tests/test_segmented_supervisor.py'):
  source_files[name]=pin(S/name)
 counts=dict(sorted(collections.Counter(x['classname'] for x in inventory.values()).items()))
 summary={'schema':'orbit-poc-segmented-preflight-publication-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'Local preflight and review snapshot; this is not the current-source full native validation or the68-fit benchmark','status':'preflight_checks_passed_with_preserved_failures_and_corrections','source_commit':source_commit,'current_source_files':source_files,'planned_benchmark_attempts':68,'benchmark_attempts_executed':0,'full_native_validation':'pending_separate_execution','original150_completion':'separate_required_deliverable_not_established_by_this_bundle','release_ready':False,'covariance_authorized':False,'accuracy_or_speedup_claim':False,'test_union':{'unique_tests':301,'total_passing_test_observations':sum(x['tests'] for x in runs),'duplicate_observations_removed':sum(x['tests'] for x in runs)-301,'key':['classname','name'],'runs':runs,'counts_by_module':counts,'explanation':'289 broad fixtures +7 new solver cases +5 new protocol-order cases. Later19 and50 invocations repeat12 and45 earlier cases.301 is a union of exact test identities, not a single301-test invocation.'},'preserved_startup_failure':startup,'profile_order':{'initial_counterexample':mapping[str(C/'profile-order-counterexample-01.json')],'final_review':mapping[str(C/'segmented-balanced-order-independent-review-02.json')],'final_schedule':mapping[str(C/'profile-order-correction-03/balanced-attempts.json')],'policy':load(C/'profile-order-correction-03/validation.json')['policy'],'positions':order['position_counts'],'prior_prelaunch_candidates_preserved':True,'case_order_and_case_profile_set_unchanged':True},'raw_receipts':{name:mapping[str(C/name)] for name in selected},'historical_or_external_references_not_copied':omitted,'separate_engineering_reports':['../engineering01/index.html','../engineering02/index.html'],'copy_policy':'All raw receipts/XML/logs retain exact original bytes and their original absolute references. This manifest supplies local file mappings. Historical source hashes are not relabelled as current. No native binaries, physical datasets or row spools are included.'}
 write(OUT/'summary.json',summary);write(OUT/'test-inventory.json',sorted(inventory.values(),key=lambda x:(x['classname'],x['name'])))
 def link(path,label):return '<a href="'+html.escape(path,quote=True)+'">'+html.escape(label)+'</a>'
 modules=''.join('<tr><td>'+html.escape(k)+'</td><td>'+str(v)+'</td></tr>' for k,v in counts.items())
 runrows=''.join('<tr><td>'+html.escape(x['id'])+'</td><td>'+str(x['tests'])+'</td><td>'+link(x['junit'],'Exact JUnit')+'</td></tr>' for x in runs)
 reviews=''.join('<li>'+link(mapping[str(C/name)],name)+'</li>' for name in selected)
 page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>v4 preflight evidence — 0 of68 benchmark fits</title><style>body{font:16px/1.5 system-ui;margin:2rem auto;max-width:1100px;padding:0 1rem;color:#17202a}h1{font-size:2rem}table{border-collapse:collapse;width:100%;margin:1rem 0}th,td{padding:.45rem;border:1px solid #ccd;text-align:left}.notice{background:#fff4cc;padding:1rem;border-left:5px solid #b47b00}code{overflow-wrap:anywhere}li{overflow-wrap:anywhere}</style><h1>v4 preflight evidence</h1><p class="notice"><strong>0 of68 benchmark attempts executed in this snapshot. Full current-source native validation remains pending separate execution.</strong> The301 distinct passing fixture identities below are local preflight evidence. They do not establish benchmark completion, release readiness, covariance authorization, orbital accuracy or speedup.</p>'''
 page+='<p>Source commit <code>'+source_commit+'</code>. '+link('summary.json','Machine-readable summary')+' · '+link('test-inventory.json','Deduplicated301-test inventory')+' · '+link('manifest.json','Exact file checksums')+'. Earlier '+link('../engineering01/index.html','engineering01')+' and '+link('../engineering02/index.html','engineering02')+' native runs retain their own source identities and narrower scopes.</p>'
 page+='<h2>Passing fixture evidence</h2><p>'+html.escape(summary['test_union']['explanation'])+' All three invocations below have zero failures, errors or skips;358 passing observations deduplicate to301 identities.</p><table><tr><th>Invocation</th><th>Passing tests</th><th>Evidence</th></tr>'+runrows+'</table><details><summary>301 identities by module</summary><table><tr><th>Module</th><th>Distinct tests</th></tr>'+modules+'</table></details>'
 page+='<h2>Preserved startup failure</h2><p>'+html.escape(startup['disposition'])+'</p><p>'+link(startup['original']['junit'],'Original100-test invocation:99 passed,1 failed')+' · '+link(startup['unchanged_retry']['junit'],'Exact unchanged failing test:1 passed in fresh retry')+' · '+link(mapping[str(C/'segmented-owned-supervisor-independent-review-01.json')],'Independent ownership review')+'. The original failure is retained; it is not converted into a clean first run.</p>'
 page+='<h2>Profile-order correction before launch</h2><p>The first three-profile schedule placed dense first in10 of12 cases. The failed counterexample and intermediate per-arity and per-duration candidates are preserved. The final deterministic factorial rotation balances24-hour profiles four times per position overall; each48/72-hour profile appears four times per position. Method and coverage margins balance exactly, regime margins balance exactly where divisible and otherwise differ by at most one. Matching48/72-hour families reverse order. All68 case/profile identities, physical settings and case order remain unchanged.</p><p>'+link(summary['profile_order']['initial_counterexample'],'Original failed counterexample')+' · '+link(summary['profile_order']['final_schedule'],'Final68-attempt schedule and all position counts')+' · '+link(summary['profile_order']['final_review'],'Independent final-order review')+'. No scientific fit was launched by these order candidates.</p>'
 page+='<h2>Reviewed controls and remaining work</h2><p>The source has a real serial validation dispatcher, exact original106/51 test and14-input identities, mandatory runtime closure, preserved original flight requests, owned-process cleanup with a kernel no-child certificate, and strict release reporting. Local fixtures exercise these contracts. The unchanged native correctness suite, actual new native linearization gates, all68 numerical attempts, and the original150 campaign completion remain separate requirements. Legacy defaults remain unchanged.</p><p>Each raw receipt keeps its exact historical bytes and source hashes. Review findings and later corrections are not silently rewritten. The outer-controller entrypoint failure and corrected real help smoke are retained in the corresponding receipts.</p><details><summary>Exact author and independent review receipts</summary><ul>'+reviews+'</ul></details>'
 (OUT/'index.html').write_text(page+'<p><small>Preflight snapshot generated '+html.escape(summary['created_at'])+'.</small></p></html>\n')
 (OUT/'README.md').write_text('# v4 preflight evidence\n\nThis is a local preflight snapshot:301 distinct test identities with passing evidence, deduplicated from289+19+50 invocations. The preserved100-test independent invocation had99passes and1startup failure; the unchanged failing node passed its fresh retry. Both remain available.\n\nNo current-source full native validation or68-fit benchmark result is claimed.0of68 benchmark fits are represented. Older engineering01/02 results are separate. Original150 completion remains required; legacy defaults remain unchanged.\n\nOpen index.html or summary.json. Raw receipts/XML/logs are byte-identical copies; manifest.json maps original paths to retained files and SHA256/length. Historical source hashes are not relabelled. No datasets,binaries or row spools are included.\n')
 # The assembler itself is bounded provenance, not executed scientific source.
 copy(Path(__file__),'assembly')
 files=[]
 for q in sorted(OUT.rglob('*')):
  if q.is_file():files.append({'path':str(q.relative_to(OUT)),'sha256':digest(q),'bytes':q.stat().st_size})
 manifest={'schema':'orbit-poc-segmented-preflight-publication-manifest-v1','files':files,'raw_original_mapping':records,'files_count':len(files),'total_bytes':sum(x['bytes'] for x in files),'limits':{'maximum_file_bytes':MAX_FILE,'maximum_total_bytes':MAX_TOTAL},'scope':summary['scope']}
 assert manifest['total_bytes']<=MAX_TOTAL and all(x['bytes']<=MAX_FILE for x in files)
 write(OUT/'manifest.json',manifest)
 for x in files:assert digest(OUT/x['path'])==x['sha256'] and (OUT/x['path']).stat().st_size==x['bytes']
 print(json.dumps({'output':str(OUT),'manifest':pin(OUT/'manifest.json'),'files':len(files),'bytes':manifest['total_bytes'],'unique_tests':301,'omitted_references':len(omitted)}))
if __name__=='__main__':main()
