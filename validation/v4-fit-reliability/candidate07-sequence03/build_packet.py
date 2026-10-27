"""Assemble an interruption-aware, static receipt packet; no numerical execution."""
from pathlib import Path
import argparse
import datetime
import hashlib
import html
import json
import re
import stat

BASE = Path('/mnt/d/orbit-v41-recovery02')
GATES = ('native-tests', 'native-fail-fast-tests', 'correction-tests',
         'synthetic-refinement-log_drag_ou', 'synthetic-refinement-pulses',
         'flight-refinement', 'eccentric-24h-refinement', 'objective-log_drag_ou',
         'objective-pulses', 'nuisance-replay', 'nuisance-replay-candidate1-point012')
COLD = ('cold-pulses', 'cold-density')
AUDITS = ('scientific', 'selected', 'rank', 'export')
CORRECT = BASE/'candidate07-correctness03'
COLD_ROOT = BASE/'candidate07-cold03'
SEQUENCE = BASE/'density-trial-sequence03'
COLLECTION = BASE/'candidate07-postboot-collection-control03'
MANIFESTS = BASE/'candidate07-postboot-input-manifests02'
AUDIT_ROOT = BASE/'candidate07-postboot-saved-audits03'
SNAPSHOT = Path('/mnt/d/orbit-v41-density-trial-candidate07/source-snapshot.json')
SNAPSHOT_SHA = '4b997bcda7c94bce973389542895dca05a3fde6e7a53fdb4178fb61eaf22646e'
SOURCE_SHA = 'b49cd3938791f1e3d6dcc828cb414d7010cf3175aa604d23c4631e95f485413a'
NATIVE_SHA = '28c725765201e4702875ec8407d3bc497aa4bdfa3092a305b15a3233cfbd675d'
INTERRUPTION = BASE/'candidate07-sequence03-interruption-independent-review01/review.json'
INTERRUPTION_SHA = '559ab88a472c346eba5ca5d24584b56d2f7e95a8e37ef3eefaf105f4a0a026c4'
RESOURCE_REVIEW = BASE/'candidate07-local-rendering-control-deviation-review01/review.json'
RESOURCE_REVIEW_SHA = 'b0b76269016d7a379f003fa57d21a16df2160cb1bac3cffd99d7a0dc7b123692'
RESOURCE_BASE = Path('/mnt/d/orbit-publication-review/2026-10-26-prior-work-fulltext02')
RESOURCE_ADDENDUM = RESOURCE_BASE/'resource-observation-addendum01/addendum.json'
RESOURCE_ADDENDUM_SHA = '7094f675d431d222a560d285927c4d15b49212d50105d77ac1737301342e56df'
MISSING = (SEQUENCE/'result.json', COLD_ROOT/'result.json', COLD_ROOT/'detached-result.json',
           COLD_ROOT/'cold-density/backend-result.json', COLD_ROOT/'cold-density/strict-result.json',
           COLD_ROOT/'cold-density/fit/point-015-trial-012/profile.execution.json')
COPY_LIMIT, PACKET_LIMIT = 4*1024**2, 32*1024**2


def require(condition, message):
    if not condition: raise ValueError(message)


def sha(raw): return hashlib.sha256(raw).hexdigest()


def encode(value): return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n').encode()


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key: '+key); result[key] = value
        return result
    def invalid(value): raise ValueError('Nonfinite JSON constant: '+value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


class Receipts:
    def __init__(self):
        self.files, self.records, self.links, self.by_path = {}, {}, {}, {}

    def add(self, role, path, expected=None, required=False):
        path = Path(path)
        require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', role) and '..' not in Path(role).parts,
                'Unsafe receipt role')
        require(role not in self.records, 'Duplicate receipt role: '+role)
        if not path.exists():
            require(not required and expected is None and not path.is_symlink(), 'Required receipt missing: '+str(path))
            self.records[role] = dict(role=role, path=str(path), status='unavailable', sha256=None, bytes=None, target=None)
            return None
        require(path.is_absolute() and not path.is_symlink() and path.resolve(strict=True)==path,
                'Receipt path is aliased: '+str(path))
        before = path.stat(); require(stat.S_ISREG(before.st_mode), 'Receipt is not regular')
        digest = hashlib.sha256(); raw = bytearray()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024*1024), b''):
                digest.update(block)
                if before.st_size<=COPY_LIMIT: raw.extend(block)
        after = path.stat()
        require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==
                (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns), 'Receipt changed during read')
        value = digest.hexdigest(); require(expected is None or value==expected, 'Receipt identity differs: '+str(path))
        previous = self.by_path.get(str(path)); target = previous['target'] if previous else None
        if previous: require((previous['sha256'],previous['bytes'])==(value,before.st_size), 'Receipt changed between roles')
        if before.st_size<=COPY_LIMIT and target is None:
            target = 'receipts/'+role; require(target not in self.files, 'Duplicate packet path')
            self.files[target] = bytes(raw)
        record = dict(role=role,path=str(path),sha256=value,bytes=before.st_size,target=target,
                      status='copied_byte_exact' if target else 'external_exact_pin')
        self.records[role] = record; self.by_path[str(path)] = record
        if target: self.links[role] = target
        return record

    def json(self, role, path, expected=None, required=False):
        record = self.add(role,path,expected,required)
        if record is None: return None
        if record['target']: return decode(self.files[record['target']])
        require(record['bytes']<=16*1024**2, 'JSON inspection exceeds16MiB bound')
        raw = Path(path).read_bytes(); require(sha(raw)==record['sha256'], 'External JSON changed')
        return decode(raw)

    def pinned(self, role, pin):
        require(isinstance(pin,dict) and {'path','sha256'}<=set(pin), 'Malformed source receipt pin')
        record = self.add(role,pin['path'],pin['sha256'],True)
        if 'bytes' in pin: require(record['bytes']==pin['bytes'], 'Pinned receipt size differs')
        return record

    def family(self, role, root, names):
        for name in names:
            self.add(role+'/'+name,Path(root)/name)


def supervision(value):
    if not isinstance(value,dict): return dict(status='unavailable',complete_exit_zero=False)
    cleanup = value.get('cleanup',{})
    return dict(status=value.get('status','unknown'),returncode=value.get('returncode'),
                complete_exit_zero=value.get('status')=='complete' and value.get('returncode')==0,
                cleanup_certified=value.get('owned_process_group_cleaned') is True and cleanup.get('verified') is True
                    and cleanup.get('empty_tree_certificate')=='kernel_ECHILD' and cleanup.get('remaining')==[],
                elapsed_seconds=value.get('elapsed_seconds'),peak_process_tree_rss_bytes=value.get('peak_process_tree_rss_bytes'),
                cleanup=cleanup,signals_received=value.get('signals_received',[]),
                owned_process_group_cleaned=value.get('owned_process_group_cleaned',False))


def terminal_files(store, role, root):
    value = store.json(role+'/result.json',root/'result.json')
    store.family(role,root,('source-before.json','source-after.json','runtime-before.json','runtime-after.json','actual-jobs.json','admission.json'))
    return value


def audit_rows(store):
    controller = terminal_files(store,'audits/controller',AUDIT_ROOT)
    controller_certified = isinstance(controller,dict) and controller.get('status')=='complete' \
        and controller.get('sources_unchanged') is True and controller.get('runtime_unchanged') is True \
        and not controller.get('error')
    result = {}
    for kind in AUDITS:
        root = AUDIT_ROOT/kind; prefix = 'audits/'+kind
        worker = store.json(prefix+'/result.json',root/'result.json')
        sup = store.json(prefix+'/supervisor.json',root/'supervisor.json')
        context = store.json(prefix+'/context.json',root/'context.json')
        store.family(prefix,root,('supervisor.plan.json','worker.log'))
        if context and context.get('source_plan'): store.pinned(prefix+'/controller-plan.json',context['source_plan'])
        manifest = None
        if worker and worker.get('manifest'):
            pin = worker['manifest']; manifest = store.json(prefix+'/input-manifest.json',pin['path'],pin['sha256'],True)
            for field in ('executor_source','original_mathematical_source','orchestration_source'):
                if manifest.get(field): store.pinned(prefix+'/'+field+'.py',manifest[field])
        valid = isinstance(worker,dict) and worker.get('schema')=='candidate07-postboot-audit-worker-v1' and worker.get('action')==kind
        scope_status = worker.get('status','unavailable') if worker else 'unavailable'
        supervised = supervision(sup)
        effective = scope_status if valid and supervised['complete_exit_zero'] and supervised.get('cleanup_certified') is True and controller_certified else ('failed_or_incomplete_supervision_or_controller' if worker or sup else 'unavailable')
        result[kind] = dict(status=effective,worker_recorded_status=scope_status,worker_schema_valid=valid,
                            controller_certified=controller_certified,
                            supervisor=supervised,error=worker.get('error') if worker else None,
                            audit=worker.get('audit') if worker else None,
                            executor_source=worker.get('executor_source') if worker else None,
                            manifest_source_attribution={key:manifest.get(key) for key in ('executor_source','original_mathematical_source','orchestration_source')} if manifest else None,
                            result_link=store.links.get(prefix+'/result.json'),covariance_authority=False,
                            whole_pair_complete=False,independent_review_status='see_separate_post_audit_review')
    return result,controller


def control(store,label,root,review,expected_result=None,expected_review=None):
    value = store.json('controls/'+label+'/result.json',root/'result.json',expected_result)
    independent = store.json('controls/'+label+'/review.json',review,expected_review)
    for filename,key in (('supervisor.json','supervisor'),('junit.xml','junit')):
        if value and value.get(key): store.pinned('controls/'+label+'/'+filename,value[key])
        else: store.add('controls/'+label+'/'+filename,root/filename)
    store.family('controls/'+label,root,('supervisor.plan.json','source-before.json','source-after.json','runtime-before.json','runtime-after.json'))
    jobs = value.get('jobs',{}) if value else {}
    for name in sorted(jobs):
        for filename,key in (('supervisor.json','supervisor'),('junit.xml','junit')):
            if jobs[name].get(key): store.pinned('controls/'+label+'/'+name+'/'+filename,jobs[name][key])
            else: store.add('controls/'+label+'/'+name+'/'+filename,root/name/filename)
        store.add('controls/'+label+'/'+name+'/supervisor.plan.json',root/name/'supervisor.plan.json')
    counted_jobs = {name:job['tests']['counts'] for name,job in jobs.items() if isinstance(job.get('tests'),dict) and isinstance(job['tests'].get('counts'),dict)}
    top_counts = (value.get('tests') or {}).get('counts') if value else None
    recorded_counts = top_counts if top_counts is not None else {key:sum(row[key] for row in counted_jobs.values()) for key in ('tests','failures','errors','skipped')} if counted_jobs else None
    counts_scope = 'actual top-level test receipt' if top_counts is not None else 'recorded aggregate counts from '+str(len(counted_jobs))+'/'+str(len(jobs))+' jobs; missing counts do not imply zero executed tests'
    reviewed_suites = [row for row in (independent or {}).get('actual_suites',[]) if 'tests' in row]
    reviewed_counts = {key:sum(row[key] for row in reviewed_suites) for key in ('tests','failures','errors','skipped')} if reviewed_suites else None
    return dict(status=value.get('status','unavailable') if value else 'unavailable',
                tests=value.get('tests') if value else None,jobs=jobs,error=value.get('error') if value else None,
                recorded_test_counts=recorded_counts,test_count_scope=counts_scope,
                independently_reviewed_test_counts=reviewed_counts,
                independently_reviewed_suites=independent.get('actual_suites') if independent else None,
                sources_unchanged=value.get('sources_unchanged') if value else None,
                runtime_unchanged=value.get('runtime_unchanged') if value else None,
                independent_review_status=independent.get('status',independent.get('classification','available')) if independent else 'unavailable',
                independent_review=independent,
                result_link=store.links.get('controls/'+label+'/result.json'),scope='control fixtures, not scientific results')


def per_stage(audits,stage):
    result = {}
    for kind,item in audits.items():
        value = item.get('audit') or {}; rows = []
        for key in ('stages','gates','cold','cases','outcomes'):
            if isinstance(value.get(key),list): rows.extend(row for row in value[key] if isinstance(row,dict) and row.get('stage')==stage)
        result[kind] = dict(overall_status=item['status'],recorded_rows=rows,
                            applicability='recorded_rows' if rows else ('not_applicable' if kind=='scientific' and stage not in GATES[3:] or kind in ('rank','export') and stage not in COLD else 'no_row_available'))
    return result


def render(report,store):
    esc = lambda value: html.escape(str(value),quote=True)
    def link(role):
        return '<a href="'+esc(store.links[role])+'">receipt</a>' if role in store.links else 'unavailable/external (see manifest)'
    rows = []
    for row in report['outcomes']:
        checks = []
        for kind,value in row['saved_audit_evidence'].items():
            detail = str(value['recorded_rows'][0].get('status',value['recorded_rows'][0].get('audit_status','recorded'))) if value['recorded_rows'] else value['applicability']
            checks.append(kind+': '+value['overall_status']+' / '+detail)
        checks = '; '.join(checks)
        rows.append('<tr><td>'+esc(row['stage'])+'</td><td>'+esc(row['original_recorded_status'])+'</td><td>'+esc(row['supervisor']['status'])+'</td><td>'+esc(checks)+'</td><td>'+link('original/'+row['stage']+'/strict-result.json')+'</td></tr>')
    audit_rows_html = ['<tr><td>'+esc(kind)+'</td><td>'+esc(item['status'])+'</td><td>'+esc(item['worker_recorded_status'])+'</td><td>'+link('audits/'+kind+'/result.json')+'</td></tr>' for kind,item in report['saved_audits'].items()]
    controls = ['<tr><td>'+esc(name)+'</td><td>'+esc(item['status'])+'</td><td>'+esc(item['recorded_test_counts'])+'<br>'+esc(item['test_count_scope'])+('<br>Independent failure review: '+esc(item['independently_reviewed_test_counts']) if item['independently_reviewed_test_counts'] else '')+'</td><td>'+link('controls/'+name+'/result.json')+'</td></tr>' for name,item in report['controls'].items()]
    collection = report['collection_evidence']; collected_supervision = collection['supervisor']
    collection_html = ('<h2>Saved-input collection</h2><p class="notice">Effective collection outcome: '+esc(collection['status'])+
        '. Controller completion records its closing checks; it does not imply the collection worker succeeded.</p>'
        '<table><tr><th>Supervisor</th><th>Elapsed seconds / return code</th><th>Worker / manifests</th><th>Cleanup</th><th>Receipt</th></tr><tr><td>'+
        esc(collected_supervision['status'])+'</td><td>'+esc(collected_supervision.get('elapsed_seconds'))+' / '+esc(collected_supervision.get('returncode'))+
        '</td><td>'+esc(collection['worker_recorded_status'])+' / collection receipt: '+esc(collection['collection_receipt_available'])+
        ', complete manifest set: '+esc(collection['all_prescribed_manifests_available'])+'</td><td>'+esc(collected_supervision.get('cleanup'))+
        '</td><td>'+link('collection/worker/supervisor.json')+'</td></tr></table>')
    deviation = report['resource_control_deviation']
    resource_html = ('<h2>Disclosed local resource-control deviation</h2><p class="notice">'+esc(deviation['description'])+
        '</p><p>'+esc(deviation['timing_and_numerical_limits'])+'</p><p>'+esc(deviation['rerun_policy'])+
        '</p><p>Independent review: '+link('resource-deviation/review.json')+'; original addendum: '+link('resource-deviation/addendum.json')+
        '; preserved failed rendering log: '+link('resource-deviation/page-render.stderr')+'.</p>')
    details = esc(json.dumps(report,indent=2,sort_keys=True,allow_nan=False))
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Candidate07 interrupted validation</title>'
            '<style>body{font:16px system-ui;max-width:1400px;margin:2rem auto;padding:0 1rem;color:#18212b}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:.6rem;border:1px solid #ccd3da;text-align:left;vertical-align:top}th{background:#edf2f7}pre{white-space:pre-wrap;overflow-wrap:anywhere}.notice{padding:1rem;background:#fff2d5;border-left:5px solid #a66d00}a{color:#075fa5}</style>'
            '<h1>Candidate07: interrupted validation and saved-output audits</h1><p class="notice">'+esc(report['summary'])+'</p>'
            '<p>This is the one-hour synthetic leo500/quiet/normal diagnostic with original GNSS-only initialization. It is not flight accuracy evidence or completion of a frozen benchmark.</p>'
            +resource_html+
            '<h2>All13 original outcomes</h2><table><tr><th>Stage</th><th>Original recorded outcome</th><th>Original supervisor</th><th>Saved audit rows</th><th>Strict receipt</th></tr>'+''.join(rows)+'</table>'
            +collection_html+
            '<h2>Four prescribed saved-output audits</h2><p>Unavailable rows are not executed audits. Supervisor failure or absence overrides a partial worker pass. Available-scope success does not complete the interrupted pair.</p><table><tr><th>Audit</th><th>Effective outcome</th><th>Worker recorded scope</th><th>Receipt</th></tr>'+''.join(audit_rows_html)+'</table>'
            '<h2>Controls</h2><table><tr><th>Qualification</th><th>Recorded outcome</th><th>Recorded counts</th><th>Receipt</th></tr>'+''.join(controls)+'</table>'
            '<h2>Missing original terminal receipts</h2><ul>'+''.join('<li>'+esc(path)+'</li>' for path in report['missing_original_receipts'])+'</ul>'
            '<h2>Limits and identities</h2><ul>'+''.join('<li>'+esc(text)+'</li>' for text in report['limitations'])+'</ul>'
            '<p><a href="report.json">Machine-readable report</a> · <a href="inputs-manifest.json">Exact input receipts</a> · <a href="SHA256SUMS">Packet checksums</a></p>'
            '<details><summary>Complete report, including failures and original cleanup signals</summary><pre>'+details+'</pre></details></html>').encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--builder-sha256',required=True)
    parser.add_argument('--post-audit-review',type=Path)
    parser.add_argument('--post-audit-review-sha256')
    args = parser.parse_args(); output = args.output
    builder_path = Path(__file__).resolve(); builder = builder_path.read_bytes()
    require(re.fullmatch('[0-9a-f]{64}',args.builder_sha256) and sha(builder)==args.builder_sha256,'Actual assembler source identity differs')
    require(re.fullmatch(re.escape(str(BASE))+r'/candidate07-sequence03-publication[0-9]{2,}/packet',str(output)), 'Fresh publicationNN/packet output required')
    require(not output.exists() and not output.is_symlink(), 'Output already exists; preserve it')
    require(bool(args.post_audit_review)==bool(args.post_audit_review_sha256), 'Review path/hash must be paired')
    store = Receipts()
    interruption = store.json('interruption/review.json',INTERRUPTION,INTERRUPTION_SHA,True)
    resource_review = store.json('resource-deviation/review.json',RESOURCE_REVIEW,RESOURCE_REVIEW_SHA,True)
    resource_addendum = store.json('resource-deviation/addendum.json',RESOURCE_ADDENDUM,RESOURCE_ADDENDUM_SHA,True)
    require(resource_review['disclosure']['sha256']==RESOURCE_ADDENDUM_SHA and resource_addendum['local_execution'] is True,
            'Resource-control disclosure identity or attribution differs')
    store.add('resource-deviation/file-metadata-utc.tsv',RESOURCE_ADDENDUM.parent/'file-metadata-utc.tsv',
              resource_review['disclosure']['metadata_sha256'],True)
    store.add('resource-deviation/original-evidence.json',RESOURCE_BASE/'evidence.json',resource_addendum['prior_evidence_sha256'],True)
    store.add('resource-deviation/source-evidence.sha256',RESOURCE_REVIEW.parent/'source-evidence.sha256',
              '4c662ac3b480fd95b9262cba5b573861c0948253a31a0d37a2f13cfc474a61ab',True)
    for name,digest in (('text-extraction.stderr','a54128a71bbe2f55d51bc123709314c4c1ec05afb41ee868176dcbec540950f3'),
                        ('page-render.stderr','e5e0464529b60ae1bdcaaa660a95b34a9a005a65f623e047b2f28c98f7f480f9'),
                        ('page-render02.stderr','0f6739a802e72060b4222263c4a9499b2c72ac7a688f965555baf52c92b42a64')):
        store.add('resource-deviation/'+name,RESOURCE_BASE/name,digest,True)
    snapshot = store.json('candidate/source-snapshot.json',SNAPSHOT,SNAPSHOT_SHA,True)
    canonical = json.dumps(snapshot['files'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    require(sha(canonical)==SOURCE_SHA, 'Candidate canonical source identity differs')
    require(set(map(str,MISSING))==set(interruption['missing_original_terminal_paths']), 'Interruption missing-file inventory differs')
    for path in MISSING: require(not path.exists() and not path.is_symlink(), 'Original missing terminal unexpectedly appeared: '+str(path))
    for number,pin in enumerate(interruption['source_pins']): store.pinned('interruption/source-'+str(number).zfill(2)+'-'+Path(pin['path']).name,pin)
    store.family('original/sequence',SEQUENCE,('plan.json','launch.json','sequence.py','correctness-terminal-audit.json'))
    store.family('original/correctness',CORRECT,('result.json','detached-result.json','plan.json','freeze.json'))
    original_gates = decode(store.files[store.links['original/correctness/result.json']])
    require([row['stage'] for row in original_gates['stages']]==list(GATES),'Original correctness inventory differs')
    original_by_stage = {row['stage']:row for row in original_gates['stages']}
    store.family('original/cold',COLD_ROOT,('plan.json','freeze.json'))
    collected = terminal_files(store,'collection/controller',COLLECTION)
    collection_worker = store.json('collection/worker/result.json',COLLECTION/'collect/result.json')
    collection_supervisor = store.json('collection/worker/supervisor.json',COLLECTION/'collect/supervisor.json')
    store.family('collection/worker',COLLECTION/'collect',('supervisor.plan.json','context.json','worker.log'))
    collection = store.json('collection/collection.json',MANIFESTS/'collection.json')
    file_map = store.add('collection/file-map.json',MANIFESTS/'file-map.json')
    partial_collection = store.add('collection/recovered-individual-evidence.json',MANIFESTS/'recovered-individual-evidence.json')
    if collection:
        for section in ('manifests','ledgers'):
            for name,pin in sorted(collection.get(section,{}).items()): store.pinned('collection/'+section+'/'+name+'.json',pin)
    context_path = COLLECTION/'collect/context.json'
    if context_path.exists():
        context = decode(store.files[store.links['collection/worker/context.json']])
        if context.get('source_plan'): store.pinned('collection/controller-plan.json',context['source_plan'])
    collection_supervised = supervision(collection_supervisor)
    collection_controller_valid = isinstance(collected,dict) and collected.get('status')=='complete' \
        and collected.get('sources_unchanged') is True and collected.get('runtime_unchanged') is True and not collected.get('error')
    collection_worker_valid = isinstance(collection_worker,dict) and collection_worker.get('schema')=='candidate07-postboot-audit-worker-v1' \
        and collection_worker.get('action')=='collect' and collection_worker.get('status')=='collected_with_original_gaps_retained'
    complete_manifests = isinstance(collection,dict) and collection.get('schema')=='candidate07-terminal-collection-v1' \
        and collection.get('status') in ('prepared','prepared_with_evidence_gaps') and collection.get('manifests_complete') is True \
        and set(collection.get('manifests',{}))==set(AUDITS)
    collection_complete = collection_controller_valid and collection_worker_valid and complete_manifests and file_map is not None \
        and collection_supervised['complete_exit_zero'] and collection_supervised.get('cleanup_certified') is True
    collection_status = 'collected_with_original_gaps_retained' if collection_complete else \
        collection_supervised['status'] if collection_supervised['status'] not in ('complete','unavailable') else 'failed_or_incomplete_collection'
    collection_evidence = dict(status=collection_status,complete=collection_complete,supervisor=collection_supervised,
        controller_recorded_status=collected.get('status') if collected else 'unavailable',controller_closing_checks_valid=collection_controller_valid,
        controller_recorded_job=(collected.get('jobs') or {}).get('collect') if collected else None,
        worker_recorded_status=collection_worker.get('status') if collection_worker else 'unavailable',worker_result_available=collection_worker is not None,
        worker_error=collection_worker.get('error') if collection_worker else None,collection_receipt_available=collection is not None,
        all_prescribed_manifests_available=complete_manifests,file_map_available=file_map is not None,
        partial_individual_receipt_available=partial_collection is not None,partial_receipt_does_not_complete_collection=True,
        numerical_audit_or_covariance_authority=False)
    audits,controller = audit_rows(store)
    outcomes = []
    for stage in GATES+COLD:
        root = (CORRECT if stage in GATES else COLD_ROOT)/stage; role = 'original/'+stage
        expected = original_by_stage.get(stage,{})
        strict = store.json(role+'/strict-result.json',root/'strict-result.json',expected.get('strict_result',{}).get('sha256'))
        sup = store.json(role+'/supervisor.json',root/'supervisor.json',expected.get('execution',{}).get('sha256'))
        store.family(role,root,('supervisor.plan.json','request.json'))
        row = dict(stage=stage,original_recorded_status=strict.get('status','unknown') if strict else 'missing_strict_receipt',
                   original_strict_receipt=store.records[role+'/strict-result.json'],supervisor=supervision(sup),
                   candidate_source_identity=SOURCE_SHA,saved_audit_evidence=per_stage(audits,stage))
        if stage in COLD:
            backend = store.json(role+'/backend-result.json',root/'backend-result.json')
            row['backend_recorded'] = {key:backend.get(key) for key in ('status','converged','covariance_valid','accepted_iterations','trial_evaluations','objective','native_binary_sha256','source_hash','confirmation_checks')} if backend else None
            if backend: require(backend['native_binary_sha256']==NATIVE_SHA and backend['source_hash']==SOURCE_SHA,'Original cold source/native identity differs')
        if stage=='cold-pulses': row['preserved_individual_receipt_review'] = interruption['preserved_pulse']
        if stage=='cold-density':
            row.update(original_recorded_status='interrupted_without_backend_or_strict_terminal',strict_converged=False,
                       accepted_final_covariance=False,original_cleanup_receipt_available=False,partial_progress=interruption['density'])
        outcomes.append(row)
    controls = {}
    for label,directory,review in (
        ('qualification02','candidate07-postboot-audit-qualification02','candidate07-postboot-audit-qualification02-independent-failure-review01'),
        ('qualification04','candidate07-postboot-audit-qualification04','candidate07-postboot-audit-qualification04-independent-review01')):
        controls[label] = control(store,label,BASE/directory,BASE/review/'review.json')
    controls['supplementary_adapter14'] = control(store,'supplementary_adapter14',BASE/'candidate07-postboot-adapter-tests04',BASE/'candidate07-postboot-adapter-tests04-independent-review01/review.json','f3ef32430ee000d09147bf62a655aaca9ed508a18e06f7f04afc3c75f7d39945','b711457e0bdff0e4cfece3b8f0778bcd6d6e3a113a41740082fa9f9621b2ce27')
    controls['supplementary_cold31'] = control(store,'supplementary_cold31',BASE/'candidate07-postboot-cold-tests03',BASE/'candidate07-postboot-cold-tests03-independent-review01/review.json','521610fb1bfc1c422325264ec4b662d96d34ab346b0b51a9a04a1a47f5a4838a','74ad3e7f7aac980964858de4452f1d9a0cd73470f7ae7517482e79063e15eb71')
    for role,path in (
        ('history/candidate04/result.json',BASE/'one-hour-run01/result.json'),
        ('history/candidate04/pulse.json',BASE/'one-hour-run01/cold-pulses/backend-result.json'),
        ('history/candidate04/density.json',BASE/'one-hour-run01/cold-density/backend-result.json'),
        ('history/candidate06/report.json',BASE/'candidate06-sequence02-publication03/packet/report.json'),
        ('history/candidate06/published.json',BASE/'candidate06-sequence02-publication03/published.json')): store.add(role,path)
    review = store.json('audits/independent-review.json',args.post_audit_review,args.post_audit_review_sha256,True) if args.post_audit_review else None
    report = dict(schema='candidate07-sequence03-publication-v1',status='diagnostic_failures_or_incomplete_evidence',
        created_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        summary='The original sequence was interrupted by a host reboot. Eleven correctness checks and the pulse fit have individual terminal receipts; density has no terminal result or original cleanup certificate. Later saved-output audits are reported separately. This packet does not complete the original pair or establish completion of a frozen campaign.',
        sequence_status='interrupted_across_boot_without_original_terminal',outcomes=outcomes,saved_audits=audits,controls=controls,
        collection_evidence=collection_evidence,
        resource_control_deviation=dict(status='disclosed_independently_reviewed_operational_deviation',
            description='Local PDF extraction, probing and PNG rendering occurred outside the admitted numerical process tree while the parent reported the density objective active. This violated the continuing local-renderer restriction.',
            timing_and_numerical_limits='Exact process intervals and numerical or timing impact were not measured. Output-write timestamps do not establish execution intervals or core separation. These timings cannot support an uncontended-performance claim during the reported overlap. No harmlessness, numerical failure or timeout is attributed to the rendering; this evidence does not establish overlap with the later cold fits.',
            rerun_policy='All original outcomes remain. No automatic rerun, replacement, timeout adjustment or correctness-threshold change is authorized by this disclosure.',
            observed_output_write_times_utc=resource_review['observed_evidence']['reported_output_write_times_utc'],
            exact_process_intervals_measured=False,numerical_or_timing_impact_measured=False,
            uncontended_timing_claim_during_reported_overlap=False,harmlessness_certified=False,
            numerical_failure_attributed_to_rendering=False,automatic_rerun_authorized=False,
            review_sha256=RESOURCE_REVIEW_SHA,addendum_sha256=RESOURCE_ADDENDUM_SHA,
            original_failed_rendering_evidence_preserved=True,review=resource_review,addendum=resource_addendum),
        collection_controller_status=collected.get('status') if collected else 'unavailable',audit_controller_status=controller.get('status') if controller else 'unavailable',
        audit_controller_evidence={key:controller.get(key) for key in ('status','error','sources_unchanged','runtime_unchanged','last_owned_cleanup_verified','signals_received')} if controller else None,
        post_audit_independent_review=review,post_audit_independent_review_status='available' if review else 'pending',
        missing_original_receipts=list(map(str,MISSING)),source_receipt_links=store.links,
        identities=dict(snapshot_file_sha256=SNAPSHOT_SHA,canonical_source_identity=SOURCE_SHA,backend_recorded_native_sha256=NATIVE_SHA),
        limitations=['This is a diagnostic publication; the frozen v3.1/v4 benchmarks remain separate and unchanged.',
            'The disclosed local PDF-processing resource deviation limits timing claims; exact intervals and numerical impact are unmeasured, and no harmlessness or failure attribution follows.',
            'Both cold cases use original GNSS-only initialization, with no accepted-state or nuisance donor.',
            'The pulse supervision includes seven recorded cleanup SIGTERM entries; its ECHILD result is not signal-free.',
            'Strict nuisance convergence differs from numerical-floor-limited progress, which cannot authorize covariance.',
            'Unavailable rank/export audit rows provide no completed audit or final density covariance certificate.',
            'A nuisance line-search acceptance does not establish outer trial12 acceptance; no density final covariance is inferred.',
            'Saved selected/rank/export checks do not establish full independent covariance reconstruction or uncertainty calibration.',
            'The original builder and its19 tests are preserved; this packet uses the included standalone static assembler.',
            'Actual final packet bytes require independent content audit before publication.'],
        whole_pair_complete=False,release_ready=False,release_authority=False,covariance_authority=False,accuracy_claim=False,
        frozen_benchmarks_unchanged=True,original_cleanup_inferred_from_boot_change=False)
    require(sha(builder_path.read_bytes())==args.builder_sha256,'Assembler source changed during reading')
    store.files['build_packet.py'] = builder
    store.files['report.json'] = encode(report); store.files['index.html'] = render(report,store)
    manifest = dict(schema='candidate07-interrupted-static-packet-inputs-v1',builder_sha256=sha(builder),
                    receipts=list(store.records.values()),original_missing_paths=list(map(str,MISSING)),
                    numerical_recomputation_performed=False,compact_copies_byte_exact=True)
    store.files['inputs-manifest.json'] = encode(manifest)
    store.files['README.txt'] = b'Static interrupted-candidate07 diagnostic packet. Read report.json and index.html. Compact original receipts are byte-exact; large originals are external exact pins. No numerical recomputation, source modification, original aggregate fabrication, covariance or release authority. The included build_packet.py is the actual assembler. Independent final-byte review is required.\n'
    require(all(len(raw)<=COPY_LIMIT for raw in store.files.values()) and sum(map(len,store.files.values()))<=PACKET_LIMIT,'Packet exceeds4MiB member or32MiB payload bound')
    for path in MISSING: require(not path.exists() and not path.is_symlink(),'Original missing terminal appeared during assembly')
    if not output.parent.exists(): output.parent.mkdir()
    require(output.parent.resolve(strict=True)==output.parent,'Aliased output parent')
    output.mkdir()
    for name,raw in sorted(store.files.items()):
        target=output/name; target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as stream: stream.write(raw)
    sums=''.join(sha(raw)+'  '+name+'\n' for name,raw in sorted(store.files.items()))
    with (output/'SHA256SUMS').open('x') as stream: stream.write(sums)
    print(json.dumps(dict(packet=str(output),files=len(store.files),sha256sums_sha256=sha(sums.encode()),report_sha256=sha(store.files['report.json']),inputs_manifest_sha256=sha(store.files['inputs-manifest.json']),independent_packet_review='pending')))


if __name__=='__main__': main()
