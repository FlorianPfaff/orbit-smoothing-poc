"""Source-only publication builder. Reads pinned receipts; never runs numerical work.

Freeze inputs only after every required audit/qualification has a real terminal
receipt. Build into a new directory. A diagnostic packet is not release approval.
"""
from pathlib import Path
import argparse
import hashlib
import html
import json
import re
import xml.etree.ElementTree as ET

GATES = (
    'native-tests', 'native-fail-fast-tests', 'correction-tests',
    'synthetic-refinement-log_drag_ou', 'synthetic-refinement-pulses',
    'flight-refinement', 'eccentric-24h-refinement', 'objective-log_drag_ou',
    'objective-pulses', 'nuisance-replay', 'nuisance-replay-candidate1-point012',
)
COLD = ('cold-pulses', 'cold-density')
LIMITATIONS = [
    'Candidate06 remains unsuccessful: the density cold fit failed during its second trial. No density covariance is accepted and no release readiness is established.',
    'The 11 correctness checks and two cold fits are diagnostic regressions, not replacements for frozen v3.1 or v4 benchmark attempts. Frozen protocols, physical/statistical models and correctness thresholds are unchanged.',
    'Both cold fits use their original GNSS-only initialization without a donor nuisance state. The one-hour case is synthetic leo500/quiet/normal; GRACE-FO filenames in templates do not make it a flight accuracy experiment.',
    'Saved-artifact rank, covariance/export and objective/refinement audits have distinct scopes. A strict pulse final covariance does not prove calibrated scientific uncertainty, full-grid independent tangent reconstruction or complete flight derivatives.',
    'Rank uses the original reduced stochastic row count and the undamped saved factor. Driver singular-value differences are disclosed without adding a numerical agreement tolerance.',
    'The first density trial was rejected as a physical-domain failure; its second trial failed a native correction check. Preserve both rather than relabeling either as convergence. Trial-history/rollback source and receipt evidence is separate from re-executing every historical trial.',
    'The original sequence aggregate reporting exception, the initial helper test failure and the source02 selected-audit compression-reader failure remain preserved. Corrected reporting/audit readers do not change estimator outcomes.',
    'No accuracy-superiority, GPU speedup, complete-flight-Jacobian or paper-readiness claim follows from this packet. No aggregate audit exit code alone determines whether a particular pulse check passed.',
]


def require(ok, why):
    if not ok:
        raise ValueError(why)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(data):
    def constant(value):
        raise ValueError('Nonfinite JSON constant: ' + value)
    return json.loads(data, parse_constant=constant)


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n').encode()


def tests(data):
    root = ET.fromstring(data)
    suites = list(root.iter('testsuite'))
    require(len(suites) == 1, 'Expected one pinned pytest suite')
    a = suites[0].attrib
    counts = {k: int(a.get(k, '0')) for k in ('tests', 'failures', 'errors', 'skipped')}
    counts['passed'] = counts['tests'] - sum(counts[k] for k in ('failures', 'errors', 'skipped'))
    counts['failed_cases'] = [c.attrib.get('name') for c in suites[0].iter('testcase')
                              if c.find('failure') is not None or c.find('error') is not None]
    return counts


def cleanup(receipt):
    c = receipt.get('cleanup', {})
    return {'status': receipt.get('status'), 'returncode': receipt.get('returncode'),
            'elapsed_seconds': receipt.get('elapsed_seconds'),
            'owned_process_group_cleaned': receipt.get('owned_process_group_cleaned'),
            'cleanup_verified': c.get('verified'), 'empty_tree_certificate': c.get('empty_tree_certificate'),
            'remaining': c.get('remaining'), 'signals_received': receipt.get('signals_received')}


def render(report, links):
    esc = lambda x: html.escape(str(x))
    def link(id, label):
        return '<a href="'+html.escape(links[id], quote=True)+'">'+esc(label)+'</a>'
    rows = ''.join('<tr><td>'+esc(r['stage'])+'</td><td>'+esc(r['recorded_status'])+'</td><td>'+
                   link(r['strict_receipt'], 'strict receipt')+' · '+link(r['supervisor_receipt'], 'supervisor')+'</td></tr>'
                   for r in report['outcomes'])
    audits = ''.join('<tr><td>'+esc(name)+'</td><td>'+esc(row['summary'])+'</td><td>'+
                     esc(row['supervisor']['returncode'])+'</td><td>'+link('audits/'+name+'/result.json','full result')+'</td></tr>'
                     for name, row in report['saved_audits'].items())
    qualifications = ''.join('<li>'+esc(name)+': '+esc(q['passed'])+' passed, '+esc(q['failures'])+
                             ' failed, '+esc(q['errors'])+' errors, '+esc(q['skipped'])+' skipped — '+
                             link('qualification/'+name+'/junit.xml','JUnit')+'</li>'
                             for name,q in report['helper_qualification'].items())
    limitations = ''.join('<li>'+esc(v)+'</li>' for v in report['limitations'])
    originals = ''.join('<li>'+esc(r['stage'])+': '+esc(r['status'])+' — '+
                        link('original/'+r['stage']+'/backend-result.json','original backend receipt')+'</li>'
                        for r in report['original_outcomes'])
    failures = ''.join('<li>'+link(id,id)+'</li>' for id in links if id.startswith('failures/'))
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Candidate06: correctness passed, density cold fit failed</title>'
            '<style>body{font:16px/1.5 system-ui;max-width:1100px;margin:3rem auto;padding:0 1rem;color:#17212b}'
            'table{border-collapse:collapse;width:100%}td,th{padding:.5rem;border:1px solid #b8c2cc;text-align:left}'
            'a{color:#064e9c}.status{border-left:6px solid #b84520;padding:1rem;background:#fff3ed}</style>'
            '<h1>Candidate06 sequence02</h1><p class="status"><strong>11 correctness checks passed. '
            'The cold pulse fit passed; the cold density fit failed.</strong> The correction is not ready for release.</p>'
            '<p>Both one-hour fits retained their original GNSS-only initialization. Failed trials and previous unsuccessful audits remain available below. '
            'No frozen benchmark or correctness threshold was changed.</p>'
            '<p><a href="report.json">Machine-readable report</a> · <a href="inputs-manifest.json">Pinned input manifest</a> · '
            '<a href="SHA256SUMS">Packet checksums</a> · <a href="README.md">Scope and limitations</a></p>'
            '<h2>All 13 planned outcomes</h2><table><thead><tr><th>Attempt</th><th>Recorded outcome</th><th>Evidence</th></tr></thead><tbody>'+rows+'</tbody></table>'
            '<h2>Saved-output audits</h2><p>Aggregate nonzero exits retain the density failure; inspect individual rows. '
            'These helpers never grant release or covariance authority.</p><table><tr><th>Audit</th><th>Scoped result</th><th>Exit</th><th>Evidence</th></tr>'+audits+'</table>'
            '<h2>Original outcomes and failure history</h2><ul>'+originals+'</ul><ul>'+failures+'</ul><p>'+
            link('sequence/result.json','Original sequence reporting exception')+' · '+
            link('preserved/selected-source02/result.json','Preserved first selected-audit failure')+'</p>'
            '<h2>Helper qualification</h2><ul>'+qualifications+'</ul>'
            '<h2>Limits of the evidence</h2><ul>'+limitations+'</ul></html>')


def build(manifest_path, expected_sha, output):
    raw = manifest_path.read_bytes()
    require(digest(raw) == expected_sha, 'Publication manifest hash differs')
    manifest = strict_json(raw)
    require(manifest['schema'] == 'candidate06-sequence02-publication-inputs-v1', 'Wrong manifest schema')
    require(manifest['builder_sha256'] == digest(Path(__file__).read_bytes()), 'Manifest pins another builder')
    require(not output.exists(), 'Publication output must be fresh')
    contents, links, pins = {}, {}, {}
    total = 0
    for pin in manifest['files']:
        id, source, target = pin['id'], Path(pin['path']), Path(pin['target'])
        require(id not in contents and source.is_absolute() and target.parts[0] == 'receipts'
                and not target.is_absolute() and '..' not in target.parts, 'Duplicate/unsafe publication mapping')
        require(str(target) not in links.values(), 'Duplicate publication target')
        require(type(pin['bytes']) is int and 0 <= pin['bytes'] <= 4*1024*1024
                and re.fullmatch('[0-9a-f]{64}', pin['sha256']), 'Unbounded or malformed input pin')
        before = source.stat()
        data = source.read_bytes()
        after = source.stat()
        require((before.st_size, before.st_mtime_ns, before.st_ino) ==
                (after.st_size, after.st_mtime_ns, after.st_ino), 'Input changed while reading')
        require(len(data) == pin['bytes'] and digest(data) == pin['sha256'], 'Input hash/size differs: '+str(source))
        total += len(data)
        require(total <= 32*1024*1024, 'Small-receipt packet exceeds32MiB bound')
        contents[id], links[id], pins[id] = data, str(target), pin
    read = lambda id: strict_json(contents[id])
    seq, gates, cold = read('sequence/result.json'), read('correctness/result.json'), read('cold/result.json')
    external = manifest['external_inputs']
    require(len(external) == 1 and external[0]['id'] == 'cold/plan.json'
            and external[0]['pin'] == read('cold/freeze.json')['plan'], 'External cold plan identity differs')
    require([r['stage'] for r in gates['stages']] == list(GATES), 'Missing/reordered correctness inventory')
    require([r['stage'] for r in cold['stages']] == list(COLD), 'Missing/reordered cold inventory')
    require(all(r['status'] == 'passed' for r in gates['stages']), 'This packet specification expects actual11 passed gates')
    require([r['status'] for r in cold['stages']] == ['passed', 'failed'], 'This packet specification expects actual mixed cold outcome')
    outcomes = []
    for family, rows in (('gates',gates['stages']), ('cold',cold['stages'])):
        for row in rows:
            stage = row['stage']
            strict_id, sup_id = family+'/'+stage+'/strict-result.json', family+'/'+stage+'/supervisor.json'
            strict, supervisor = read(strict_id), read(sup_id)
            require(strict['stage'] == stage and strict['status'] == row['status'], 'Strict outcome differs')
            require(row['strict_result']['sha256'] == pins[strict_id]['sha256'], 'Aggregate strict pin differs')
            supervisor_pin = row.get('supervisor') or row.get('execution')
            require(supervisor_pin['sha256'] == pins[sup_id]['sha256'], 'Aggregate supervisor pin differs')
            outcomes.append({'stage':stage,'recorded_status':row['status'],'strict_receipt':strict_id,
                             'supervisor_receipt':sup_id,'supervisor':cleanup(supervisor)})
    original = read('original/result.json')
    original_outcomes = [{'stage':r['stage'],'status':r['status']} for r in original['stages']]
    require([r['stage'] for r in original_outcomes] == list(COLD), 'Original outcome inventory differs')
    audits = {k:read('audits/'+k+'/result.json') for k in ('rank','export','scientific','selected')}
    for a in audits.values():
        require(a.get('approved') is False and a.get('release_authority') is False
                and a.get('covariance_authority') is False, 'Auditor authority differs')
    require([r['stage'] for r in audits['rank']['cases']] == list(COLD), 'Rank lost an outcome')
    require([r['stage'] for r in audits['export']['outcomes']] == list(COLD), 'Export audit lost an outcome')
    require([r['stage'] for r in audits['scientific']['stages']] == list(GATES[3:]), 'Scientific audit lost a stage')
    require([r['stage'] for r in audits['selected']['gates']] == list(GATES)
            and [r['stage'] for r in audits['selected']['cold']] == list(COLD), 'Selected audit lost an outcome')
    require(audits['selected']['source_revision'] == 'source03', 'Corrected selected audit must be actual source03')
    summaries = {
        'rank': '; '.join(r['stage']+': '+r['status'] for r in audits['rank']['cases']),
        'export': '; '.join(r['stage']+': '+r['status'] for r in audits['export']['outcomes']),
        'scientific': str(sum(r['status']=='saved_predicates_passed' for r in audits['scientific']['stages']))+'/8 saved scientific predicates passed',
        'selected': '; '.join(r['stage']+': '+('selected_checks_completed' if r.get('selected_checks_completed')
                                             else r.get('audit_status','unclassified')) for r in audits['selected']['cold']),
    }
    saved = {k:{'summary':summaries[k],'supervisor':cleanup(read('audits/'+k+'/supervisor.json')),
                'result_sha256':pins['audits/'+k+'/result.json']['sha256']} for k in audits}
    qualification = {k:tests(contents['qualification/'+k+'/junit.xml']) for k in ('initial','corrected','selected-source03')}
    pulse, density = read('cold/cold-pulses/backend-result.json'), read('cold/cold-density/backend-result.json')
    require(pulse['converged'] is True and pulse['covariance_valid'] is True
            and density['converged'] is False and density['covariance_valid'] is False, 'Actual covariance state differs')
    report = {'schema':'candidate06-sequence02-publication-v1','status':'failed_density_requires_correction',
              'release_authority':False,'covariance_authority':False,'accuracy_claim':False,
              'outcomes':outcomes,'original_outcomes':original_outcomes,'saved_audits':saved,
              'helper_qualification':qualification,'sequence_recorded_failure':seq,
              'density_backend_error':density['error'],'density_history':density['history'],
              'pulse_confirmation_checks':pulse['confirmation_checks'],
              'selected_pulse_saved_checks':audits['selected']['cold'][0],
              'limits_and_approximations_from_scientific_audit':audits['scientific']['unavailable'],
              'limitations':LIMITATIONS,'frozen_benchmarks_unchanged':True,
              'publication_input_sha256':expected_sha,'source_receipt_links':links,
              'external_input_identities':external}
    # Serialize all summaries before creating output. Original raw bytes remain exact.
    report_data = json_bytes(report)
    html_data = render(report,links).encode()
    readme = ('# Candidate06 sequence02: preserved mixed outcome\n\n'
              'Eleven correctness checks passed. The original-initialization pulse cold fit passed; the density cold fit failed. '
              'This packet publishes that outcome, all13 attempts, original outcomes, failed trial evidence and four saved-output audits.\n\n'
              'Read report.json for machine-readable diagnostics and index.html for the evidence links. '
              'Aggregate rank/export/selected audit exits retain the unsuccessful density case; inspect their per-case rows.\n\n'
              +'\n'.join('- '+v for v in LIMITATIONS)+'\n\n'
              'All copied receipts preserve original bytes. Bulky inputs, raw row archives and orbit arrays are excluded. '
              'Checksums and original absolute source identities remain in inputs-manifest.json. '
              'This builder does not rerun fitting, compute covariance or approve a release.\n').encode()
    output.mkdir(parents=False)
    written = {}
    for id, data in contents.items():
        path = output/links[id]
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)
        written[links[id]] = digest(data)
    for name, data in (('report.json',report_data),('index.html',html_data),('README.md',readme),
                       ('inputs-manifest.json',raw),('build_packet.py',Path(__file__).read_bytes())):
        with (output/name).open('xb') as stream:
            stream.write(data)
        written[name] = digest(data)
    with (output/'SHA256SUMS').open('x') as stream:
        stream.write(''.join(h+'  '+name+'\n' for name,h in sorted(written.items())))
    return {'status':'packet_built_not_release_approved','output':str(output),
            'receipt_count':len(contents),'receipt_bytes':total,'outcome_count':len(outcomes)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.manifest,args.manifest_sha256,args.output),allow_nan=False))
