"""Offline thin-packet fixtures. No scientific checker, fit, or live data access."""
import hashlib
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[1]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value)
    return pin(path)


def pin(path):
    data = path.read_bytes()
    return {'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


@pytest.fixture
def example(tmp_path):
    spec = importlib.util.spec_from_file_location('warm_report_test', ROOT/'scripts/report_nuisance_warm_profiles.py')
    m = importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    data = tmp_path/'experiment';data.mkdir()
    jobs = []
    for group in ('pulses', 'density', 'pulses-bias-priors'):
        for case in m.CASES:
            job_id = group+'--'+case;root = data/job_id;root.mkdir()
            config = write(root/'config.xml','<fixture/>')
            jobs.append({'id':job_id,'group':group,'root':str(root),'point':'source',
                         'treatment':'warm' if case.startswith('warm') else 'cold_export',
                         'mode':'receiver_clock_signal_float_v1','profile_sha256':config['sha256'],
                         'input_inventory':[{'path':str(tmp_path/'never-read-input.bin'),'bytes':999,'sha256':'a'*64}]})
    deps = {k:write(tmp_path/'protocol'/(k+'.json'),{'fixture':k}) for k in
            ('preparation','build_record','runner','checker','supervisor')}
    freeze = {'schema':m.FREEZE,'jobs':jobs,'execution_order':[j['id'] for j in jobs],**deps}
    frozen = data/'freeze.json';freeze_pin = write(frozen,freeze)
    for j in jobs:
        root = Path(j['root'])
        sup = write(root/'supervisor.json',{'status':'complete','owned_process_group_cleaned':True,
                    'peak_process_tree_rss_bytes':2048,'cleanup':{'verified':True,'remaining':[],'empty_tree_certificate':'kernel_ECHILD'}})
        write(root/'qr.profile.json',{'nuisance_converged':True,'nuisance_floor_limited':False,'iterations':2})
        write(root/'qr.3.diagnostics.json',{'rank_status':'full'})
        write(root/'qr.3.parameters.tsv','index\tname\n0\tclock\n')
        write(root/'qr.3.bias_coordinates.tsv','coordinate\tvalue\n0\t0.1\n')
        write(root/'profile.log','completed fixture\n')
        write(root/'qr.3.rows.tsv','BULK ROW FILE MUST NOT BE READ\n')
        (root/'qr.3.R.bin').write_bytes(b'BULK MATRIX MUST NOT BE READ')
        outputs = [{**pin(p),'path':p.name} for p in root.iterdir() if p.is_file()]
        ex = {'schema':'orbit-poc-nuisance-warm-profile-execution-v1','freeze':freeze_pin,'job_id':j['id'],
              **{k:j[k] for k in ('group','point','treatment','mode','input_inventory')},
              'status':'complete','elapsed_seconds':1.5,'owned_process_group_cleaned':True,
              'supervisor_sha256':sup['sha256'],'output_inventory':outputs}
        write(root/'execution.json',ex)
    checks = tmp_path/'checks';checks.mkdir()
    by_id = {j['id']:j for j in jobs}
    for group in ('pulses','density','pulses-bias-priors'):
        for name, labels in m.CHECKS.items():
            chosen = [by_id[group+'--'+case] for case in labels]
            result = {'schema':m.CHECK,'roots':[j['root'] for j in chosen],
                      'release_authority':False,'accepted_orbit_covariance':False,'passed':True,
                      'checker_sha256':deps['checker']['sha256'],
                      'execution_receipts':[{'root':j['root'],'freeze':freeze_pin,
                          'sha256':pin(Path(j['root'])/'execution.json')['sha256']} for j in chosen],
                      'checks':{'existing_scientific_criterion':True},
                      'relative_dynamic_covariance_difference':1e-10}
            write(checks/(group+'--'+name+'.json'),result)
    native = tmp_path/'native-tests/result.json'
    results = []
    for suite, count in (('native',106),('correction',51)):
        result = {'suite':suite,'counts':{'tests':count,'failure':0,'error':0,'skipped':0},'passed':True,'execution':{'status':'complete','owned_process_group_cleaned':True}}
        results.append(result)
        for name,content in (('tests.xml','<testsuites/>'),('pytest.log','passed fixture\n'),('supervisor.json',{'status':'complete'}),('result.json',result)):
            write(native.parent/suite/name,content)
    write(native,{'passed':True,'results':results})
    failed = tmp_path/'history/candidate-build-result02.json';write(failed,{'execution':{'status':'failed','returncode':1},'cause':'actual Vector compile failure'})
    args = SimpleNamespace(freeze=frozen,checks=checks,native_tests=native,output=tmp_path/'packet',evidence=[failed],outcome_audit=None)
    return SimpleNamespace(m=m,args=args,freeze=freeze,jobs=jobs,checks=checks,native=native,failed=failed,tmp=tmp_path)


def result(e):
    return e.m.report(e.args)


def test_all27_attempts15_checker_results_and_no_new_authority(example,monkeypatch):
    e=example;original=e.m.read_bytes
    def bounded(path):
        assert not str(path).endswith(('.rows.tsv','.bin'))
        return original(path)
    monkeypatch.setattr(e.m,'read_bytes',bounded)
    r=result(e)
    assert len(r['attempts'])==27 and len(r['checks'])==15
    assert r['attempt_counts']=={'complete':27} and r['check_counts']=={'passed':15}
    assert not any(r[k] for k in ('release_authority','accepted_orbit_covariance','whole_fit_convergence_claim','speedup_claim'))
    assert r['independent_outcome_audit']=={'status':'pending'}
    assert all(x['profile_iterations']==2 and x['native_wall_seconds']==1.5 and x['peak_process_tree_rss_bytes']==2048 for x in r['attempts'])
    assert 'PR #6' in (e.args.output/'index.html').read_text()
    assert not any(p.suffix=='.bin' or p.name.endswith('.rows.tsv') for p in e.args.output.rglob('*'))
    assert (e.args.output/'evidence/000-candidate-build-result02.json').read_bytes()==e.failed.read_bytes()
    manifest=json.loads((e.args.output/'manifest.json').read_text())
    assert {x['path'] for x in manifest['files']}=={str(p.relative_to(e.args.output)) for p in e.args.output.rglob('*') if p.is_file() and p.name!='manifest.json'}
    for record in manifest['files']:
        p=e.args.output/record['path'];assert pin(p)['sha256']==record['sha256'] and p.stat().st_size==record['bytes']
    with pytest.raises(FileExistsError):result(e)


@pytest.mark.parametrize('kind',['missing','running','unclean','malformed','wrong_freeze','changed_config','changed_profile'])
def test_missing_invalid_or_unclosed_attempts_cannot_disappear_or_pass(example,kind,monkeypatch):
    e=example;j=e.jobs[0];root=Path(j['root']);path=root/'execution.json'
    if kind in ('missing','running'):path.unlink()
    if kind=='missing':(root/'supervisor.json').unlink()
    if kind=='running':write(root/'supervisor.json',{'status':'running','owned_process_group_cleaned':False})
    if kind=='unclean':
        ex=json.loads(path.read_text());ex['owned_process_group_cleaned']=False;write(path,ex)
    if kind=='malformed':path.write_text('{broken')
    if kind=='wrong_freeze':
        ex=json.loads(path.read_text());ex['freeze']['sha256']='f'*64;write(path,ex)
    if kind=='changed_config':(root/'config.xml').write_text('changed')
    if kind=='changed_profile':(root/'qr.profile.json').write_text('{}')
    if kind in ('missing','running','unclean'):
        original=e.m.read_bytes
        def protected(p):
            assert not (Path(p).parent==root and (Path(p).name.startswith('qr.') or Path(p).name=='profile.log'))
            return original(p)
        monkeypatch.setattr(e.m,'read_bytes',protected)
    r=result(e);assert len(r['attempts'])==27 and len(r['checks'])==15
    affected=next(x for x in r['attempts'] if x['id']==j['id'])
    assert affected['status']!='complete' or affected.get('owned_closure_reported') is False
    assert all(x['status']!='passed' for x in r['checks'] if j['id'] in x['jobs'])


@pytest.mark.parametrize('kind',['missing','failed','wrong_checker','wrong_receipt','duplicate','wrong_authority','nonboolean','bad_json'])
def test_checker_decision_preserved_or_explicitly_unavailable(example,kind):
    e=example;p=e.checks/'pulses--warm-target-full.json';v=json.loads(p.read_text())
    if kind=='missing':p.unlink()
    elif kind=='failed':v.update(passed=False,error='measured criterion failure');write(p,v)
    elif kind=='wrong_checker':v['checker_sha256']='0'*64;write(p,v)
    elif kind=='wrong_receipt':v['execution_receipts'][0]['sha256']='0'*64;write(p,v)
    elif kind=='duplicate':write(e.checks/'duplicate.json',v)
    elif kind=='wrong_authority':v['accepted_orbit_covariance']=True;write(p,v)
    elif kind=='nonboolean':v['passed']=1;write(p,v)
    else:p.write_text('{bad')
    r=result(e);item=next(x for x in r['checks'] if x['id']=='pulses--warm-target-full')
    assert item['status']!='passed'
    if kind=='failed':assert item['result']==v and item['status']=='failed'


@pytest.mark.parametrize('kind',['missing_jobs','duplicate_order','output_inside_attempt','evidence_directory','evidence_binary','symlink_profile'])
def test_unsafe_or_incomplete_protocol_and_copy_inputs_reject(example,kind):
    e=example
    if kind in ('missing_jobs','duplicate_order'):
        f=json.loads(e.args.freeze.read_text())
        if kind=='missing_jobs':f['jobs'].pop()
        else:f['execution_order'][0]=f['execution_order'][1]
        write(e.args.freeze,f)
    elif kind=='output_inside_attempt':e.args.output=Path(e.jobs[0]['root'])/'new-report'
    elif kind=='evidence_directory':e.args.evidence=[e.failed.parent]
    elif kind=='evidence_binary':e.args.evidence=[Path(e.jobs[0]['root'])/'qr.3.R.bin']
    elif kind=='symlink_profile':
        p=Path(e.jobs[0]['root'])/'qr.profile.json';other=e.tmp/'other.json';other.write_bytes(p.read_bytes());p.unlink();p.symlink_to(other)
        r=result(e);assert r['attempts'][0]['status']=='invalid_evidence';return
    with pytest.raises((ValueError,FileExistsError)):result(e)


def test_supplied_audit_is_attributed_without_granting_release(example):
    e=example;audit=e.tmp/'audit.json';write(audit,{'decision':'accepted','scope':'fixture only'})
    e.args.outcome_audit=audit;r=result(e)
    assert r['independent_outcome_audit']['status']=='supplied_separately'
    assert r['independent_outcome_audit']['declared_receipt']['decision']=='accepted'
    assert r['release_authority'] is False


def test_html_escapes_evidence_and_preserves_failed_native_test(example):
    e=example;v=json.loads(e.native.read_text());v['passed']=False;v['results'][0]['counts']['failure']=1;v['note']='<script>BAD()</script>';write(e.native,v)
    r=result(e);page=(e.args.output/'index.html').read_text()
    assert r['native_tests']==v and '&lt;script&gt;' in page and '<script>BAD()' not in page


@pytest.mark.parametrize('status',['blocked','timeout','failed','memory_limit','interrupted'])
def test_all_terminal_native_failures_remain_planned_rows(example,status):
    e=example;p=Path(e.jobs[0]['root'])/'execution.json';v=json.loads(p.read_text());v['status']=status;write(p,v)
    r=result(e);assert r['attempts'][0]['status']==status and len(r['attempts'])==27
    assert not any(c['status']=='passed' for c in r['checks'] if e.jobs[0]['id'] in c['jobs'])


@pytest.mark.parametrize('target',['execution','native_tests','checker'])
def test_nonobject_evidence_is_explicit_not_a_success(example,target):
    e=example
    p=Path(e.jobs[0]['root'])/'execution.json' if target=='execution' else e.native if target=='native_tests' else e.checks/'pulses--warm-target-full.json'
    write(p,[]);r=result(e)
    if target=='execution':assert r['attempts'][0]['status']=='invalid_evidence'
    elif target=='native_tests':assert 'invalid_evidence' in r['native_tests']
    else:assert next(c for c in r['checks'] if c['id']=='pulses--warm-target-full')['status']!='passed'


def test_unclosed_native_test_logs_are_never_read(example,monkeypatch):
    e=example;v=json.loads(e.native.read_text());v['results'][0]['execution']['owned_process_group_cleaned']=False;write(e.native,v)
    original=e.m.read_bytes
    def protected(p):
        assert Path(p).parent != e.native.parent/'native'
        return original(p)
    monkeypatch.setattr(e.m,'read_bytes',protected);r=result(e)
    assert any('test closure unavailable' in x['error'] for x in r['issues'])


def test_copied_source_change_is_recorded_before_packet_completion(example,monkeypatch):
    e=example;original=e.m.read_bytes;reads=0
    def unstable(p):
        nonlocal reads
        if Path(p)==e.failed:
            reads+=1
            if reads==2:write(e.failed,{'changed':True})
        return original(p)
    monkeypatch.setattr(e.m,'read_bytes',unstable);r=result(e)
    assert any('changed before packet completion' in x['error'] for x in r['issues'])


def test_thin_file_size_limit_rejects_before_output_creation(example,monkeypatch):
    e=example;monkeypatch.setattr(e.m,'LIMIT',1)
    with pytest.raises(ValueError,match='size limit'):result(e)
    assert not e.args.output.exists()


@pytest.mark.parametrize('audit_decision',[{'decision':'accepted'},{'passed':True},{'status':'pending'}])
def test_large_receipts_are_collapsed_and_audit_lead_cannot_infer_acceptance(example,audit_decision):
    e=example;marker='LARGE_AUDIT_PAYLOAD_'+('x'*20000)
    audit={**audit_decision,'inventory':marker};path=e.tmp/'independent-audit.json';write(path,audit);e.args.outcome_audit=path
    build=json.loads(e.failed.read_text());build['source_inventory']='LARGE_BUILD_INVENTORY_'+('y'*20000);write(e.failed,build)
    checkpath=e.checks/'pulses--warm-target-full.json';check=json.loads(checkpath.read_text())
    check['full_diagnostic_inventory']='LARGE_CHECKER_INVENTORY_'+('z'*20000);check['objective_difference']=1e-12;write(checkpath,check)
    r=result(e);page=(e.args.output/'index.html').read_text()
    class Visible(HTMLParser):
        def __init__(self):super().__init__();self.depth=0;self.visible=[];self.audit=[];self.in_audit=False
        def handle_starttag(self,tag,attrs):
            if tag=='details':self.depth+=1
            if tag=='p' and dict(attrs).get('id')=='outcome-audit':self.in_audit=True
        def handle_endtag(self,tag):
            if tag=='details':self.depth-=1
            if tag=='p':self.in_audit=False
        def handle_data(self,text):
            if not self.depth:self.visible.append(text)
            if self.in_audit:self.audit.append(text)
    view=Visible();view.feed(page);visible=''.join(view.visible);lead=''.join(view.audit)
    assert len(lead)<600 and 'full audit receipt' in lead
    assert 'LARGE_AUDIT_PAYLOAD_' not in page
    assert 'LARGE_BUILD_INVENTORY_' not in visible and 'LARGE_CHECKER_INVENTORY_' not in visible
    assert 'LARGE_BUILD_INVENTORY_' in page and 'LARGE_CHECKER_INVENTORY_' in page
    assert 'Objective difference: 1e-12' in visible
    assert ('receipt explicitly declares acceptance' in lead)==(audit_decision.get('decision')=='accepted')
    assert 'no release authority' in lead and r['release_authority'] is False
    assert json.loads((e.args.output/'evidence/independent-outcome-audit.json').read_text())==audit
    assert next(c for c in r['checks'] if c['id']=='pulses--warm-target-full')['result']==check
