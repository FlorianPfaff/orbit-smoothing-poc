"""Fabricated provenance tests: never execute a scientific candidate."""
import importlib.util
import json
from pathlib import Path

import pytest

SPEC=importlib.util.spec_from_file_location('history_under_test',Path(__file__).with_name('assemble_correctness_history.py'))
H=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(H)
COMMIT='e7c93a97603cddcbef2f163257a34f48577c5516'


def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(value if isinstance(value,bytes) else H.encoded(value))
    return path


def pin(path):
    raw=path.read_bytes()
    return {'path':str(path),'sha256':H.sha(raw),'bytes':len(raw)}


def fixture(tmp_path,native05=True):
    source_files={f'source/file-{i:03}.cpp':H.sha(str(i).encode()) for i in range(758)}
    source_sha=H.sha(json.dumps(source_files,sort_keys=True,separators=(',',':')).encode())
    plan={'schema':'orbit-poc-correctness-history-plan-v1',
          'assembler_sha256':H.sha(Path(H.__file__).read_bytes()),'source_sha256':source_sha,
          'attempts':{},'output':str(tmp_path/'assembled')}
    parts={}
    for number in ('04','05'):
        native=number=='05' and native05
        stage=tmp_path/'staged'/number
        remote=f'/actual/private/execution-{number}'
        execution={'schema':'orbit-poc-correctness-execution-v1',
                   'paths':{'root':remote,'run':remote+'/validation-'+number}}
        ep=put(stage/'execution.json',execution)
        run={'status':'passed' if native else 'failed','finished_at':'2026-10-15T00:00:00Z',
             'final_cleanup':{'verified':True},'execution':pin(ep),
             'resume':{'status':'not_applicable','reason':'no_campaign_running'},
             'source':{'sha256':source_sha,'files':source_files},'steps':[{'name':'build'}]}
        if native:run['native']={'sha256':'a'*64}
        rp=put(stage/'pipeline.json',run)
        status='passed' if native else 'failed'
        audit={'passed':native,'numerical_components':'fabricated fixture'}
        summary={'schema':'orbit-correction-evidence-report-v4','candidate_evidence_status':status,
                 'release_acceptance':'not_assessed','frozen_campaign_reclassified':False,
                 'native_tests':{'status':'passed' if native else 'missing'}}
        bundle=stage/'publication'
        contents={'index.html':f'<html>Fixture attempt {number}: {status}</html>'.encode(),
                  'summary.json':H.encoded(summary),'independent-audit.json':H.encoded(audit),
                  'provenance/pipeline-04.json':H.encoded(H.scrub(run)),
                  'provenance/execution.json':H.encoded(H.scrub(execution)),
                  'historical/pipeline-02.json':b'{"status":"failed"}\n',
                  'historical/pipeline-03.json':b'{"status":"interrupted"}\n'}
        originals={'provenance/pipeline-04.json':rp.read_bytes(),'provenance/execution.json':ep.read_bytes()}
        records=[]
        for name,raw in contents.items():
            put(bundle/name,raw)
            records.append({'destination':name,'published_sha256':H.sha(raw),'published_bytes':len(raw),
                            'original_sha256':H.sha(originals.get(name,raw))})
        manifest={'schema':'orbit-poc-correctness-publication-bundle-v4','release_acceptance':'not_assessed',
                  'frozen_campaign_reclassified':False,'reported_audit_passed':native,
                  'reported_pipeline_status':run['status'],'reported_evidence_status':status,
                  'native_sha256':'a'*64 if native else None,'source_inventory_sha256':source_sha,
                  'missing_receipts':[] if native else [{'role':'native_tests','reason':'not produced'}],
                  'files':records}
        mp=put(bundle/'manifest.json',manifest);put(bundle/'README.txt',b'Immutable fixture bundle.\n')
        post={'schema':'orbit-poc-correctness-postprocess04-run-v1','status':'completed',
              'finished_at':'2026-10-15T01:00:00Z','scientific_status':status,
              'validation_pipeline':{'path':remote+'/validation-'+number+'/pipeline.json','sha256':H.sha(rp.read_bytes())},
              'source':{'sha256':source_sha,'commit':COMMIT},'steps':[]}
        for name,target,code in [('audit','independent-audit.json',0 if native else 1),
                                 ('report','summary.json',0),('collect','manifest.json',0)]:
            post['steps'].append({'name':name,'cleanup_verified':True,'returncode':code,
                                 'result':{'sha256':H.sha((bundle/target).read_bytes())}})
        pp=put(stage/'postprocess.json',post)
        plan['attempts'][number]={'bundle':{'path':str(bundle),'manifest_sha256':H.sha(mp.read_bytes())},
                                 'execution':pin(ep),'run':pin(rp),'postprocess':pin(pp),'execution_root':remote}
        parts[number]={'execution':ep,'run':rp,'postprocess':pp,'manifest':mp,'bundle':bundle}
    review={'schema':'orbit-poc-infrastructure04-independent-review-v1','passed':True,
            'classification':'infrastructure_failure_dynamic_loader_abi','scientific_validation':'not_run',
            'accepted_native_identity':False,'linked_executable_present':True,'owned_cleanup_rechecked':True,
            'live_exact_owned_processes':[],'source_sha256':source_sha,
            'pipeline':pin(parts['04']['run']),'postprocess':pin(parts['04']['postprocess']),
            'publication_manifest':pin(parts['04']['manifest']),
            'private_message':'Failure in /actual/private/libc.so.6 requires GLIBC_2.38.'}
    review_path=put(tmp_path/'evidence'/'independent04.json',review)
    plan['independent_review04']=pin(review_path)
    plan_path=put(tmp_path/'control'/'plan.json',plan)
    return {'plan':plan,'path':plan_path,'parts':parts,'review':review_path}


def run(f):
    put(f['path'],f['plan'])
    return H.assemble(f['path'],H.sha(f['path'].read_bytes()))


def mutate_raw(f,number,kind,change):
    path=f['parts'][number][kind];value=H.decode(path.read_bytes());change(value);put(path,value)
    f['plan']['attempts'][number][kind]=pin(path)


def mutate_bundle(f,number,change):
    path=f['parts'][number]['manifest'];value=H.decode(path.read_bytes());change(value);put(path,value)
    f['plan']['attempts'][number]['bundle']['manifest_sha256']=H.sha(path.read_bytes())


def test_copies_verbatim_and_keeps_failed_attempt_identity(tmp_path):
    f=fixture(tmp_path);result=run(f);out=Path(f['plan']['output'])
    assert result['release_acceptance']=='not_assessed'
    assert result['frozen_campaign_reclassified'] is False
    assert result['attempts']['04']['classification']=='infrastructure_failure_before_native_validation'
    assert result['attempts']['04']['native_tests_status']=='missing'
    assert result['attempts']['05']['reported_evidence_status']=='passed'
    assert result['attempts']['04']['missing_receipts']==[{'role':'native_tests','reason':'not produced'}]
    assert result['attempts']['04']['run_sha256']!=result['attempts']['05']['run_sha256']
    assert result['source_commit']==COMMIT
    for number in ('04','05'):
        for original in f['parts'][number]['bundle'].rglob('*'):
            if original.is_file():
                assert (out/('attempt-'+number)/original.relative_to(f['parts'][number]['bundle'])).read_bytes()==original.read_bytes()
    for entry in result['files']:
        raw=(out/entry['destination']).read_bytes()
        assert H.sha(raw)==entry['sha256'] and len(raw)==entry['bytes']
    text=(out/'index.html').read_text()
    assert 'GLIBC_2.38' in text and 'not strict nuisance convergence' in text
    assert 'Attempt 04' in text and 'Attempt 05' in text
    public_review=(out/'evidence/independent-attempt04-review.json').read_bytes()
    assert b'/actual/private/' not in public_review and str(tmp_path).encode() not in public_review
    assert b'private-path-sha256:' in public_review
    assert result['independent_attempt04_review']['original_sha256']==H.sha(f['review'].read_bytes())


def test_failed05_is_preserved_without_substitution(tmp_path):
    f=fixture(tmp_path,native05=False);result=run(f)
    assert all(v['reported_evidence_status']=='failed' for v in result['attempts'].values())
    assert all(v['native_tests_status']=='missing' for v in result['attempts'].values())


@pytest.mark.parametrize('kind',['execution','run','postprocess'])
def test_pinned_raw_artifact_tamper_rejected(tmp_path,kind):
    f=fixture(tmp_path);f['parts']['05'][kind].write_bytes(b'{}')
    with pytest.raises(ValueError,match='Pinned artifact changed'):run(f)
    assert not Path(f['plan']['output']).exists()


@pytest.mark.parametrize('name',['index.html','summary.json','historical/pipeline-02.json','provenance/pipeline-04.json'])
def test_bundle_file_tamper_rejected(tmp_path,name):
    f=fixture(tmp_path);(f['parts']['04']['bundle']/name).write_bytes(b'tampered')
    with pytest.raises(ValueError,match='Publication bytes differ'):run(f)


def test_manifest_tamper_rejected(tmp_path):
    f=fixture(tmp_path);f['parts']['05']['manifest'].write_bytes(b'{}')
    with pytest.raises(ValueError,match='Bundle manifest changed'):run(f)


def test_extra_unlisted_file_rejected(tmp_path):
    f=fixture(tmp_path);put(f['parts']['04']['bundle']/'extra.txt',b'extra')
    with pytest.raises(ValueError,match='Unlisted publication'):run(f)


@pytest.mark.parametrize('destination',['../outside','/absolute','./index.html','x/../index.html','manifest.json'])
def test_unsafe_bundle_destinations_rejected(tmp_path,destination):
    f=fixture(tmp_path)
    mutate_bundle(f,'04',lambda m:m['files'][0].update(destination=destination))
    with pytest.raises(ValueError,match='Unsafe or duplicate'):run(f)


def test_symlink_bundle_file_rejected(tmp_path):
    f=fixture(tmp_path);path=f['parts']['04']['bundle']/'index.html'
    external=put(tmp_path/'external.html',path.read_bytes());path.unlink();path.symlink_to(external)
    with pytest.raises(ValueError,match='escapes bundle|symlink'):run(f)


@pytest.mark.parametrize('field,value',[
    ('status','running'),('final_cleanup',{'verified':False}),
    ('resume',{'status':'resumed'}),('execution',{'sha256':'0'*64}),
    ('source',{'sha256':'0'*64,'files':{}})])
def test_unclosed_or_misattributed_run_rejected(tmp_path,field,value):
    f=fixture(tmp_path);mutate_raw(f,'05','run',lambda d:d.update({field:value}))
    with pytest.raises(ValueError):run(f)


def test_source_map_digest_recomputed(tmp_path):
    f=fixture(tmp_path)
    mutate_raw(f,'05','run',lambda d:d['source']['files'].update({'source/file-000.cpp':'0'*64}))
    with pytest.raises(ValueError,match='inventory digest'):run(f)


@pytest.mark.parametrize('change',[
    lambda d:d.update(status='running'),
    lambda d:d['validation_pipeline'].update(sha256='0'*64),
    lambda d:d['validation_pipeline'].update(path='/wrong/pipeline.json'),
    lambda d:d['source'].pop('commit'),
    lambda d:d['source'].update(commit='short'),
    lambda d:d['steps'][2]['result'].update(sha256='0'*64),
    lambda d:d['steps'][0].update(returncode=1),
    lambda d:d['steps'][1].update(cleanup_verified=False),
    lambda d:d['steps'].append(d['steps'][0]),
])
def test_invalid_postprocess_rejected(tmp_path,change):
    f=fixture(tmp_path);mutate_raw(f,'05','postprocess',change)
    with pytest.raises(ValueError):run(f)


def test_distinct_source_commits_rejected(tmp_path):
    f=fixture(tmp_path);mutate_raw(f,'05','postprocess',lambda d:d['source'].update(commit='f'*40))
    with pytest.raises(ValueError,match='Source commits differ'):run(f)


def test_swapped_attempts_rejected(tmp_path):
    f=fixture(tmp_path);f['plan']['attempts']['04'],f['plan']['attempts']['05']=f['plan']['attempts']['05'],f['plan']['attempts']['04']
    with pytest.raises(ValueError,match='another attempt'):run(f)


def test_same_execution_relabel_rejected(tmp_path):
    f=fixture(tmp_path);f['plan']['attempts']['05']=f['plan']['attempts']['04']
    with pytest.raises(ValueError,match='same execution'):run(f)


@pytest.mark.parametrize('change',[
    lambda m:m.update(release_acceptance='passed'),
    lambda m:m.update(frozen_campaign_reclassified=True),
    lambda m:m.update(reported_evidence_status='passed'),
    lambda m:m.update(reported_audit_passed=True),
    lambda m:m.update(native_sha256='a'*64),
    lambda m:m['files'][3].update(original_sha256='0'*64),
])
def test_publication_promotion_or_identity_tamper_rejected(tmp_path,change):
    f=fixture(tmp_path);mutate_bundle(f,'04',change)
    with pytest.raises(ValueError):run(f)


@pytest.mark.parametrize('change',[
    lambda r:r.update(passed=False),
    lambda r:r.update(scientific_validation='passed'),
    lambda r:r.update(accepted_native_identity=True),
    lambda r:r.update(linked_executable_present=False),
    lambda r:r.update(owned_cleanup_rechecked=False),
    lambda r:r.update(live_exact_owned_processes=[123]),
    lambda r:r['pipeline'].update(sha256='0'*64),
    lambda r:r['postprocess'].update(sha256='0'*64),
    lambda r:r['publication_manifest'].update(sha256='0'*64),
])
def test_independent04_review_must_agree_and_bind_actual04(tmp_path,change):
    f=fixture(tmp_path);value=H.decode(f['review'].read_bytes());change(value);put(f['review'],value)
    f['plan']['independent_review04']=pin(f['review'])
    with pytest.raises(ValueError):run(f)


def test_review_raw_tamper_rejected(tmp_path):
    f=fixture(tmp_path);f['review'].write_bytes(b'{}')
    with pytest.raises(ValueError,match='Pinned artifact changed'):run(f)


def test_wrong_assembler_hash_rejected(tmp_path):
    f=fixture(tmp_path);f['plan']['assembler_sha256']='0'*64
    with pytest.raises(ValueError,match='assembler changed'):run(f)


def test_wrong_plan_hash_rejected(tmp_path):
    f=fixture(tmp_path)
    with pytest.raises(ValueError,match='plan changed'):H.assemble(f['path'],'0'*64)


def test_existing_output_is_never_modified(tmp_path):
    f=fixture(tmp_path);sentinel=put(Path(f['plan']['output'])/'sentinel',b'keep')
    with pytest.raises(ValueError,match='NEW absolute'):run(f)
    assert sentinel.read_bytes()==b'keep'


def test_output_inside_input_directory_rejected(tmp_path):
    f=fixture(tmp_path);f['plan']['output']=str(f['parts']['04']['bundle']/'new')
    with pytest.raises(ValueError,match='inside an input root'):run(f)


def test_combined_size_bound_rejected_before_write(tmp_path,monkeypatch):
    f=fixture(tmp_path)
    largest=max(sum(p.stat().st_size for p in part['bundle'].rglob('*') if p.is_file()) for part in f['parts'].values())
    monkeypatch.setattr(H,'MAX_TOTAL',largest+1024)
    # Both individually fit; together the copied evidence exceeds the reduced test limit.
    with pytest.raises(ValueError,match='Combined history exceeds'):run(f)
    assert not Path(f['plan']['output']).exists()


@pytest.mark.parametrize('raw',[b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":1e999}',b'[]'])
def test_strict_json(raw):
    with pytest.raises(ValueError):H.decode(raw)
