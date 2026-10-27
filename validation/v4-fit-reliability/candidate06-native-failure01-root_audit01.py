"""Independent static evidence audit; no archived program is executed."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, xml.etree.ElementTree as ET

root=Path(__file__).resolve().parent
packet=root/'packet'
checks=[]
def check(name,condition):
    checks.append({'name':name,'passed':bool(condition)})
    if not condition: raise AssertionError(name)
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def read(name): return json.loads((packet/name).read_text())
def cases(name):
    rows=list(ET.parse(packet/name).getroot().iter('testcase'))
    return {(r.get('classname'),r.get('name')):('failure' if r.find('failure') is not None else 'error' if r.find('error') is not None else 'skipped' if r.find('skipped') is not None else 'passed') for r in rows}, rows
out={'schema':'root-independent-publication-review-v1','created_utc':datetime.now(timezone.utc).isoformat(),'reviewer':'root; independent inspection of underlying archived receipts','scope':'Completed native106 failure and static diagnosis only; no numerical pass authority','native_runs':0}
try:
    check('independently pinned manifest',digest(packet/'artifact-manifest.json')=='ea58aee86610dd917a3c44901bad53a7082665efd756cb43f783503c55ce9b4b')
    manifest=read('artifact-manifest.json')
    listed={r['path'] for r in manifest['files']}
    check('exact54 inventory',len(listed)==54 and listed=={str(p.relative_to(packet)) for p in packet.rglob('*') if p.is_file()}-{'artifact-manifest.json'})
    for row in manifest['files']:
        p=packet/row['path']
        check('artifact '+row['path'],p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(packet.resolve()) and p.stat().st_size==row['bytes'] and digest(p)==row['sha256'])
    for row in read('provenance.json')['files']:
        check('direct original '+row['path'],Path(row['original_path']).read_bytes()==(packet/row['path']).read_bytes())
    current, rows=cases('evidence/current/tests.xml')
    check('106 unique tests',len(current)==len(rows)==106)
    check('102pass4fail',list(current.values()).count('passed')==102 and list(current.values()).count('failure')==4)
    failed={name for (cl,name),status in current.items() if status=='failure'}
    expected={f'test_native_nuisance_search_is_transactional[{m}]' for m in ('reject','support','exception')}|{'test_native_empirical_nuisance_floor_requires_independent_audits[floor_zero_replay-zero_update_replay_failed]'}
    check('exact four failures',failed==expected)
    for row in rows:
        if row.find('failure') is not None:
            text=row.find('failure').text or ''
            check('17 versus0 '+row.get('name'),'17' in text and '0' in text and 'trials' in text)
    for prior in ('remote106','local106'):
        cs,rs=cases('evidence/prior/'+prior+'/tests.xml')
        check(prior+' same106 allpass',set(cs)==set(current) and len(rs)==106 and set(cs.values())=={'passed'})
    cs,rs=cases('evidence/prior/fail-fast37/tests.xml')
    check('independent37 prior allpass',len(cs)==len(rs)==37 and set(cs.values())=={'passed'})
    plan=read('evidence/current/correctness-plan.json')
    flag='ORBIT_POC_NUISANCE_FAIL_FAST_REPLAY'
    check('exact frozen plan',digest(packet/'evidence/current/correctness-plan.json')=='aca653aae8ae8c712defdc74b550e43be013552e26aebf9cc454f30757df8e95')
    check('current original106 opt-in1',plan['jobs'][0]['stage']=='native-tests' and plan['jobs'][0]['environment'][flag]=='1')
    check('old local flag absent',flag not in read('evidence/prior/local106/freeze.json')['environment'])
    remote=read('evidence/prior/remote106/supervisor.plan.json')['argv']
    check('old remote clearenv and flag absent','--clearenv' in remote and flag not in remote)
    source=(packet/'evidence/source/groops/extension/nuisanceLineSearch.h').read_text()
    check('parser default zero','const std::string value=raw?raw:"0";' in source)
    source_test=(packet/'evidence/source/tests/test_native_nuisance_fail_fast.py').read_text()
    check('explicit0versus17 tested','(0 if flag == "1" else 17)' in source_test)
    for mode in ('reject','support','exception','floor_zero_replay'):
        d=read('evidence/current/fixtures/'+mode+'/search.json')
        check('replay failure rejected before trials '+mode,d['trials']==[] and d['floor_rejection']=='zero_update_replay_failed' and d['accepted'] is False and d['nuisance_floor_limited'] is False)
        check('parent preserved '+mode,(packet/'evidence/current/fixtures'/mode/'qr.parent.txt').read_bytes()==b'parent\npreserved\n')
    strict=read('evidence/current/strict-result.json'); sup=read('evidence/current/supervisor.json'); report=read('report.json')
    check('terminal process failed',sup['status']=='failed' and sup['returncode']==1 and sup['cleanup']['verified'] is True and not sup['cleanup']['remaining'])
    check('strict and report remain failed',strict['status']==report['status']=='failed' and strict['returncode']==1 and report['failed_gate_reclassified'] is False)
    check('report count actual',report['tests']==106 and report['passed']==102 and report['failures']==4 and report['errors']==report['skips']==0)
    check('no convergence release or covariance authority',all(report[k] is False and strict[k] is False for k in ('full_fit_verified','covariance_authority','release_authority')))
    check('remaining gates not certified',report['remaining_current_stages'].startswith('not certified'))
    check('cold gate closed',report['cold_fit_gate'].startswith('must remain closed'))
    check('runtime identity appropriately bounded',report['complete_runtime_identity_claimed'] is False)
    check('source identity both independent audits',read('evidence/history-audit/history-audit.json')['passed_history_consistency_checks'] is True and read('evidence/independent-audit/findings.json')['diagnosis_supported'] is True)
    check('repairs explicitly separate',report['repair_status'].startswith('Separately versioned controls-only repair proposed'))
    out['passed']=True
except Exception as error:
    out['passed']=False; out['error']=repr(error)
out.update(check_count=len(checks),checks=checks,manifest_sha256=digest(packet/'artifact-manifest.json'))
with (root/'root-audit01.json').open('x') as f: json.dump(out,f,indent=2); f.write('\n')
print(json.dumps({k:v for k,v in out.items() if k!='checks'}))
raise SystemExit(0 if out['passed'] else 1)
