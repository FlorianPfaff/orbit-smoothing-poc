#!/usr/bin/env python3
"""Independent offline audit; never starts the estimator or changes a frozen run."""
from pathlib import Path
import datetime,hashlib,importlib.util,json,os,xml.etree.ElementTree as ET
B=Path('/home/emper/orbit-nuisance-performance'); R=B/'source'; D=B/'control/native-pairs-independent01'
seen={};hash_cache={}
def require(v,m):
 if not v:raise ValueError(m)
def pin(path):
 p=Path(path);a=p.stat();key=(str(p),a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)
 if key not in hash_cache:
  h=hashlib.sha256()
  with p.open('rb') as f:
   for c in iter(lambda:f.read(1024*1024),b''):h.update(c)
  z=p.stat();require((a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(z.st_dev,z.st_ino,z.st_size,z.st_mtime_ns,z.st_ctime_ns),'changed while reading '+str(p));hash_cache[key]={'path':str(p),'sha256':h.hexdigest(),'bytes':a.st_size}
 rec=hash_cache[key];seen[str(p)]=rec;return rec
def load(path):pin(path);return json.loads(Path(path).read_text())
def verify(rec):
 q=pin(rec['path']);require(q['sha256']==rec['sha256'],'pin mismatch '+str(rec['path']));return q
checker=R/'scripts/check_nuisance_performance_pair.py';require(pin(checker)['sha256']=='7a396b15cdb8ca3be1129aedbcf20359e9ddfcb4480c0e03e2d4b24b6f4545fd','checker changed')
require(pin(R/'scripts/analyze_nuisance_profile.py')['sha256']=='3ccf1d2ff9235136c00f909df44f9e623785e2476191717e469f65f05e6040c2','analyzer changed')
spec=importlib.util.spec_from_file_location('checker',checker);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
build=load(B/'build-01/build-manifest.json'); require(build['upstream_commit']=='7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee' and build['mpi'] is False,'build profile')
require(pin(B/'build-01/groops')['sha256']==build['executable_sha256'],'native binary')
review=load(B/'control/native-patch-review01/orbit-poc-nuisance-performance-extension.json');require(build['nuisance_performance_extension']==review,'candidate source differs from reviewed patch')
for rel,h in review['installed_files'].items(): require(pin(B/'native-source-01'/rel)['sha256']==h and build['patched_source']['files'][rel]==h,'installed patch drift')
require(pin(B/'build-01/CMakeCache.txt')['sha256']==build['cmake_cache_sha256'],'cmake drift')
completebuild=load(B/'control/candidate-build-complete01.json');verify(completebuild['native']);verify(completebuild['build_manifest']);require(completebuild['native']['sha256']==build['executable_sha256'],'archived binary mismatch')
for rec in completebuild['libraries']:verify(rec);require(str(Path(rec['path']).resolve())==rec['resolved'],'library target changed')
# Exact originally specified native/correction test suites and JUnit cases.
testfreeze=load(B/'native-tests01/freeze.json');testresult=load(B/'native-tests01/result.json');require(testresult['passed'] is True,'test overall')
require(testfreeze['cache']==1 and testfreeze['performance']==1 and testfreeze['cpu']==0 and testfreeze['threads']==1,'native test controls')
require(testfreeze['candidate_build']==completebuild,'test build identity')
require(pin(B/'control/run_native_tests01.py')['sha256']==testfreeze['runner_sha256'],'test runner changed')
suphash=pin(R/'src/orbit_poc/segmented/supervisor.py')['sha256'];require(testfreeze['supervisor_sha256']==suphash,'supervisor changed')
for rel,h in testfreeze['test_hashes'].items():
 require(pin(R/rel)['sha256']==h,'test source changed')
 require(pin(Path('/mnt/d/orbit-segmented-v4/validation-07-packet/source')/rel)['sha256']==h,'test source differs from archived validation07')
tests=[]
for (name,count,files),result in zip(testfreeze['suites'],testresult['results']):
 folder=B/'native-tests01'/name;root=ET.parse(folder/'tests.xml').getroot();pin(folder/'tests.xml');cases=list(root.iter('testcase'))
 counts={'tests':len(cases),**{t:sum(c.find(t) is not None for c in cases) for t in ('failure','error','skipped')}}
 require(counts=={'tests':count,'failure':0,'error':0,'skipped':0} and counts==result['counts'],'actual JUnit counts')
 require(len({(c.get('classname'),c.get('name')) for c in cases})==count,'duplicate JUnit test')
 s=load(folder/'supervisor.json');pl=load(folder/'supervisor.plan.json');require(s==result['execution'],'suite execution mismatch')
 require(s['status']=='complete' and s['returncode']==0 and s['owned_process_group_cleaned'] is True and s['cleanup']['verified'] is True and not s['cleanup']['remaining'],'suite cleanup')
 require(s['plan_sha256']==pin(folder/'supervisor.plan.json')['sha256'] and pl['argv']==s['argv'] and pl['helper_sha256']==suphash,'suite plan binding')
 require(s['argv'][-len(files):]==files and s['argv'][:3]==['/usr/bin/taskset','-c','0'],'suite selection')
 tests.append({'suite':name,'counts':counts,'junit':pin(folder/'tests.xml'),'execution':pin(folder/'supervisor.json'),'elapsed_seconds':s['elapsed_seconds'],'cleanup_verified':True})
require([t['counts']['tests'] for t in tests]==[106,51],'prescribed counts')
# All twelve attempts: freeze identities, actual completion, exact native treatment, immutable inputs.
runs=[];pairs=[];execution_groups=[];input_union={}
for group,runner,expected in [('paired01','run_pairs01.py',8),('replay-pairs01','run_replay_pairs01.py',4)]:
 q=B/group;prep=load(q/'preparation.json');freeze=load(q/'freeze.json');done=load(q/'execution-complete.json')
 require(done=={'all_planned_attempts_executed':True,'count':expected,'freeze_sha256':pin(q/'freeze.json')['sha256']},'terminal group')
 require(len(prep['jobs'])==expected and [j['name'] for j in prep['jobs']]==prep['predeclared_order']==freeze['order'],'job order/count')
 require(pin(q/'preparation.json')['sha256']==freeze['preparation_sha256'],'freeze prep')
 require(pin(B/'control'/runner)['sha256']==freeze['runner_sha256'],'runner changed')
 verify(freeze['native']);verify(freeze['build_manifest']);verify(freeze['python']);require(freeze['native']['sha256']==build['executable_sha256'] and freeze['supervisor_sha256']==suphash,'shared executable')
 require(prep['cpu']==0 and prep['one_numerical_thread'] is True and prep['max_process_tree_rss_bytes']==8589934592 and prep['timeout_seconds']==7200,'run controls')
 for job in prep['jobs']:
  folder=Path(job['profile']).parent;e=load(folder/'profile.execution.json');s=load(folder/'supervisor.json');pl=load(folder/'supervisor.plan.json');p=load(folder/'qr.profile.json');a=load(folder/'admission.json')
  require(e['status']=='complete' and e['returncode']==0 and e['timed_out'] is False and e['owned_process_group_cleaned'] is True,'run not complete')
  require(s['status']=='complete' and s['returncode']==0 and s['cleanup']['verified'] is True and not s['cleanup']['remaining'] and s['owned_process_group_cleaned'] is True,'run cleanup')
  require(e['supervisor_sha256']==pin(folder/'supervisor.json')['sha256'] and s['plan_sha256']==pin(folder/'supervisor.plan.json')['sha256'],'execution chain')
  require(pl['argv']==s['argv']==e['command'] and pl['helper_sha256']==suphash,'command/helper chain')
  require(pl['timeout_seconds']==7200 and pl['max_process_tree_rss_bytes']==8589934592 and pl['cwd']==str(folder),'actual supervisor limits')
  require(not a['unrelated_native_or_build_processes'] and a['boot']==s['boot_id']==freeze['admission']['boot'],'admission')
  require(p['nuisance_converged'] is True and p['nuisance_floor_limited'] is False and p['threshold_m']==1e-8 and p['required_consecutive_small_updates']==2,'strict criterion')
  require(len(p['history'])==p['iterations'] and len(p['history'])>=2 and all(0<=x['maximum_update_m']<1e-8 for x in p['history'][-2:]),'last two strict corrections')
  for f in [job['source_profile'],*job['input_files']]:
   if f['path'] in input_union:require(input_union[f['path']]['sha256']==f['sha256'],'conflicting input pin')
   input_union[f['path']]=f
  sidecars=[load(path) for path in sorted(folder.glob('qr.*.nuisance_performance.json'))];rows=[]
  for x in sidecars:rows += [x['parent_row_build'],x['zero_update_replay']['row_build']]+[t['row_build'] for t in x['ordinary_trials']]+[t['row_build'] for t in x['arithmetic_audits']]+[t['row_build'] for r in x['probe_rounds'] for t in r]
  calls=sum(x.get('interpolation_calls',0) for x in rows);hits=sum(x.get('interpolation_cache_hits',0) for x in rows);evals=sum(x.get('interpolation_evaluations',0) for x in rows)
  require(calls==hits+evals and (hits>0 if job['cache'] else hits==0),'treatment counter')
  runs.append({'name':job['name'],'group':group,'cache':job['cache'],'accumulate':job['accumulate'],'execution':pin(folder/'profile.execution.json'),'profile':pin(folder/'qr.profile.json'),'status':e['status'],'strict_nuisance_convergence':True,'floor_limited':False,'iterations':p['iterations'],'final_two_updates_m':[x['maximum_update_m'] for x in p['history'][-2:]],'elapsed_seconds':e['elapsed_seconds'],'peak_process_tree_rss_bytes':e['peak_rss_bytes'],'measured_search_interpolation':{'calls':calls,'hits':hits,'evaluations':evals},'cleanup_verified':True})
 for method,acc in sorted({(j['method'],j['accumulate']) for j in prep['jobs']}):
  key=f'{method}-accumulate{acc}';off=q/f'{key}-cache0';on=q/f'{key}-cache1';out=D/f'{key}-pair-review01.json'
  if out.exists():result=load(out)
  else:
   result=m.compare(off,on)
   with out.open('x') as f:json.dump(result,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
  require(result['passed'] is True and result['cache_pair_verified'] is True and result['artifact_equality'] is True and not result['issues'],'independent exact pair')
  author=load(B/'analysis'/f'{key}-pair01.json');require(author['comparisons']==result['comparisons'] and author['passed'] is True,'author/independent comparison difference')
  for run in result['runs']:
   for f in run['provenance']:verify(f)
  pairs.append({'method':method,'accumulate':acc,'group':group,'report':pin(out),'author_report':pin(B/'analysis'/f'{key}-pair01.json'),'scientific_artifacts_compared':result['scientific_comparison_count'],'exact_equality':True,'accepted_covariance':False})
 execution_groups.append({'name':group,'preparation':pin(q/'preparation.json'),'freeze':pin(q/'freeze.json'),'completion':pin(q/'execution-complete.json'),'runner':pin(B/'control'/runner),'attempts':expected})
# Fresh post-completion input union, no repeated per-job full hashing.
for rec in input_union.values():verify(rec)
require(len(runs)==12 and len(pairs)==6,'coverage')
r={'schema':'orbit-poc-native-nuisance-pairs-independent-audit-v1','status':'passed_bounded_native_and_exact_pair_checks','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'auditor':pin(Path(__file__)),'audit_cpu_affinity':sorted(os.sched_getaffinity(0)),'native_test_suites':tests,'total_native_and_correction_tests':157,'test_failures':0,'test_skips':0,'candidate_build':pin(B/'build-01/build-manifest.json'),'candidate_native':pin(B/'build-01/groops'),'candidate_installed_patch':review,'runtime_dependencies_independently_rehashed':len(completebuild['libraries']),'execution_groups':execution_groups,'runs':runs,'pairs':pairs,'paired_scientific_comparisons':sum(x['scientific_artifacts_compared'] for x in pairs),'input_union_postcompletion_verified':{'unique_paths':len(input_union),'bytes_counting_paths':sum(f['bytes'] for f in input_union.values())},'scientific_comparison':'Exact JSON values except three declared per-trial CPU/RSS resource fields, plus exact uncompressed text and binary factor payloads; no numerical tolerance introduced.','missing_evidence':[],'limitations':['This is 106 native tests, 51 correction tests and 12 fixed-orbit nuisance profiles, not the complete prescribed propagation/objective/refinement release suite.','Both old failure replays preserve their distinct original physical/statistical inputs. Successful current nuisance profiles do not imply a completed full nonlinear orbit fit.','One observation per off/on cell is a bounded engineering timing observation, not a statistical speedup estimate, large-arc scaling claim or accuracy-superiority claim.','Recorded sidecar interpolation/design/build/child wall timings overlap and cover search iterations only; final fresh linearization and other parent stages are outside sidecar accounting.','One-thread CPU0 controls and environment are attributed to pinned reviewed runners and supervisor receipts; resource admission is cooperative, not exclusive CPU reservation.','Covariance is not authorized by this audit; full-fit strict convergence and fresh covariance gates remain separate.','Frozen production campaigns, executables, inputs, thresholds and results were not changed.'],'native_commands_executed_by_auditor':0,'accepted_covariance':False,'whole_fit_convergence_established':False,'release_authority':False,'provenance':list(seen.values())}
out=B/'control/native-pairs-independent-audit01.json'
with out.open('x') as f:json.dump(r,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
print(json.dumps({'audit':str(out),'sha256':pin(out)['sha256'],'tests':157,'attempts':len(runs),'pairs':len(pairs),'input_union':len(input_union)}))
