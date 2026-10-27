"""Collect unchanged small receipts; never launch a fit or modify source evidence."""
from pathlib import Path
import csv, datetime, hashlib, html, json, shutil
from zoneinfo import ZoneInfo

B = Path('/mnt/d/orbit-v41-recovery02')
R = B / 'reference-gates14-run01'
P = B / 'publication14-01/packet'
inventory = []

def read(p):
    return json.loads(Path(p).read_text())

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

# The approval binds completed independent audit bytes, not the existence of drafts.
approval_path = B / 'publication14-01/approved-audits.json'
approval = read(approval_path)
assert set(approval['audits']) == {'terminal', 'objective_math'}
for role, identity in approval['audits'].items():
    assert sha(identity['path']) == identity['sha256'], role
    audit = read(identity['path'])
    assert audit.get('approved', audit.get('passed')) is True, role
    assert audit['checks'] and all(c['passed'] for c in audit['checks']), role
    assert len(audit['checks']) == audit.get('checks_count', audit.get('check_count')), role
P.mkdir(parents=True, exist_ok=False)

def copy(p, dest=None):
    p = Path(p)
    if dest is None:
        dest = 'evidence/' + str(p.relative_to(B))
    target = P / dest
    if target.exists():
        assert sha(target) == sha(p), str(target)
        return
    assert p.is_file() and p.stat().st_size < 5_000_000, str(p)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(p, target)
    inventory.append({'source': str(p), 'path': dest, 'bytes': p.stat().st_size, 'sha256': sha(p)})

terminal = read(R / 'result.json')
assert terminal['all_eight_strict_passed'] and len(terminal['stages']) == 8
copy(approval_path, 'approved-audits.json')
for name in ['plan.json', 'freeze.json', 'result.json', 'detached-result.json', 'detached-started.json', 'run-started.json', 'python-runtime.json', 'storage.json']:
    copy(R / name)
for name in ['preflight-result.json', 'preflight-execution.json', 'validation-inputs.json']:
    copy(R / 'prepared' / name)
rows = []
for stage in terminal['planned_stages']:
    d = R / stage
    strict = read(d / 'strict-result.json')
    supervisor = read(d / 'supervisor.json')
    assert strict['status'] == 'passed' and supervisor['returncode'] == 0 and supervisor['cleanup']['verified']
    result = Path(strict['evidence']['result']['path'])
    assert sha(result) == strict['evidence']['result']['sha256']
    for name in ['strict-result.json', 'supervisor.json', 'supervisor.plan.json', 'admission.json']:
        copy(d / name)
    copy(result)
    detail = read(result)
    for evaluation in detail.get('profile_evaluations', []):
        p = Path(evaluation['receipt'])
        copy(p)
        for q in p.parent.glob('qr.*.profile.json'):
            copy(q)
        for q in p.parent.glob('qr.*.nuisance_line_search.json'):
            copy(q)
        for name in ['profile.execution.json', 'closure.json']:
            if (p.parent / name).exists(): copy(p.parent / name)
    if stage.startswith('nuisance-replay'):
        for p in (d / 'result').glob('*.json'):
            copy(p)
        for p in (d / 'result').glob('*.xml'):
            copy(p)
    rows.append({'stage': stage, 'status': strict['status'], 'scientific_seconds': strict['scientific_command_seconds'],
                 'worker_total_seconds': strict['worker_total_seconds'], 'supervised_seconds': supervisor['elapsed_seconds'],
                 'peak_process_tree_rss_bytes': supervisor['peak_process_tree_rss_bytes'],
                 'cleanup_verified': supervisor['cleanup']['verified'], 'evidence': strict['evidence'],
                 'receipt_written_at': datetime.datetime.fromtimestamp((d/'strict-result.json').stat().st_mtime, ZoneInfo('Europe/Berlin')).isoformat()})

# Small frozen controls and independent reviews; large source datasets stay external.
for directory in ['validation-controls07', 'terminal-audit14-01', 'next-full-fit-plan01']:
    for p in sorted((B / directory).rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts and p.suffix in {'.json', '.py', '.md', '.txt', '.xml', '.log', '.csv'}:
            copy(p)
# Carry audit-selected small evidence without moving large raw row/trajectory archives into Git.
external = []
audited = read(B/'terminal-audit14-01/evidence-inventory.json')['entries']
for e in audited:
    p = Path(e['path'])
    allowed = e.get('copy_recommended', e.get('copy_eligible', False))
    text_file = p.suffix in {'.json','.xml','.py','.md','.txt','.tsv','.cpp','.h','.log','.patch'}
    row_spool = '.rows.' in p.name or p.name.endswith('.rows.tsv')
    if allowed and text_file and not row_spool and e['bytes'] < 5_000_000:
        assert sha(p) == e['sha256'], str(p)
        dest = None if p.is_relative_to(B) else 'evidence/external/'+e['sha256'][:16]+'-'+p.name
        copy(p, dest)
    else:
        external.append(e)
(P/'external-evidence.json').write_text(json.dumps({'scope':'Audit-used evidence retained outside Git; exact historical locators and identities, not missing validation results','files':external},indent=2)+'\n')
for rel in [
    'validation-review04/controls07-review01.json', 'validation-review04/manifest14-semantic-review01.json',
    'validation-review04/recovery14-launch-review01.json', 'preparation05/result.json',
    'interruption-audit/interruption.json', 'reference-gates12-run01/result.json',
    'reference-gates12-run01/detached-result.json', 'reference-gates12-run01/freeze.json',
    'status-audit-20261023-01/recovered-validation-audit02.json',
    'reference-gates13-run01/plan.json', 'preparation04/result.json',
    'validation-review04/recovery13-preflight-failure-summary01.json',
    'timeout-audit/audit.json', 'timeout-audit/summary.csv',
    'gnss-timeout-audit01/audit.json', 'gnss-timeout-audit01/summary.csv',
    'gnss-timeout-audit01/frozen-pair-report.json', 'gnss-timeout-audit01/final-integrity-audit.json',
    'gnss-timeout-audit01/manifest.json']:
    copy(B / rel)
for stage in ['objective-log_drag_ou', 'objective-pulses']:
    for name in ['strict-result.json', 'supervisor.json', 'result/validation.json']:
        copy(B / 'reference-gates12-run01' / stage / name)
C = Path('/mnt/d/orbit-v41-recovery01/candidate04')
for name in ['source-snapshot.json', 'candidate04-source-patch.json', 'candidate04-from-4bc693b.patch', 'build-result04.json', 'build-plan04.json']:
    copy(C / name, 'evidence/candidate04/' + name)
copy(C / 'binaries/groops-v41-28c725765201e470.build-manifest.json', 'evidence/candidate04/native-build-manifest.json')
copy(B / 'publication14-01/base-ffddebb-to-4bc693b.patch', 'evidence/candidate04/base-ffddebb-to-4bc693b.patch')
copy(Path(__file__), 'build_packet.py')
copy(B / 'publication14-01/audit-guard-tests.json', 'audit-guard-tests.json')

report = {'schema': 'orbit-poc-eight-check-publication-v1', 'published_scope': 'Candidate04 reference-preservation checks only',
          'independent_audits': approval['audits'],
          'run': str(R), 'native_sha256': '28c725765201e4702875ec8407d3bc497aa4bdfa3092a305b15a3233cfbd675d',
          'plan_sha256': sha(R/'plan.json'), 'freeze_sha256': sha(R/'freeze.json'),
          'counts': {'planned': 8, 'passed': 8, 'failed': 0}, 'stages': rows,
          'objective_profiles': {'density': 22, 'pulses': 10, 'all_strict': True, 'floor_limited': 0},
          'whole_fit_verified': False, 'accepted_covariance': False, 'release_authority': False,
          'new_native_runs_launched_for_publication': False,
          'frozen_benchmark_results_replaced': False,
          'timing_scope': 'Stage totals include substantial identity/inventory I/O; these are not fit speed comparisons.',
          'external_artifacts': 'Original datasets, binaries, trajectories and large row archives stay outside Git; exact source locators and hashes remain in the copied receipts.'}
(P/'report.json').write_text(json.dumps(report, indent=2)+'\n')
with (P/'summary.csv').open('w', newline='') as f:
    cols=['stage','status','scientific_seconds','worker_total_seconds','supervised_seconds','peak_process_tree_rss_bytes','cleanup_verified','receipt_written_at']
    w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(rows)
(P/'source-map.json').write_text(json.dumps({'scope':'Copied evidence bytes are unchanged; source paths are historical locators, not portable clickable links. Use this map to locate their packaged equivalents.','files':inventory},indent=2)+'\n')
print(json.dumps({'packet':str(P),'copied_files':len(inventory),'copied_bytes':sum(x['bytes'] for x in inventory)}))
