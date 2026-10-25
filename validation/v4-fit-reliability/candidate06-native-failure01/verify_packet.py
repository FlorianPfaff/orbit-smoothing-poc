#!/usr/bin/env python3
"""Verify this static archive. Never imports or executes archived source/controllers."""
import argparse, hashlib, json, sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit, unquote

BINARY='28c725765201e4702875ec8407d3bc497aa4bdfa3092a305b15a3233cfbd675d'
PLAN='aca653aae8ae8c712defdc74b550e43be013552e26aebf9cc454f30757df8e95'
TEST='da2db1dab2d4a9677b7c6d33889d8bfe549294d2dbdc72a3b1d4a5c05acefb08'
FLAG='ORBIT_POC_NUISANCE_FAIL_FAST_REPLAY'
FAILURES={
 'tests.test_numerics_native_qr::test_native_nuisance_search_is_transactional[reject]',
 'tests.test_numerics_native_qr::test_native_nuisance_search_is_transactional[support]',
 'tests.test_numerics_native_qr::test_native_nuisance_search_is_transactional[exception]',
 'tests.test_numerics_native_qr::test_native_empirical_nuisance_floor_requires_independent_audits[floor_zero_replay-zero_update_replay_failed]'}
class Links(HTMLParser):
 def __init__(self):super().__init__();self.links=[]
 def handle_starttag(self,tag,attrs):
  for key,value in attrs:
   if key in ('href','src') and value:self.links.append(value)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def junit(path):
 root=ET.parse(path).getroot(); suites=[root] if root.tag=='testsuite' else list(root.iter('testsuite'))
 counts={k:sum(int(s.get(k,'0')) for s in suites) for k in ['tests','failures','errors','skipped']}
 cases={}
 for c in root.iter('testcase'):
  key=c.get('classname','')+'::'+c.get('name','')
  if key in cases:raise ValueError('duplicate testcase '+key)
  kind='failed' if c.find('failure') is not None else 'error' if c.find('error') is not None else 'skipped' if c.find('skipped') is not None else 'passed'
  cases[key]=kind
 return counts,cases

def verify(packet,originals=False):
 checks=[]
 def check(name,condition):
  checks.append({'name':name,'passed':bool(condition)})
  if not condition:raise ValueError(name)
 def read(rel):return json.loads((packet/rel).read_text())
 def local(rel):
  q=PurePosixPath(rel)
  check('safe path '+rel,not q.is_absolute() and '..' not in q.parts and str(q)==rel)
  p=packet/rel
  check('regular non-symlink '+rel,p.is_file() and not p.is_symlink())
  check('within packet '+rel,p.resolve().is_relative_to(packet.resolve()))
  return p
 try:
  m=read('artifact-manifest.json'); rows=m['files']; names=[r['path'] for r in rows]
  check('manifest schema',m['schema']=='immutable-publication-manifest-v1')
  check('unique manifest paths',len(names)==len(set(names)))
  check('manifest file count',m['file_count']==len(rows))
  check('manifest total bytes',m['total_bytes']==sum(r['bytes'] for r in rows))
  actual={p.relative_to(packet).as_posix() for p in packet.rglob('*') if p.is_file()}
  check('exact file inventory',actual==set(names)|{'artifact-manifest.json'})
  for row in rows:
   p=local(row['path']);check('size '+row['path'],p.stat().st_size==row['bytes']);check('hash '+row['path'],sha(p)==row['sha256'])
  manifest={r['path']:r for r in rows}
  provenance=read('provenance.json')['files']
  check('unique copied originals',len({r['path'] for r in provenance})==len(provenance))
  for row in provenance:
   check('copied manifest '+row['path'],row['path'] in manifest and all(row[k]==manifest[row['path']][k] for k in ('bytes','sha256')))
   if originals:
    p=Path(row['original_path']);check('original exists '+row['path'],p.is_file());check('original size '+row['path'],p.stat().st_size==row['bytes']);check('original hash '+row['path'],sha(p)==row['sha256'])
  for row in read('external-artifacts.json')['files']:
   check('external valid pin '+row['path'],Path(row['path']).is_absolute() and len(row['sha256'])==64 and row['bytes']>=0)
   if originals:
    p=Path(row['path']);check('external exists '+row['path'],p.is_file());check('external bytes '+row['path'],p.stat().st_size==row['bytes']);check('external hash '+row['path'],sha(p)==row['sha256'])
  report=read('report.json');history=read('evidence/history-audit/history-audit.json');ind=read('evidence/independent-audit/findings.json')
  counts,cases=junit(packet/'evidence/current/tests.xml')
  check('current counts',counts=={'tests':106,'failures':4,'errors':0,'skipped':0})
  check('current actual case count',len(cases)==106)
  check('exact four failures',{k for k,v in cases.items() if v=='failed'}==FAILURES)
  check('102 actual passes',sum(v=='passed' for v in cases.values())==102)
  check('report failed',report['status']=='failed' and report['tests']==106 and report['passed']==102 and report['failures']==4 and report['errors']==report['skips']==0)
  check('report exact failure names',set(report['failure_case_ids'])==FAILURES)
  for rel in ['evidence/prior/remote106/tests.xml','evidence/prior/local106/tests.xml']:
   c,t=junit(packet/rel);check('prior106 pass '+rel,c=={'tests':106,'failures':0,'errors':0,'skipped':0});check('same106 identities '+rel,set(t)==set(cases));check('same four prior passes '+rel,all(t[k]=='passed' for k in FAILURES))
  c,t=junit(packet/'evidence/prior/fail-fast37/tests.xml');check('explicit37 pass',c=={'tests':37,'failures':0,'errors':0,'skipped':0} and len(t)==37)
  for mode in ['reject','support','exception','floor_zero_replay']:
   for flag in ['default','legacy','early']:
    key='tests.test_native_nuisance_fail_fast::test_native_invalid_replay_keeps_legacy_work_unless_opted_in['+mode+'-'+flag+']';check('prior option contract '+mode+'/'+flag,t.get(key)=='passed')
   base='evidence/current/fixtures/'+mode
   d=read(base+'/search.json');check('zero ordinary trials '+mode,d['trials']==[]);check('invalid replay rejected '+mode,d['floor_rejection']=='zero_update_replay_failed')
   for key in ['accepted','stationary_without_update','nuisance_floor_limited']:check(mode+' '+key+' false',d[key] is False)
   check('parent preserved '+mode,(packet/base/'qr.parent.txt').read_bytes()==b'parent\npreserved\n')
   check('mode config '+mode,mode in (packet/base/'run.xml').read_text())
  strict=read('evidence/current/strict-result.json');supervisor=read('evidence/current/supervisor.json');plan=read('evidence/current/correctness-plan.json')
  check('exact frozen current plan',sha(packet/'evidence/current/correctness-plan.json')==PLAN==report['original_plan_sha256'])
  check('current stage inventory',len(plan['jobs'])==10 and plan['jobs'][0]['stage']=='native-tests')
  check('current opt-in option',plan['jobs'][0]['environment'][FLAG]=='1')
  check('scientific argv bound',strict['argv']==plan['jobs'][0]['argv'])
  check('strict failure',strict['stage']=='native-tests' and strict['status']=='failed' and strict['returncode']==1)
  check('supervisor failure',supervisor['status']=='failed' and supervisor['returncode']==1)
  check('supervisor plan pinned',supervisor['plan_sha256']==sha(packet/'evidence/current/supervisor.plan.json'))
  check('owned cleanup',supervisor['owned_process_group_cleaned'] is True and supervisor['cleanup']['verified'] is True and supervisor['cleanup']['remaining']==[])
  for k in ['full_fit_verified','covariance_authority','release_authority']:check('strict no '+k,strict[k] is False and report[k] is False)
  check('failure not waived',report['failed_gate_reclassified'] is False and history['current_gate_remains_failed'] is True)
  check('history consistency',history['passed_history_consistency_checks'] is True)
  check('independent diagnosis',ind['diagnosis_supported'] is True and ind['check_count']==23 and len(ind['checks'])==23)
  for name,value in (ind['checks'].items() if isinstance(ind['checks'],dict) else [(str(i),v) for i,v in enumerate(ind['checks'])]):
   check('independent '+name,value is True or isinstance(value,dict) and value.get('passed') is True)
  check('same binary report and audit',report['native_binary_sha256']==history['actual_native_binary_sha256']==BINARY)
  check('original106 unchanged source',sha(packet/'evidence/source/tests/test_numerics_native_qr.py')==TEST)
  check('remote requested binary',read('evidence/prior/remote106/request.json')['native_sha256']==BINARY)
  check('remote started binary',read('evidence/prior/remote106/startup.json')['native_sha256']==BINARY)
  freeze=read('evidence/prior/local106/freeze.json');check('local legacy option absent',FLAG not in freeze['environment'])
  check('local test source pin',freeze['source_snapshot']['tests/test_numerics_native_qr.py']==TEST)
  priorargv=read('evidence/prior/remote106/supervisor.plan.json')['argv'];check('remote cleared env','--clearenv' in priorargv)
  priorenv={priorargv[i+1]:priorargv[i+2] for i in range(len(priorargv)-2) if priorargv[i]=='--setenv'}
  check('remote legacy option absent',FLAG not in priorenv)
  check('source parser default0','const std::string value=raw?raw:"0";' in (packet/'evidence/source/groops/extension/nuisanceLineSearch.h').read_text())
  check('test options asserted','(0 if flag == "1" else 17)' in (packet/'evidence/source/tests/test_native_nuisance_fail_fast.py').read_text())
  for r in history['source_identity']:check('historical identity '+r['relative_path'],r['candidate04_candidate06_and_snapshots_match'] is True and sha(packet/'evidence/source'/r['relative_path'])==r['sha256'])
  check('installed header distinction',sha(packet/'evidence/source/installed/nuisanceLineSearch.h')!=sha(packet/'evidence/source/groops/extension/nuisanceLineSearch.h') and history['compiled_native_matches_frozen_native_source'] is True and history['compiled_flag_parser_and_search_match_overlay'] is True)
  for key in ['source_or_test_modified','thresholds_changed','frozen_benchmarks_changed','current_run_mutated']:check('unchanged '+key,report['preservation'][key] is False)
  check('no new native runs',report['preservation']['native_runs_by_packager']==0)
  check('prior proposal immutable claim',report['references']['candidate06_proposal_commit']=='1017dcdbc05998609ec3a7bfbd78e071b3173c36')
  check('remaining not certified',report['remaining_current_stages'].startswith('not certified'))
  check('cold gate remains closed',report['cold_fit_gate'].startswith('must remain closed'))
  parser=Links();parser.feed((packet/'index.html').read_text())
  for link in parser.links:
   url=urlsplit(link)
   if url.scheme or url.netloc:check('only intended external link '+link,link=='https://github.com/FlorianPfaff/orbit-smoothing-poc/pull/9')
   elif url.path:check('local report link '+link,(packet/unquote(url.path)).is_file())
  return {'passed':True,'checks':checks,'check_count':len(checks),'manifest_sha256':sha(packet/'artifact-manifest.json'),'verify_originals':originals,'native_tests_executed':0,'scientific_gate_status':'failed; unchanged'}
 except Exception as error:
  return {'passed':False,'checks':checks,'check_count':len(checks),'error':repr(error),'verify_originals':originals,'native_tests_executed':0,'scientific_gate_status':'failed; unchanged'}

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--packet',type=Path,default=Path(__file__).resolve().parent);parser.add_argument('--verify-originals',action='store_true');parser.add_argument('--output',type=Path)
 args=parser.parse_args();out=verify(args.packet,args.verify_originals);out['created_utc']=datetime.now(timezone.utc).isoformat();body=json.dumps(out,indent=2,sort_keys=True)+'\n'
 if args.output:
  with args.output.open('x') as f:f.write(body)
 print(json.dumps({k:v for k,v in out.items() if k!='checks'},sort_keys=True));return 0 if out['passed'] else 1
if __name__=='__main__':sys.exit(main())
