"""Publish exact, thin composed-unit evidence without copying fake numerical files."""
import argparse
from datetime import datetime, timezone
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET


D = Path(__file__).resolve().parent


def pin(path):
    path = Path(path)
    data = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in {'href', 'src'}:
                self.targets.append(value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--independent-review', type=Path)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.parent != D or output.exists():
        raise ValueError('Output must be a new direct child of this separate control directory')
    readiness_path = D / 'readiness01.json'
    readiness = json.loads(readiness_path.read_bytes())
    assert readiness['passed_tests'] == 7 and readiness['native_execution'] is False
    assert all(readiness[k] is False for k in ['wholefit_admission', 'fullfit_admission', 'release_authority'])
    for group in ['successful_attempt', 'preserved_failed_attempt']:
        for value in readiness[group].values():
            if isinstance(value, dict) and 'path' in value:
                assert pin(value['path']) == value
    for key in ['test_source', 'runner']:
        assert pin(readiness[key]['path']) == readiness[key]
    plan = json.loads((D / 'author-tests02/plan.json').read_bytes())
    sources = plan['production_source_files']
    assert len(sources) == 52 and all(pin(p['path']) == p for p in sources)
    assert sources == json.loads((D / 'author-tests01/plan.json').read_bytes())['production_source_files']

    # The optional review remains exact source evidence. Its conclusions are
    # rendered verbatim; author test results never manufacture review acceptance.
    review = None
    if args.independent_review:
        review = json.loads(args.independent_review.read_bytes())
        assert review['schema'] == 'independent-composed-python-warm-lifecycle-review-v1'
        assert review['status'] == 'accepted_composed_python_unit_evidence_only'
        assert review['passed'] is True and review['counts'] == {'failure': 0, 'error': 0, 'skipped': 0, 'tests': 7}
        assert review['mock_launch_count'] == 173 and review['production_python_files'] == sources
        assert all(review[k] is False for k in ['native_execution', 'compiler_execution',
                   'wholefit_admission', 'fullfit_admission', 'release_authority', 'scientific_numerical_acceptance'])
        assert review['author_readiness'] == pin(readiness_path)
        for key in ['test_source', 'test_execution', 'test_plan', 'test_log', 'test_junit',
                    'review_execution_plan', 'review_execution_result']:
            assert pin(review[key]['path']) == review[key]
        assert review['test_source']['sha256'] == readiness['test_source']['sha256']
        for entry in review['observed_cases']:
            assert pin(entry['trace']['path']) == entry['trace']
        assert len(review['observed_cases']) == 7
        for value in review['author_failure_preserved'].values():
            assert pin(value['path']) == value
    output.mkdir()
    payloads = []
    builder_pin = pin(Path(__file__).resolve())

    def copy(source, relative):
        source = Path(source)
        assert source.is_file() and not source.is_symlink()
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        before = pin(source)
        shutil.copyfile(source, destination)
        after = pin(destination)
        assert before == pin(source) and after['sha256'] == before['sha256'] and after['bytes'] == before['bytes']
        payloads.append({'path': relative, 'sha256': after['sha256'], 'bytes': after['bytes'],
                         'kind': 'exact_source_copy', 'source': before})

    def generated(relative, value, source_pins, derivation):
        destination = output / relative
        write_json(destination, value)
        p = pin(destination)
        payloads.append({'path': relative, 'sha256': p['sha256'], 'bytes': p['bytes'],
                         'kind': 'derived_metadata', 'source_inputs': source_pins,
                         'generator': builder_pin, 'derivation': derivation})

    for name in ['test_lifecycle_composition.py', 'run_offline.py', 'make_publication.py', 'readiness01.json']:
        copy(D / name, 'control/' + name)
    generated('source-pins.json', {'schema': 'composed-unit-python-source-pins-v1',
              'candidate_source_root': '/home/emper/orbit-nuisance-warmstarts/source-candidate06',
              'count': 52, 'source_files': sources,
              'scope': 'Exact Python bytes used by both author attempts; source code is not duplicated in this thin packet'},
              [pin(D / 'author-tests01/plan.json'), pin(D / 'author-tests02/plan.json')],
              'Identical production_source_files arrays extracted from both actual attempt plans and rehashed at packet creation')

    attempts = []
    attempt_specs = [('author-tests01', 4), ('author-tests02', 0)]
    if review is not None:
        independent_attempt = Path(review['test_plan']['path']).parent
        assert independent_attempt.parent == D
        assert json.loads((independent_attempt / 'plan.json').read_bytes())['production_source_files'] == sources
        attempt_specs.append((independent_attempt.name, 0))
    for attempt, expected_failures in attempt_specs:
        root = D / attempt
        for name in ['plan.json', 'test_lifecycle_composition.py', 'execution.json', 'tests.xml', 'tests.log']:
            copy(root / name, 'attempts/' + attempt + '/' + name)
        tree = ET.parse(root / 'tests.xml')
        cases = list(tree.iter('testcase'))
        failures = sum(case.find('failure') is not None for case in cases)
        errors = sum(case.find('error') is not None for case in cases)
        skipped = sum(case.find('skipped') is not None for case in cases)
        assert len(cases) == 7 and failures == expected_failures and errors == skipped == 0
        case_results = []
        for case in cases:
            failure = case.find('failure')
            case_results.append({'name': case.get('name'), 'outcome': 'passed' if failure is None else 'failed',
                                 'failure_message': None if failure is None else failure.get('message')})
        trace_rows = []
        for source in sorted((root / 'tmp').glob('*/composition-trace.json')):
            if source.parent.is_symlink():
                continue
            trace = json.loads(source.read_bytes())
            assert trace['evidence_kind'] == 'mock_composed_python_unit' and trace['native_execution'] is False
            relative = 'attempts/' + attempt + '/traces/' + source.parent.name + '.json'
            copy(source, relative)
            trace_rows.append({'path': relative, 'scenario': trace['scenario'],
                               'mock_call_boundary_records': len(trace['launches']),
                               'profile_labels': [row['point_label'] for row in trace['launches'] if row['call'] == 'profile'],
                               'acceptance_labels': [row['label'] for row in trace['acceptances']],
                               'optimizer_status': trace.get('optimizer_result', {}).get('status'),
                               'raised': trace.get('raised')})
        assert len(trace_rows) == 7
        attempts.append({'name': attempt, 'tests': 7, 'passed': 7 - failures, 'failures': failures,
                         'errors': errors, 'skipped': skipped, 'cases': case_results, 'traces': trace_rows,
                         'mock_call_boundary_records': sum(t['mock_call_boundary_records'] for t in trace_rows)})
    assert attempts[1]['mock_call_boundary_records'] == 173
    assert attempts[0]['mock_call_boundary_records'] == 118
    review_info = {'status': 'pending_independent_review', 'receipt': None}
    if review is not None:
        assert attempts[2]['mock_call_boundary_records'] == 173
        copy(args.independent_review, 'review/independent-review.json')
        for key, name in [('review_execution_plan', 'execution-plan.json'),
                          ('review_execution_result', 'replay-result.json')]:
            copy(review[key]['path'], 'review/' + name)
        copy(args.independent_review.parent / 'replay.log', 'review/replay.log')
        copy(review['author_failure_preserved']['narrow_fixture_only_diff']['path'],
             'review/preserved-author-serializer-repair.diff')
        review_info = {'status': 'accepted_composed_python_unit_evidence_only', 'receipt': 'review/independent-review.json',
                       'source_pin': pin(args.independent_review), 'reported_schema': review.get('schema'),
                       'reported_status': review.get('status'), 'tests': 7, 'passed': 7,
                       'mock_call_boundary_records': 173}
    summary = {'schema': 'thin-composed-warm-lifecycle-unit-publication-v1',
               'created_at': datetime.now(timezone.utc).isoformat(),
               'scope': 'Mock composed Python unit evidence; not a native fit or orbit-dynamics validation',
               'native_execution': False, 'physical_closure_mocked': True,
               'final_author_tests': {'tests': 7, 'passed': 7, 'failures': 0, 'errors': 0, 'skipped': 0},
               'initial_author_tests': {'tests': 7, 'passed': 3, 'failures': 4, 'errors': 0, 'skipped': 0},
               'repair': 'Fixture trace JSON serialization only: numpy.generic is encoded via item(). Production code, thresholds and controls were not changed.',
               'python_source_files_bound': 52, 'attempts': attempts, 'independent_review': review_info,
               'omitted': 'Synthetic factor/trajectory/seed/covariance files and pytest temporary trees; exact traces retain their provenance references.',
               'wholefit_admission': False, 'fullfit_admission': False, 'release_authority': False, 'speedup_claim': None}
    summary_sources = [pin(readiness_path), *[pin(D / row['name'] / 'tests.xml') for row in attempts],
                       *[p['source'] for p in payloads if p['kind'] == 'exact_source_copy' and '/traces/' in p['path']]]
    if review is not None:
        summary_sources.append(pin(args.independent_review))
    generated('summary.json', summary, summary_sources,
              'Counts parsed from exact JUnit; traces and actual attempt plans preserved; scope and authority kept explicit')

    review_text = ('<strong>Independent review pending.</strong>' if review is None else
                   '<strong>Independent replay: 7 passed; accepted as composed Python unit evidence only.</strong> '
                   '<a href="review/independent-review.json">Read the exact review</a>: ' +
                   html.escape(str(review.get('status', 'No status field'))))
    rows = ''.join('<tr><td>' + html.escape(a['name']) + '</td><td>' + str(a['passed']) + '</td><td>' +
                   str(a['failures']) + '</td><td>' + str(a['mock_call_boundary_records']) + '</td></tr>' for a in attempts)
    case_rows = ''.join('<tr><td>' + html.escape(c['name']) + '</td><td>' + html.escape(c['outcome']) + '</td></tr>'
                        for c in attempts[1]['cases'])
    links = ''.join('<li><a href="' + html.escape(p['path'], quote=True) + '">' + html.escape(p['path']) +
                    '</a> — ' + str(p['bytes']) + ' bytes; SHA256 <code>' + p['sha256'] + '</code></li>'
                    for p in sorted(payloads, key=lambda p: p['path']))
    document = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Warm-start lifecycle — composed Python unit evidence</title>
<style>body{max-width:1100px;margin:2rem auto;padding:0 1rem;font:16px/1.55 system-ui,sans-serif;color:#1d2935}table{border-collapse:collapse;width:100%;margin:1rem 0}th,td{text-align:left;border:1px solid #ccd4dc;padding:.5rem}code{overflow-wrap:anywhere;font-size:.85em}li{margin:.6rem 0;overflow-wrap:anywhere}.scope{padding:1rem;border:2px solid #7a5c16;background:#fff8e7}</style>
<h1>Warm-start lifecycle: composed Python unit evidence</h1>
<p><strong>Final author run: 7 passed; 0 failures, errors or skips.</strong></p>
<p class="scope">Native computation and physical closure are mocked. This packet tests real Python optimizer, lifecycle and backend control flow. It is not a native fit, orbit-dynamics validation, or speedup result. Whole-fit, full-fit and release authority remain false.</p>
<p>''' + review_text + '''</p>
<p>The tests exercise real minimize and NativeModel initialization, evaluate, trial, accept, execute and finish, including cold final covariance. They record donor promotion, rejection rollback, floor-limited revocation, inherited-environment suppression, and all seven protected cold labels. The final run contains 173 mocked call-boundary records; zero native processes were launched.</p>
<h2>Author attempts and independent replay</h2>
<table><thead><tr><th>Attempt</th><th>Passed</th><th>Failed</th><th>Mock call records</th></tr></thead><tbody>''' + rows + '''</tbody></table>
<p>The first attempt had four fixture serialization failures when recording a NumPy boolean. Its source, execution receipt, JUnit, log and all seven traces are preserved. Only trace encoding changed before the passing attempt; production source and numerical thresholds did not change. The original readiness keeps its historical pending-review status; the later independent receipt records the reviewed result.</p>
<h2>Final cases</h2><table><thead><tr><th>Case</th><th>Outcome</th></tr></thead><tbody>''' + case_rows + '''</tbody></table>
<h2>Evidence inventory</h2><p>All 52 Python source pins are retained. Exact source copies are byte-identical; generated metadata records its input provenance in the <a href="manifest.json">manifest</a>. Synthetic factor, trajectory, seed and covariance files are omitted; their references remain in the copied traces. No temporary numerical tree is included.</p><ul>''' + links + '''</ul></html>'''
    (output / 'index.html').write_text(document)
    index_pin = pin(output / 'index.html')
    payloads.append({'path': 'index.html', 'sha256': index_pin['sha256'], 'bytes': index_pin['bytes'],
                     'kind': 'derived_html', 'generator': builder_pin,
                     'source_inputs': [pin(output / 'summary.json'), pin(readiness_path)],
                     'derivation': 'Static index from actual parsed test counts and exact packet evidence inventory'})
    manifest = {'schema': 'thin-composed-unit-payload-manifest-v1', 'created_at': datetime.now(timezone.utc).isoformat(),
                'generator': builder_pin, 'payloads': sorted(payloads, key=lambda p: p['path']),
                'self_inventory': 'The manifest excludes its own bytes. Its hash is sealed in the separate packet validation receipt.'}
    write_json(output / 'manifest.json', manifest)
    assert {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()} == {
        p['path'] for p in payloads} | {'manifest.json'}
    for entry in payloads:
        actual = pin(output / entry['path'])
        assert actual['sha256'] == entry['sha256'] and actual['bytes'] == entry['bytes']
        if entry['kind'] == 'exact_source_copy':
            assert pin(entry['source']['path']) == entry['source']
    parser = Links()
    parser.feed(document)
    for target in parser.targets:
        parsed = urlsplit(target)
        assert not parsed.scheme and not parsed.netloc
        resolved = (output / unquote(parsed.path)).resolve()
        assert resolved.is_relative_to(output) and resolved.is_file()
    validation = {'schema': 'thin-composed-unit-packet-validation-v1',
                  'created_at': datetime.now(timezone.utc).isoformat(), 'packet': str(output),
                  'payload_count': len(payloads), 'payload_bytes': sum(p['bytes'] for p in payloads),
                  'manifest': pin(output / 'manifest.json'), 'summary': pin(output / 'summary.json'),
                  'index': index_pin, 'local_html_links_checked': len(parser.targets),
                  'all_payload_hashes_and_source_copies_verified': True, 'no_extra_payloads': True,
                  'native_execution': False, 'bulky_mock_numerical_files_included': False,
                  'independent_review': review_info, 'wholefit_admission': False,
                  'fullfit_admission': False, 'release_authority': False}
    receipt_path = D / (output.name + '-validation.json')
    assert not receipt_path.exists()
    write_json(receipt_path, validation)
    print(json.dumps({'packet': str(output), 'validation': pin(receipt_path), 'manifest': validation['manifest'],
                      'payload_count': len(payloads), 'payload_bytes': validation['payload_bytes']}))


if __name__ == '__main__':
    main()
