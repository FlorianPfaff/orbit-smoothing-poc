#!/usr/bin/env python3
"""Package thin fixed-trajectory nuisance evidence; never run a checker or fit.

Required: --freeze FILE --checks DIR --native-tests FILE --output NEW_DIR.
Use repeated --evidence FILE for build failures, reviews, source/control snapshots
and logs. No directory traversal/copy is performed for optional evidence. Large
datasets, row spools, matrix binaries and seed payloads stay outside the packet;
their declared pins remain in the copied inventories. --outcome-audit preserves
a separately supplied audit; this reporter never grants release authority.
"""
from __future__ import annotations
import argparse
from collections import Counter
import datetime
import hashlib
import html
import json
import math
from pathlib import Path
import re

FREEZE = 'orbit-poc-nuisance-warm-profile-freeze-v1'
CHECK = 'orbit-poc-nuisance-warm-fixed-profile-check-v1'
CASES = ('disabled_source', 'cold_source_full', 'cold_source_repeat_full',
         'warm_source_full', 'cold_target_full', 'cold_target_repeat_full',
         'warm_target_full', 'cold_source_clock', 'warm_target_clock')
CHECKS = {
    'inert-full': ('disabled_source', 'cold_source_full'),
    'inert-clock': ('disabled_source', 'cold_source_clock'),
    'warm-source-full': ('cold_source_full', 'warm_source_full', 'cold_source_repeat_full'),
    'warm-target-full': ('cold_target_full', 'warm_target_full', 'cold_target_repeat_full'),
    'warm-target-clock': ('cold_target_full', 'warm_target_clock', 'cold_target_repeat_full'),
}
TERMINAL = {'complete', 'failed', 'timeout', 'memory_limit', 'disk_limit',
            'interrupted', 'identity_failure', 'blocked', 'internal_error'}
LIMIT = 16 * 1024**2
PACKET_LIMIT = 128 * 1024**2


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read_bytes(path):
    path = Path(path).absolute()
    require(path.resolve(strict=True) == path and path.is_file() and not path.is_symlink(),
            'Missing/nonregular/symlink evidence: ' + str(path))
    a = path.stat()
    require(a.st_size <= LIMIT, 'Thin-evidence size limit exceeded: ' + str(path))
    data = path.read_bytes()
    b = path.stat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    require(identity(a) == identity(b) and len(data) == a.st_size,
            'Evidence changed during read: ' + str(path))
    return data, {'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def decode(data):
    def pairs(items):
        out = {}
        for k, v in items:
            require(k not in out, 'Duplicate JSON key: ' + k)
            out[k] = v
        return out
    def number(value):
        result = float(value)
        require(math.isfinite(result), 'Nonfinite JSON number')
        return result
    def invalid(value):
        raise ValueError('Nonfinite JSON constant: ' + value)
    return json.loads(data, object_pairs_hook=pairs, parse_float=number, parse_constant=invalid)


def native_number(value):
    return value if type(value) in (float, int) and math.isfinite(value) and value >= 0 else None


class Packet:
    def __init__(self, root):
        self.root = root
        self.files = []
        self.issues = []
        self.bytes = 0

    def write(self, relative, data, source=None):
        relative = Path(relative)
        require(not relative.is_absolute() and '..' not in relative.parts, 'Unsafe packet path')
        require(self.bytes + len(data) <= PACKET_LIMIT, 'Thin packet size limit exceeded')
        dest = self.root / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open('xb') as stream:
            stream.write(data)
        self.bytes += len(data)
        record = {'path': relative.as_posix(), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        if source is not None:
            record['source'] = source
        self.files.append(record)
        return record

    def json(self, relative, value):
        return self.write(relative, (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode())

    def copy(self, path, relative, *, expected=None, optional=False):
        try:
            data, pin = read_bytes(path)
            if expected is not None:
                require(pin['sha256'] == expected['sha256'] and
                        ('bytes' not in expected or pin['bytes'] == expected['bytes']),
                        'Copied evidence differs from declared pin: ' + str(path))
            return self.write(relative, data, pin), data
        except (ValueError, OSError) as error:
            if not optional or Path(path).exists() or Path(path).is_symlink():
                self.issues.append({'path': str(path), 'error': str(error)})
            return None, None


def collect_job(packet, job, freeze_pin):
    initial_issues = len(packet.issues)
    root = Path(job['root'])
    prefix = 'attempts/' + job['id'] + '/'
    row = {k: job[k] for k in ('id', 'group', 'point', 'treatment', 'mode')}
    row.update(status='missing', declared_status=None, receipt_integrity='unavailable',
               strict_nuisance_reported=None, profile_iterations=None,
               native_wall_seconds=None, peak_process_tree_rss_bytes=None,
               accepted_orbit_covariance=False, issues=[], evidence=[])
    config, _ = packet.copy(root/'config.xml', prefix+'config.xml', expected={'sha256': job['profile_sha256']})
    if config:
        row['evidence'].append(config['path'])
    ex_record, ex_bytes = packet.copy(root/'execution.json', prefix+'execution.json', optional=True)
    if ex_bytes is None:
        if (root/'execution.json').exists():
            row.update(status='invalid_evidence', receipt_integrity='invalid')
        else:
            # Only a small control receipt is observed. No live profile/logs are read.
            sup_record, sup_bytes = packet.copy(root/'supervisor.json', prefix+'supervisor.json', optional=True)
            if sup_bytes is not None:
                try:
                    value = decode(sup_bytes)
                    require(isinstance(value,dict), 'Supervisor receipt must be an object')
                    row['declared_status'] = value.get('status')
                    row['status'] = 'running_or_unclosed' if value.get('status') not in TERMINAL else 'unclosed_terminal_receipt'
                    row['evidence'].append(sup_record['path'])
                except (ValueError, TypeError):
                    row['status'] = 'invalid_evidence'
        return row
    row['execution_sha256'] = ex_record['sha256']
    row['evidence'].append(ex_record['path'])
    try:
        ex = decode(ex_bytes)
        require(isinstance(ex,dict), 'Execution receipt must be an object')
        row['declared_status'] = ex.get('status')
        require(config is not None, 'Frozen config was not copied intact')
        require(ex['schema'] == 'orbit-poc-nuisance-warm-profile-execution-v1', 'Unknown execution schema')
        require(ex['freeze'] == freeze_pin and ex['job_id'] == job['id'], 'Wrong execution freeze/job')
        require(all(ex[k] == job[k] for k in ('group', 'point', 'treatment', 'mode')), 'Wrong execution assignment')
        require(ex['status'] in TERMINAL, 'Execution receipt is not terminal')
        require(ex['input_inventory'] == job['input_inventory'], 'Input inventory attribution differs')
        row['status'] = ex['status']
        row['receipt_integrity'] = 'attributed_control_receipt'
        row['native_wall_seconds'] = native_number(ex.get('elapsed_seconds'))
        outputs = ex.get('output_inventory', [])
        require(isinstance(outputs, list), 'Malformed output inventory')
        inventory = {}
        for item in outputs:
            p = Path(item['path'])
            require(not p.is_absolute() and '..' not in p.parts and str(p) not in inventory, 'Unsafe/duplicate output inventory')
            inventory[str(p)] = item
        # A terminal parent alone does not certify descendant closure.
        closed = ex.get('owned_process_group_cleaned') is True
        sup_rec, sup_data = packet.copy(root/'supervisor.json', prefix+'supervisor.json',
                                       expected={'sha256': ex['supervisor_sha256']})
        if sup_rec:
            row['evidence'].append(sup_rec['path'])
        if sup_data is None:
            closed = False
        else:
            sup = decode(sup_data)
            require(isinstance(sup,dict), 'Supervisor receipt must be an object')
            row['peak_process_tree_rss_bytes'] = native_number(sup.get('peak_process_tree_rss_bytes'))
            closed = closed and sup.get('owned_process_group_cleaned') is True
            if ex['status'] != 'blocked':
                cleanup = sup.get('cleanup', {})
                require(isinstance(cleanup,dict), 'Malformed cleanup receipt')
                closed = closed and cleanup.get('verified') is True and cleanup.get('remaining') == [] and cleanup.get('empty_tree_certificate') == 'kernel_ECHILD'
        row['owned_closure_reported'] = closed
        if not closed:
            row['issues'].append('Owned-process closure is not certified; profile and log files were not read.')
            return row
        thin = ['admission.json', 'supervisor.plan.json', 'profile.log', 'qr.profile.json', 'seed.bin.json']
        profile = None
        for name in thin:
            if name not in inventory:
                continue
            rec, data = packet.copy(root/name, prefix+name, expected=inventory[name])
            if rec:
                row['evidence'].append(rec['path'])
            if data is not None and name == 'qr.profile.json':
                profile = decode(data)
                require(isinstance(profile,dict), 'Profile receipt must be an object')
                row['strict_nuisance_reported'] = profile.get('nuisance_converged') is True and profile.get('nuisance_floor_limited') is False
                count = profile.get('iterations')
                row['profile_iterations'] = count if type(count) is int and count >= 0 else None
        if profile is not None and row['profile_iterations'] is not None:
            # Final stem follows the native fresh-pass convention; diagnostics
            # are copied as evidence, never independently accepted as covariance.
            stem = 'qr.' + str(row['profile_iterations'] + 1)
            for suffix in ('diagnostics.json', 'factor.json', 'parameters.tsv', 'bias_coordinates.tsv', 'nuisance_coordinates.tsv'):
                name = stem + '.' + suffix
                if name in inventory:
                    rec, _ = packet.copy(root/name, prefix+name, expected=inventory[name])
                    if rec:
                        row['evidence'].append(rec['path'])
    except (KeyError, ValueError, TypeError) as error:
        row.update(status='invalid_evidence', receipt_integrity='invalid')
        row['issues'].append(str(error))
    if len(packet.issues) != initial_issues:
        row.update(status='invalid_evidence', receipt_integrity='invalid')
        row['issues'].extend(packet.issues[initial_issues:])
    return row


def collect_checks(packet, directory, jobs, rows, freeze_pin, checker_pin):
    by_id = {j['id']: j for j in jobs}
    summaries = {r['id']: r for r in rows}
    planned = []
    for group in sorted({j['group'] for j in jobs}):
        for kind, labels in CHECKS.items():
            ids = [group+'--'+label for label in labels]
            planned.append({'id': group+'--'+kind, 'kind': kind, 'jobs': ids,
                            'roots': [by_id[i]['root'] for i in ids], 'status': 'missing', 'result': None})
    files = sorted(Path(directory).glob('*.json')) if Path(directory).exists() else []
    seen = set()
    for path in files:
        item = None
        rec, raw = packet.copy(path, 'checks/'+path.name)
        if raw is None:
            continue
        try:
            value = decode(raw)
            require(isinstance(value,dict), 'Checker result must be an object')
            matches = [p for p in planned if p['roots'] == value.get('roots')]
            require(len(matches) == 1, 'Checker roots do not match one planned check')
            item = matches[0]
            if item['id'] in seen:
                item['status'] = 'invalid_evidence'
                raise ValueError('Duplicate checker result for planned check')
            seen.add(item['id'])
            item['result'] = value
            item['evidence'] = rec['path']
            require(value['schema'] == CHECK and value['checker_sha256'] == checker_pin['sha256'], 'Wrong checker schema/identity')
            require(value['release_authority'] is False and value['accepted_orbit_covariance'] is False, 'Checker claims unsupported authority')
            require(type(value['passed']) is bool, 'Checker decision must be boolean')
            if value['passed']:
                receipts = value['execution_receipts']
                require(len(receipts) == len(item['jobs']), 'Checker execution attribution incomplete')
                for record, job_id in zip(receipts, item['jobs']):
                    actual = summaries[job_id]
                    require(record['root'] == by_id[job_id]['root'] and record['freeze'] == freeze_pin and
                            record['sha256'] == actual.get('execution_sha256') and
                            actual['status'] == 'complete' and actual.get('owned_closure_reported') is True,
                            'Passing checker lacks matching closed execution receipt')
            item['status'] = 'passed' if value['passed'] else 'failed'
        except (ValueError, KeyError, TypeError) as error:
            packet.issues.append({'path': str(path), 'error': str(error)})
            if item is not None:
                item['status'] = 'invalid_evidence'
    return planned


def render(summary):
    esc = lambda value: html.escape(str(value if value is not None else 'unknown'))
    brief = lambda value: str(value)[:240]+('…' if len(str(value))>240 else '')
    def details(label, value):
        return '<details><summary>'+esc(label)+'</summary><pre>'+esc(json.dumps(value,indent=2,sort_keys=True))+'</pre></details>'
    def declaration(value):
        if not isinstance(value,dict):
            return 'Unclassified receipt; inspect the preserved record.'
        execution = value.get('execution')
        if isinstance(execution,dict) and isinstance(execution.get('status'),str):
            return 'Declared execution status: '+brief(execution['status'])
        for key in ('decision','status','outcome'):
            if isinstance(value.get(key),str):
                return 'Declared '+key+': '+brief(value[key])
        if type(value.get('passed')) is bool:
            return 'Declared passed: '+str(value['passed'])
        return 'Preserved provenance; no acceptance inferred.'
    def metrics(value):
        if not isinstance(value,dict):
            return 'No checker result available.'
        fields = []
        if 'error' in value:
            fields.append('Error: '+str(value['error'])[:240])
        for key,label in (('compared_artifacts','Artifacts compared'),
                          ('objective_difference','Objective difference'),
                          ('cold_objective_floor','Cold objective floor'),
                          ('relative_retained_covariance_difference','Retained covariance relative difference'),
                          ('relative_dynamic_covariance_difference','Dynamic covariance relative difference (diagnostic)')):
            if key in value:
                fields.append(label+': '+brief(value[key]))
        predictions = value.get('maximum_prediction_difference_m')
        if isinstance(predictions,dict):
            for kind in ('code','phase'):
                if kind in predictions:
                    fields.append(kind.title()+' maximum prediction difference (m): '+brief(predictions[kind]))
        return '; '.join(fields) if fields else 'See the original checker decision below.'
    audit = summary['independent_outcome_audit']
    audit_text = 'pending; no accepted independent audit is established'
    audit_link = ''
    if audit.get('status')=='supplied_separately':
        receipt = audit.get('declared_receipt')
        accepted = isinstance(receipt,dict) and any(receipt.get(k)=='accepted' for k in ('decision','status','outcome'))
        audit_text = 'supplied separately; '+('the receipt explicitly declares acceptance' if accepted else 'no explicit acceptance is inferred from the receipt')
        audit_link = ' (<a href="'+html.escape(audit['evidence'],quote=True)+'">full audit receipt</a>)'
    attempt_rows = ''.join('<tr>'+''.join('<td>'+esc(r.get(k))+'</td>' for k in
                         ('id','status','strict_nuisance_reported','profile_iterations','native_wall_seconds','peak_process_tree_rss_bytes'))+'</tr>'
                           for r in summary['attempts'])
    check_rows = ''.join('<tr><td>'+esc(c['id'])+'</td><td>'+esc(c['status'])+'</td><td><p>'+esc(metrics(c.get('result')))+'</p>'+details('Full unchanged checker result',c.get('result'))+'</td></tr>' for c in summary['checks'])
    issues = ''.join('<li>'+esc(x)+'</li>' for x in summary['issues']) or '<li>None recorded by this packaging pass.</li>'
    links = ''.join('<li><a href="'+html.escape(p,quote=True)+'">'+esc(p)+'</a></li>' for p in summary['evidence_links'])
    declarations = ''.join('<tr><td>'+esc(v['evidence'])+'</td><td><p>'+esc(declaration(v['declared_receipt']))+'</p>'+details('Full preserved receipt',v['declared_receipt'])+'</td></tr>' for v in summary['additional_receipts'])
    native = summary['native_tests']
    native_lines = [declaration(native)]
    if isinstance(native,dict):
        for suite in native.get('results',[]):
            counts = suite.get('counts',{})
            native_lines.append(str(suite.get('suite','unknown'))+': '+', '.join(k+'='+str(counts.get(k,'unknown')) for k in ('tests','failure','error','skipped')))
    native_display = '<p>'+esc('; '.join(native_lines))+'</p>'+details('Full native-test result',native)
    return '''<!doctype html><meta charset="utf-8"><title>Nuisance initialization profile evidence</title>
<style>body{font:15px system-ui;margin:2em;max-width:1300px;color:#182230}table{border-collapse:collapse;width:100%;margin:1em 0}td,th{border:1px solid #ccd3dd;padding:.5em;text-align:left;vertical-align:top}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-width:60em}.notice{padding:1em;background:#fff3cd}h1{font-size:1.7em}</style>
<h1>Fixed-trajectory nuisance initialization: actual evidence</h1>
<p>Snapshot: '''+esc(summary['created_at'])+'''. Planned attempts: '''+str(len(summary['attempts']))+'''. Outcomes: '''+esc(summary['attempt_counts'])+'''. Checker results: '''+esc(summary['check_counts'])+'''.</p>
<div class="notice">This is a bounded nuisance-profile experiment. Strict nuisance convergence does not establish full orbit-optimizer convergence. Covariance comparisons are diagnostic local linearizations only; accepted orbit covariance and release authority are false. No whole-fit result or speedup is claimed. Timings are individual observed runs under cooperative admission, not an exclusive machine reservation.</div>
<p id="outcome-audit">Independent outcome audit: '''+esc(audit_text)+audit_link+'''. This report grants no release authority. Earlier 24-hour cache experiments timed out and are separate PR #6 evidence; this packet does not replace those outcomes.</p>
<h2>Every planned attempt</h2><p>Strict and iteration fields are native profile statements. Checker decisions below retain their original scope and thresholds. Missing or unclosed attempts remain explicit.</p>
<table><thead><tr><th>Attempt</th><th>Receipt outcome</th><th>Native reports strict</th><th>Profile iterations</th><th>Native wall seconds</th><th>Peak process-tree RSS bytes</th></tr></thead><tbody>'''+attempt_rows+'''</tbody></table>
<h2>Existing checker decisions</h2><table><thead><tr><th>Planned check</th><th>Status</th><th>Unchanged checker result</th></tr></thead><tbody>'''+check_rows+'''</tbody></table>
<h2>Native tests and candidate failures</h2><p>Test/build receipts, earlier failed attempts and reviews are retained below. A successful later candidate never deletes an earlier failure.</p>'''+native_display+'''
<h2>Preserved build, failure and review receipts</h2><table><thead><tr><th>Evidence</th><th>Original declared result</th></tr></thead><tbody>'''+declarations+'''</tbody></table>
<h2>Packaging issues</h2><ul>'''+issues+'''</ul><h2>Evidence and provenance</h2><ul>'''+links+'''</ul><p>Copy hashes and original paths: <a href="manifest.json">manifest.json</a>. Full machine-readable report: <a href="summary.json">summary.json</a>. Datasets, row spools, matrix binaries and seeds are excluded; their recorded input/output pins remain in the receipts.</p>'''


def report(args):
    raw, freeze_pin = read_bytes(args.freeze)
    freeze = decode(raw)
    require(isinstance(freeze,dict), 'Frozen protocol must be an object')
    require(freeze['schema'] == FREEZE, 'Unknown frozen profile protocol')
    jobs = freeze['jobs']
    groups = {j['group'] for j in jobs}
    require(len(jobs) == 27 and len(groups) == 3 and len({j['id'] for j in jobs}) == 27, 'Expected all27 planned attempts in3 groups')
    require({j['id'] for j in jobs} == {g+'--'+c for g in groups for c in CASES}, 'Unexpected planned cases')
    require(all(re.fullmatch(r'[a-zA-Z0-9_.-]+',j['id']) for j in jobs), 'Unsafe job identity')
    require(len({j['root'] for j in jobs})==27 and all(Path(j['root']).is_absolute() for j in jobs), 'Attempt roots must be unique absolute paths')
    require(len(freeze['execution_order']) == 27 and set(freeze['execution_order']) == {j['id'] for j in jobs}, 'Incomplete execution order')
    out = args.output.absolute()
    protected = [Path(args.freeze).absolute().parent, Path(args.checks).absolute(), Path(args.native_tests).absolute().parent]
    protected += [Path(j['root']).absolute() for j in jobs]
    protected += [Path(p).absolute() for p in args.evidence]
    require(out.resolve() == out and not any(out.is_relative_to(p) for p in protected), 'Packet output overlaps evidence/attempt tree')
    out.mkdir(exist_ok=False)
    packet = Packet(out)
    packet.write('protocol/freeze.json', raw, freeze_pin)
    packet.copy(__file__, 'source/report_nuisance_warm_profiles.py')
    for key in ('preparation','build_record','runner','checker','supervisor'):
        p = freeze.get(key)
        if p:
            packet.copy(p['path'], 'protocol/'+key+Path(p['path']).suffix, expected=p)
    by_id = {j['id']: j for j in jobs}
    attempts = [collect_job(packet, by_id[key], freeze_pin) for key in freeze['execution_order']]
    checks = collect_checks(packet,args.checks,jobs,attempts,freeze_pin,freeze['checker'])
    tests_record, tests_raw = packet.copy(args.native_tests, 'native-tests/result.json')
    native_tests = None
    if tests_raw is not None:
        try:
            native_tests = decode(tests_raw)
            require(isinstance(native_tests,dict) and isinstance(native_tests.get('results'),list) and
                    all(isinstance(r,dict) for r in native_tests['results']), 'Native test result must contain suite objects')
        except (ValueError,TypeError) as error:
            packet.issues.append({'path':str(args.native_tests),'error':str(error)})
            native_tests = {'invalid_evidence':str(error)}
    for suite in ('native','correction'):
        matches = [r for r in (native_tests or {}).get('results',[]) if r.get('suite')==suite]
        execution = matches[0].get('execution') if len(matches)==1 else None
        if not isinstance(execution,dict) or execution.get('status') not in TERMINAL or execution.get('owned_process_group_cleaned') is not True:
            packet.issues.append({'path':str(args.native_tests),'error':suite+' test closure unavailable; suite logs were not read'})
            continue
        for name in ('tests.xml','pytest.log','supervisor.json','result.json'):
            packet.copy(Path(args.native_tests).parent/suite/name,'native-tests/'+suite+'/'+name,optional=True)
    declarations = []
    for index,path in enumerate(args.evidence):
        path = Path(path)
        require(path.suffix in ('.json','.xml','.log','.txt','.py','.h','.cpp','.stderr','.stdout'), 'Optional evidence must be an explicit thin text/control file')
        require(not path.name.endswith(('.rows.tsv','.rows.tsv.gz')) and path.name not in ('R.bin','rhs.bin','seed.bin'), 'Bulk evidence forbidden')
        rec, data = packet.copy(path, 'evidence/'+str(index).zfill(3)+'-'+path.name)
        if data is not None and path.suffix == '.json':
            try:
                declarations.append({'evidence':rec['path'],'declared_receipt':decode(data)})
            except (ValueError,TypeError) as error:
                packet.issues.append({'path':str(path),'error':str(error)})
    audit = {'status':'pending'}
    if args.outcome_audit is not None:
        rec, data = packet.copy(args.outcome_audit,'evidence/independent-outcome-audit.json')
        if data is not None:
            try:
                audit = {'status':'supplied_separately','evidence':rec['path'],'declared_receipt':decode(data)}
            except ValueError as error:
                packet.issues.append({'path':str(args.outcome_audit),'error':str(error)})
    # Re-read only sources actually copied. No bulk reference hashing or checker run.
    for record in packet.files:
        if 'source' in record:
            try:
                _, current = read_bytes(record['source']['path'])
                require(current == record['source'], 'Copied source changed before packet completion')
            except (ValueError,OSError) as error:
                packet.issues.append({'path':record['source']['path'],'error':str(error)})
    summary = {'schema':'orbit-poc-nuisance-warm-profile-report-v1',
               'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'freeze':freeze_pin,'attempts':attempts,'checks':checks,
               'attempt_counts':dict(Counter(r['status'] for r in attempts)),
               'check_counts':dict(Counter(c['status'] for c in checks)),
               'native_tests':native_tests,'additional_receipts':declarations,'independent_outcome_audit':audit,
               'release_authority':False,'accepted_orbit_covariance':False,
               'whole_fit_convergence_claim':False,'speedup_claim':False,
               'earlier_wholefit_timeouts':{'publication':'PR #6','scope':'Separate cache off/on24-hour outcomes; not replaced by this profile experiment'},
               'reference_verification_scope':'Only copied thin evidence is rehashed; bulk input/output references remain as recorded pins. Scientific decisions are inherited from the pinned checker, not recomputed.',
               'issues':packet.issues,'evidence_links':[r['path'] for r in packet.files]}
    packet.json('summary.json',summary)
    packet.write('index.html',render(summary).encode())
    manifest = {'schema':'orbit-poc-thin-evidence-packet-v1','files':packet.files,
                'total_payload_bytes':packet.bytes,'excluded':['datasets','row spools','matrix binaries','seed payloads'],
                'manifest_self_hash':'Excluded to avoid recursion; hash this file externally.'}
    with (out/'manifest.json').open('x') as stream:
        json.dump(manifest,stream,indent=2,sort_keys=True);stream.write('\n')
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--freeze',type=Path,required=True)
    p.add_argument('--checks',type=Path,required=True)
    p.add_argument('--native-tests',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--evidence',type=Path,action='append',default=[])
    p.add_argument('--outcome-audit',type=Path)
    args = p.parse_args()
    summary = report(args)
    print(json.dumps({'output':str(args.output),'attempt_counts':summary['attempt_counts'],
                      'check_counts':summary['check_counts'],'release_authority':False}))
    return 0 if not summary['issues'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
