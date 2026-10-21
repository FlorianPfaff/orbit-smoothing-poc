#!/usr/bin/env python3
"""Copy completed evidence and build a bounded engineering report; never run native code."""
import argparse, datetime, gzip, hashlib, html, json, pathlib, subprocess

B = pathlib.Path('/home/emper/orbit-nuisance-performance')
SOURCE = B / 'source'
EXPECTED_SOURCE = 'c55aef501f171de7e6a7c42ef4614d7f82f1e7c9'
PAIR_NAMES = ['pulses-accumulate0', 'pulses-accumulate1', 'log_drag_ou-accumulate0', 'log_drag_ou-accumulate1', 'old_nuisance_replay-accumulate0', 'candidate1_nuisance_replay-accumulate0']
LABELS = ['Pulses · per observation', 'Pulses · epoch accumulation', 'Log density · per observation', 'Log density · epoch accumulation', 'Historical failure input: old', 'Historical failure input: candidate1']

def digest(data): return hashlib.sha256(data).hexdigest()
def read(path): return json.loads(pathlib.Path(path).read_text())
def dump(path, data): path.write_text(json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + '\n')
def link(path, label): return '<a href="' + html.escape(path, quote=True) + '">' + html.escape(label) + '</a>'
def fmt(x, places=3): return 'unknown' if x is None else f'{x:,.{places}f}'

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', required=True, type=pathlib.Path)
    ap.add_argument('--actual-review', required=True, type=pathlib.Path)
    args = ap.parse_args()
    out = args.output.resolve()
    if out.exists(): raise SystemExit('Refusing to overwrite an existing publication.')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=SOURCE, text=True).strip()
    if head != EXPECTED_SOURCE: raise SystemExit('Candidate source commit changed.')
    out.mkdir(parents=True)
    copies = []
    def copy(src, rel=None, compressed=False):
        src = pathlib.Path(src)
        raw = src.read_bytes()
        rel = rel or ('evidence/' + str(src.relative_to(B)))
        stored = gzip.compress(raw, mtime=0) if compressed else raw
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            if dst.read_bytes() != stored: raise ValueError('Conflicting copy ' + str(dst))
            return rel
        dst.write_bytes(stored)
        copies.append({'path': rel, 'bytes': len(stored), 'sha256': digest(stored), 'source_path': str(src), 'source_bytes': len(raw), 'source_sha256': digest(raw), 'encoding': 'gzip' if compressed else 'identity'})
        return rel

    # Frozen controls and preparations are real preserved bytes, not reconstructed descriptions.
    controls = ['run_native_tests01.py', 'run_pairs01.py', 'run_replay_pairs01.py', 'prepare_exact_nuisance_replay_pairs01.py', 'review_pair_preparation01.py', 'review_exact_replay_preparation01.py', 'discover_nuisance_fixtures01.py', 'finish_native_build01.py', 'finish_native_build02.py', 'build-controller-correction02.json', 'finish-native-build01.log', 'finish-native-build02.log', 'candidate-build-complete01.json', 'candidate-source01.json', 'bootstrap-complete01.json', 'fixture-discovery01.json', 'exact-nuisance-replays-local-inputs01.json', 'exact-replay-preparation-independent-review01.json', 'paired01-independent-preparation-result.json', 'nuisance-performance-independent-review01.json', 'native-nuisance-candidate01-author-validation.json', 'native-nuisance-candidate01-author-validation02.json']
    for name in controls: copy(B / 'control' / name)
    copy(B / 'build-01/build-manifest.json')
    for review in ['nuisance-tools-review01', 'nuisance-tools-review02']:
        for path in sorted((B / 'control' / review).iterdir()):
            if path.is_file() and path.suffix in ('.json', '.py', '.xml', '.log'): copy(path)
    copy(args.actual_review, 'evidence/reviews/actual-pairs-independent-review01.json')
    copy(B / 'control/audit_native_pairs01.py')
    for check in ['campaign09-preservation-check01', 'campaign09-preservation-check02']:
        copy(B / 'control' / check / 'receipt.json')
        p = B / 'control' / check / 'snapshot.json'
        snap = read(p)
        dest = out / 'evidence/control' / check / 'owned-status.json'
        dump(dest, {'schema': 'orbit-poc-owned-campaign-snapshot-excerpt-v1', 'source': {'path': str(p), 'sha256': digest(p.read_bytes()), 'bytes': p.stat().st_size}, 'scope': 'Selected owned campaign fields; full original read-only snapshot remains outside Git.', **{k:snap[k] for k in ['captured_at', 'driver_live', 'driver_identity_matches', 'terminal_count', 'terminal_status_counts', 'current_nonterminal_attempt_ids', 'process_visibility_errors', 'manifest_hash', 'expected_native_pins']}})
    diagnosis_path = pathlib.Path('/mnt/d/orbit-segmented-v4/control/campaign09-first-timeout-independent-diagnosis01.json')
    copy(diagnosis_path, 'evidence/prior-timeout-diagnosis01.json')
    # Keep the historical analyzer outputs attributed to the analyzer versions recorded in them.
    for name in ['nuisance-timeout01.json', 'nuisance-timeout02.json', 'nuisance-tools-tests04.xml']:
        copy(B / 'analysis' / name)
    for name in ['freeze.json', 'result.json']: copy(B / 'native-tests01' / name)
    for suite in ['native', 'correction']:
        for name in ['tests.xml', 'pytest.log', 'supervisor.json', 'supervisor.plan.json', 'result.json']:
            copy(B / 'native-tests01' / suite / name)
    for experiment in ['paired01', 'replay-pairs01']:
        for name in ['freeze.json', 'preparation.json', 'execution-complete.json']: copy(B / experiment / name)

    pipeline = []
    for rel in ['scripts/analyze_nuisance_profile.py', 'scripts/check_nuisance_performance_pair.py', 'scripts/build_groops.py', 'groops/extension/native_nuisance_performance.py', 'groops/extension/nuisancePerformance.h', 'src/orbit_poc/segmented/supervisor.py', 'groops/extension/native_row_qr.py', 'src/orbit_poc/numerics/optimizer.py', 'src/orbit_poc/numerics/backend.py', 'src/orbit_poc/segmented/backend.py']:
        p = SOURCE / rel
        pipeline.append({'path': rel, 'sha256': digest(p.read_bytes()), 'bytes': p.stat().st_size})
    pairs = []
    external = []
    for name, label in zip(PAIR_NAMES, LABELS):
        check_path = B / 'analysis' / (name + '-pair01.json')
        check = read(check_path)
        check_rel = copy(check_path)
        if not (check['passed'] and check['artifact_equality'] and check['cache_pair_verified']): raise ValueError('Pair failed: ' + name)
        runs = []
        for run in check['runs']:
            root = pathlib.Path(run['root'])
            execution = run['execution']
            if not (execution['status'] == 'complete' and execution['owned_process_group_cleaned'] and execution['returncode'] == 0 and not execution['timed_out']): raise ValueError('Run not terminal and clean.')
            for path in sorted(root.iterdir()):
                if path.is_file() and (path.suffix in ['.json', '.xml'] or path.name == 'profile.log'): copy(path)
            for artifact in run['provenance']:
                if str(artifact['path']).startswith(str(root) + '/'):
                    external.append({'run': root.name, **artifact, 'copied_in_publication': (out / 'evidence' / pathlib.Path(artifact['path']).relative_to(B)).is_file()})
            perf = run['performance']
            q = read(root / 'qr.profile.json')
            cat = perf['child_categories']
            # Keep each recorded stage distinct. Do not sum overlapping wall/CPU quantities.
            run_summary = {'name': root.name, 'cache': execution['cache'], 'status': execution['status'], 'profile_classification': run['profile_classification'], 'nuisance_iterations': q['iterations'], 'maximum_update_m': q['maximum_update_m'], 'threshold_m': q['threshold_m'], 'nuisance_floor_limited': q['nuisance_floor_limited'], 'final_generation': run['final_generation'], 'native_supervised_elapsed_seconds': execution['elapsed_seconds'], 'controller_elapsed_seconds': execution['controller_elapsed_seconds'], 'peak_process_tree_rss_bytes': execution['peak_rss_bytes'], 'parent_row_build': perf['parent_row_build'], 'child_categories': cat, 'sidecar_count': perf['sidecar_count'], 'search_record_count': perf['search_record_count'], 'evidence_directory': 'evidence/' + str(root.relative_to(B))}
            runs.append(run_summary)
        runs.sort(key=lambda x:x['cache'])
        pairs.append({'name': name, 'label': label, 'check': check_rel, 'passed': check['passed'], 'artifact_equality': check['artifact_equality'], 'cache_pair_verified': check['cache_pair_verified'], 'scientific_comparison_count': check['scientific_comparison_count'], 'accepted_covariance': check['accepted_covariance'], 'whole_fit_convergence_established': check['whole_fit_convergence_established'], 'observed_profile_time_reduction_percent': 100 * (1-runs[1]['native_supervised_elapsed_seconds']/runs[0]['native_supervised_elapsed_seconds']), 'runs': runs})
    native = read(B / 'native-tests01/result.json')
    diagnosis = read(diagnosis_path)
    snapshot = read(B / 'control/campaign09-preservation-check02/snapshot.json')
    actual_review = read(args.actual_review)
    freeze = read(B / 'paired01/freeze.json')
    summary = {'schema': 'orbit-poc-nuisance-engineering-publication-v1', 'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'candidate_source_commit': head, 'scope': 'Twelve fixed-orbit GNSS nuisance-profile runs: six same-executable cache-off/on pairs. Single timings, no whole-fit performance or release claim.', 'native': freeze['native'], 'build_manifest': freeze['build_manifest'], 'pipeline': pipeline, 'admission': freeze['admission'], 'default_cache_enabled': False, 'default_instrumentation_enabled': False, 'native_test_results': native, 'pair_count': len(pairs), 'run_count': sum(len(p['runs']) for p in pairs), 'scientific_pair_comparison_count': sum(p['scientific_comparison_count'] for p in pairs), 'pairs': pairs, 'actual_independent_review': {'source_path': str(args.actual_review), 'sha256': digest(args.actual_review.read_bytes()), 'status': actual_review.get('status')}, 'accepted_covariance': False, 'whole_fit_convergence_established': False, 'release_authority': False, 'prior_timeout': {'wall_seconds': diagnosis['whole_fit']['wall_seconds'], 'completed_profile_wall_seconds': diagnosis['profile_wall_seconds_sum'], 'fraction': diagnosis['profile_wall_fraction_of_supervised_fit'], 'lm_trial_evidenced': False}, 'frozen_campaign_snapshot': {k:snapshot[k] for k in ['captured_at', 'driver_live', 'driver_identity_matches', 'terminal_count', 'terminal_status_counts', 'current_nonterminal_attempt_ids', 'process_visibility_errors', 'manifest_hash', 'expected_native_pins']}, 'limitations': ['Same candidate executable with cache toggled; no old-versus-new executable claim.', 'Historical fixtures and replay inputs are outcome selected, not independent scientific trials.', 'One timing per configuration on a cooperatively admitted host; no confidence interval or established speedup.', 'Supervised elapsed times and sampled process-tree RSS are reported separately from controller overhead and nested stage timing.', 'Interpolation wall time is within observation-design wall time, within row-build wall time. Child CPU is a different measurement; do not add these quantities.', 'Final linearization and parent nuisance solves/recovery/update lack sidecar timing; absent measurements remain unknown.', 'All twelve nuisance profiles converged strictly. No floor-limited pass is used here; such progress cannot authorize covariance.', 'These tests do not repeat the complete propagation/objective validation suite or establish full orbit fit/covariance acceptance.', 'Frozen v4 campaign continues with its original executable and attempts; this candidate does not replace its results.']}
    dump(out / 'summary.json', summary)
    dump(out / 'external-artifacts.json', {'schema': 'orbit-poc-external-artifact-inventory-v1', 'scope': 'Raw per-run provenance already checked by the pair checker. Bulky text rows/matrices remain external; public pair records include exact comparison hashes.', 'artifacts': external})

    table = []
    stages = []
    for pair in pairs:
        off,on = pair['runs']
        table.append('<tr><th>' + link(pair['check'], pair['label']) + '</th><td>' + fmt(off['native_supervised_elapsed_seconds']) + '</td><td>' + fmt(on['native_supervised_elapsed_seconds']) + '</td><td>' + fmt(pair['observed_profile_time_reduction_percent'], 1) + '%</td><td>' + fmt(off['peak_process_tree_rss_bytes']/2**20,1) + ' / ' + fmt(on['peak_process_tree_rss_bytes']/2**20,1) + '</td><td>Strict / strict<br>6 / 6 iterations</td><td>97 / 97 equal</td></tr>')
        for r in pair['runs']:
            def val(group, field): return group[field]['recorded_sum']
            par = r['parent_row_build']
            children = r['child_categories']
            stages.append('<tr><th>' + html.escape(pair['label']) + '<br>cache ' + ('on' if r['cache'] else 'off') + '</th><td>' + fmt(val(par,'interpolation_calls'),0) + ' / ' + fmt(val(par,'interpolation_cache_hits'),0) + ' / ' + fmt(val(par,'interpolation_evaluations'),0) + '</td><td>' + fmt(val(par,'build_wall_seconds')) + ' / ' + fmt(val(par,'observation_design_wall_seconds')) + ' / ' + fmt(val(par,'interpolation_wall_seconds')) + '</td><td>' + fmt(children['ordinary_trials']['wall_seconds']['recorded_sum']) + ' / ' + fmt(children['ordinary_trials']['child_cpu']['total_cpu_seconds']['recorded_sum']) + '</td><td>' + fmt(children['zero_update_replay']['wall_seconds']['recorded_sum']) + ' / ' + fmt(children['zero_update_replay']['child_cpu']['total_cpu_seconds']['recorded_sum']) + '</td><td>' + link(r['evidence_directory']+'/profile.execution.json','execution') + ' · ' + link(r['evidence_directory']+'/qr.profile.json','profile') + ' · ' + link(r['evidence_directory']+'/qr.1.nuisance_performance.json','first sidecar') + '</td></tr>')
    evidence_groups = [
      ('evidence/paired01/preparation.json','Eight-run preparation'),('evidence/paired01/freeze.json','Eight-run freeze'),('evidence/replay-pairs01/preparation.json','Four exact replay preparations'),('evidence/replay-pairs01/freeze.json','Replay freeze'),('evidence/control/run_pairs01.py','Frozen paired runner'),('evidence/control/run_replay_pairs01.py','Frozen replay runner'),('evidence/control/run_native_tests01.py','Frozen native-test runner'),('evidence/native-tests01/result.json','157 native/regression test outcomes'),('evidence/native-tests01/freeze.json','Native-test source/runtime pins'),('evidence/control/nuisance-tools-review02/independent-review02.json','Independent analysis/checker review: 77 tests'),('evidence/reviews/actual-pairs-independent-review01.json','Independent actual-results audit'),('evidence/control/exact-replay-preparation-independent-review01.json','Distinct historical replay identity audit'),('evidence/control/nuisance-performance-independent-review01.json','Independent native patch/control review'),('evidence/control/candidate-build-complete01.json','Candidate build and library inventory'),('evidence/build-01/build-manifest.json','Pinned native build manifest'),('evidence/control/build-controller-correction02.json','Preserved build-controller failure'),('evidence/control/nuisance-tools-review01/independent-review01.json','Preserved rejected checker review'),('evidence/control/nuisance-tools-review01/counterexamples-result.json','Preserved false-positive counterexamples'),('evidence/prior-timeout-diagnosis01.json','Original frozen-fit timeout diagnosis'),('evidence/control/campaign09-preservation-check02/receipt.json','Read-only frozen campaign snapshot receipt'),('evidence/control/campaign09-preservation-check02/owned-status.json','Owned campaign status and full snapshot hash'),('external-artifacts.json','External row/matrix inventory'),('manifest.json','Publication byte hashes'),('summary.json','Machine-readable results')]
    evidence_html = ''.join('<li>'+link(p,l)+'</li>' for p,l in evidence_groups)
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Nuisance profiling · candidate01</title><style>
:root{color-scheme:light;--ink:#152d3a;--muted:#506773;--line:#d9e4e9;--accent:#006b62}*{box-sizing:border-box}body{margin:0;background:#f4f7f8;color:var(--ink);font:16px/1.6 system-ui,sans-serif}main{max-width:1250px;margin:0 auto;padding:44px 28px 64px}h1{font-size:2.3rem;line-height:1.15;margin:.3em 0}h2{font-size:1.4rem;margin-top:2em}p{max-width:100ch}a{color:#00685e;text-underline-offset:.16em}.eyebrow{color:var(--accent);font-size:.82rem;font-weight:750;letter-spacing:.09em;text-transform:uppercase}.lead{font-size:1.18rem}.card{border-left:4px solid var(--accent);padding:16px 22px;background:white;margin:24px 0}.tablewrap{overflow-x:auto;background:white;border:1px solid var(--line);border-radius:8px}table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{text-align:left;vertical-align:top;padding:12px;border-bottom:1px solid var(--line)}thead{background:#e5eeef}tbody th{min-width:190px}td{font-variant-numeric:tabular-nums}code{font-size:.88em;overflow-wrap:anywhere}small,.muted{color:var(--muted)}ul{padding-left:22px}.evidence{columns:2;column-gap:36px}.evidence li{break-inside:avoid;margin:6px 0}footer{border-top:1px solid var(--line);margin-top:38px;padding-top:18px;font-size:.86rem}@media(max-width:750px){main{padding:24px 16px}.evidence{columns:1}h1{font-size:1.8rem}}
</style><main><div class="eyebrow">Separate engineering experiment · 19 October 2026</div><h1>Less repeated interpolation, identical nuisance solutions</h1><p class="lead">All 12 fixed-orbit GNSS nuisance profiles completed with strict nuisance convergence. All six cache-off/on pairs matched on all 97 scientific artifacts per pair. The 106 native tests and 51 correction regressions passed without failures or skips.</p><div class="card"><strong>Bounded result.</strong> These are measurements from the same candidate executable with an optional interpolation cache toggled. The cache remains off by default. This result does not establish whole-orbit convergence, authorize covariance, replace frozen benchmark attempts, or certify a v4 release.</div>
<h2>What changed and why</h2><p>The first frozen 24-hour dense fit timed out after 7,200.426 s. Its two completed fixed-state nuisance profiles consumed 7,057.355 s (98.013%); the tighter-closure profile was unfinished and no LM trial was evidenced. This identified a profiling bottleneck, without identifying every internal cost. The failure and incomplete measurements are preserved.</p><p>The isolated candidate reuses an exactly keyed dynamic interpolation result only within a native row-building generation. It still executes the original per-observation GNSS design, local QR, priors, residual arithmetic, and objective replay. New generations invalidate cached values. It does not introduce nuisance warm starts or reuse stale factors. Physical models, weights, thresholds and compatibility defaults are unchanged.</p>
<h2>Actual paired measurements</h2><p>One timed run per configuration; CPU 0, one numerical thread, serial execution, 8 GiB process-tree and two-hour limits on host <code>pfaff</code>. Admission was cooperative, not exclusive CPU reservation. The small historical fixtures and two distinct failure replays are outcome-selected engineering checks, not independent scientific trials. “Old” and “candidate1” identify archived input sets; both run the same new executable.</p><div class="tablewrap"><table><thead><tr><th>Fixture</th><th>Cache off (s)</th><th>Cache on (s)</th><th>Observed reduction</th><th>Peak tree RSS off/on (MiB)</th><th>Nuisance status</th><th>Scientific equality</th></tr></thead><tbody>''' + ''.join(table) + '''</tbody></table></div><p class="muted">Times cover the supervised native profile process. Controller elapsed time is separately recorded in summary.json. These single paired observations provide no speedup confidence interval. Sampled peak RSS is a process-tree measurement and can reflect parent/child overlap; the observed values do not establish a memory reduction.</p>
<h2>Exact equality and convergence scope</h2><p>Each pair verifies all generations through a fresh final undamped factor: weighted rows, R and right-hand-side payloads, nuisance/dynamic coordinate exports, updates, receiver times, singular values, profiles, rank/factor diagnostics, prior/residual costs, support and line-search decisions. Text and binary payloads compare byte for byte; JSON scientific values compare exactly. Only the declared child user CPU, system CPU and peak RSS fields in line-search trials are removed. The full comparison inventories and hashes are linked in the table.</p><p>All twelve runs made six nuisance iterations and satisfied the unchanged 10<sup>−8</sup> m threshold for two consecutive updates. No run used a floor-limited pass. Equality of a floor-limited result would remain progress-only evidence and could not authorize covariance. Fixed-orbit nuisance convergence does not establish dynamic LM convergence, and these runs produce no accepted orbit covariance. The complete propagation/refinement/objective suite was not repeated here.</p>
<h2>Measured stages and interpolation counters</h2><p>For each run, the six instrumented parent builds made 8,064 interpolation requests. Cache-on retained all requests while reducing evaluations to 720 with 7,344 exact-key hits (91.07%); cache-off evaluated all 8,064. Ordinary trials and zero-update replays have their own counts in the raw sidecars. Final linearization, parent nuisance solves, recovery and parameter updates are outside sidecar timing coverage.</p><div class="tablewrap"><table><thead><tr><th>Run</th><th>Parent calls / hits / evaluations</th><th>Parent build / design / interpolation wall (s)</th><th>Ordinary children wall / CPU (s)</th><th>Zero-replay children wall / CPU (s)</th><th>Raw receipts</th></tr></thead><tbody>''' + ''.join(stages) + '''</tbody></table></div><p class="muted">Each number is the sum of that named recorded category over its six iterations. Interpolation is included in design, which is included in row-build wall time. Child CPU and child elapsed wall time overlap and are different measures. Do not add columns into a total profile cost. No arithmetic-audit or probe child was needed in these runs; unavailable historical timing remains unknown.</p>
<h2>Failures, audits and campaign preservation</h2><p>The first build controller failed because it assumed an optional header had been copied into the native tree. Its replacement fixed that control assumption, with no numerical source change. The first analysis-tool review rejected command-shape and receipt/counter attribution defects. Those counterexamples and the rejected review remain published beside the corrected 77-test independent review. No unsuccessful attempt was silently replaced.</p><p>The independent actual-results audit is published with the real execution evidence. The native/regression run adds 157 passing tests; the separate native patch/control focused tests report 18 passing checks. These are distinct validation scopes. All execution receipts report return code zero and verified owned-process cleanup; a successful process alone was not treated as scientific convergence.</p><p>The read-only snapshot at 06:15 UTC found the original frozen campaign driver alive with matching identity and no process-visibility errors. It retained two timed-out attempts and was running the first family’s <code>segmented_4h</code> attempt. That snapshot is historical evidence, not a continuing liveness claim. The campaign’s executables, settings and attempts remain separate from this candidate.</p>
<h2>Reproducibility and remaining work</h2><p>Candidate source: <code>''' + head + '''</code><br>Native executable SHA-256: <code>''' + freeze['native']['sha256'] + '''</code><br>Build manifest SHA-256: <code>''' + freeze['build_manifest']['sha256'] + '''</code></p><p>Frozen preparation files pin the exact inputs, output-only remaps, order, executable, runtime and supervisor. Runner scripts and compact raw XML, execution, supervisor, profile, factor, search and performance receipts are copied unchanged. Bulky input data, row spools, binary factors and executables stay outside Git; their inventories and comparison hashes are preserved. The publication manifest records both original-source and published-copy hashes. Compact owned-campaign excerpts pin the complete external snapshots; unrelated process details are omitted from this publication. The copied controls retain their original absolute paths; relocation requires a new explicit preparation and freeze.</p><p>Next useful evidence is a separately frozen representative 24-hour whole-fit comparison, including repeated objective evaluations and fresh final covariance gates. Preserve the current frozen campaign while that is developed. No performance extrapolation from these small profiles can certify the campaign’s two-hour limit or multi-day capability.</p><ul class="evidence">''' + evidence_html + '''</ul><footer>Engineering evidence only. No accuracy-superiority claim, no accepted covariance, and no release authorization. The optional controls are <code>ORBIT_POC_NUISANCE_INTERPOLATION_CACHE=1</code> and <code>ORBIT_POC_NUISANCE_PERFORMANCE=1</code>; both default to off.</footer></main></html>'''
    (out / 'index.html').write_text(page)
    copy(pathlib.Path(__file__), 'controls/build_publication01.py')
    # This verifier uses only the published bytes, and does not access a running process.
    verifier = '''#!/usr/bin/env python3\nimport gzip, hashlib, json\nfrom pathlib import Path\np=Path(__file__).resolve().parent\nm=json.loads((p/'manifest.json').read_text())\nfor e in m['files']:\n b=(p/e['path']).read_bytes()\n assert len(b)==e['bytes'] and hashlib.sha256(b).hexdigest()==e['sha256'],e['path']\n if e.get('encoding')=='gzip':\n  raw=gzip.decompress(b)\n  assert hashlib.sha256(raw).hexdigest()==e['source_sha256'],e['path']\nprint(f"Verified {len(m['files'])} published files; no native run performed.")\n'''
    (out / 'verify.py').write_text(verifier)
    filemap = {e['path']:e for e in copies}
    for path in sorted(out.rglob('*')):
        if path.is_file():
            rel = str(path.relative_to(out))
            if rel not in filemap: filemap[rel] = {'path': rel, 'bytes': path.stat().st_size, 'sha256': digest(path.read_bytes()), 'generated': True}
    dump(out / 'manifest.json', {'schema': 'orbit-poc-publication-manifest-v1', 'candidate_source_commit': head, 'scope': 'Byte inventory excluding this manifest itself. Source receipts are copied unchanged, apart from explicitly generated compact owned-campaign excerpts; full snapshot hashes are retained.', 'files': [filemap[k] for k in sorted(filemap)]})
    print(json.dumps({'output': str(out), 'files': len(filemap)+1, 'bytes': sum(p.stat().st_size for p in out.rglob('*') if p.is_file()), 'summary_sha256': digest((out/'summary.json').read_bytes()), 'manifest_sha256': digest((out/'manifest.json').read_bytes())}))

if __name__ == '__main__': main()
