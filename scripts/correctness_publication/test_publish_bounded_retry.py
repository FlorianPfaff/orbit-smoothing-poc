"""Fabricated presentation-only tests; never run a native estimator."""
import copy,gzip,hashlib,importlib.util,json
from pathlib import Path
import pytest
SPEC=importlib.util.spec_from_file_location('bounded_retry',Path(__file__).with_name('publish_bounded_retry.py'))
M=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(M)

def pin(path,raw,compress=False):
    stored=gzip.compress(raw,mtime=0) if compress else raw
    path.write_bytes(stored)
    return {'path':str(path),'sha256':M.digest(stored),'bytes':len(stored),'encoding':'gzip' if compress else 'identity','original_sha256':M.digest(raw),'original_bytes':len(raw)}

def fixture(tmp_path,attempt='07',mutate=None):
    remote='/mnt/seagate10tb/orbit-v31-correctness-'+attempt+'-florianpfaff'
    source={'sha256':'c'*64,'files':{'src/a':'d'*64}}
    ident={'pid':401 if attempt=='07' else 501,'start_ticks':100,'boot_id':'test-boot'}
    d={
      'execution':{'schema':'orbit-poc-correctness-execution-v1','paths':{'root':remote,'run':remote+'/validation-07'}},
      'source_freeze':{'schema':'orbit-poc-candidate07-source-freeze-v1','source':source,'commit':'a'*40},
      'pins':{'schema':'orbit-poc-correctness-candidate07-pins-v1','source_sha256':source['sha256'],'source_file_count':1,'expected_native_test_count':106,'input_artifacts':{str(i):{'sha256':str(i)*4} for i in range(14)}},
      'pipeline':{'schema':'orbit-poc-correctness-validation07-run-v1','status':'failed','finished_at':'now','final_cleanup':{'verified':True},'source':source,'resume':{'status':'not_applicable','reason':'no_campaign_running'},'admission':{'driver_identity':{'pid':ident['pid'],'start_ticks':100},'boot_id':'test-boot'},'steps':[{'name':'clone','status':'failed' if attempt=='07' else 'passed','returncode':128 if attempt=='07' else 0}]},
      'postprocess_plan':{'driver_process':ident},
      'launch':{'driver_process':ident},
      'postprocess_launch':{},
      'audit':{'schema':'orbit-poc-correctness-independent-audit07-v1','passed':False,'errors':['native unavailable'],'input_artifacts':[]},
      'summary':{'schema':'orbit-correction-evidence-report07-v1','release_acceptance':'not_assessed','frozen_campaign_reclassified':False,'candidate_evidence_status':'failed','native_tests':{'status':'missing','counts':None},'correction_regression_tests':{'status':'missing','counts':None},'synthetic_refinement':{'log_drag_ou':{'status':'missing'},'pulses':{'status':'missing'}},'additional_refinement':{'flight':{'status':'missing'},'eccentric':{'status':'missing'}},'objectives':{'pulses':{'status':'failed','directional_scales':[{'scale':1,'status':'passed'},{'scale':.5,'status':'failed'}],'accepted_derivative_scales':[]},'log_drag_ou':{'status':'missing'}},'nuisance_replays':{'strict':{'status':'passed','resolution_status':'strict','strict_nuisance_converged':True,'progress_only_floor_validated':False},'floor':{'status':'passed','resolution_status':'progress_only_floor_validated','strict_nuisance_converged':False,'progress_only_floor_validated':True}},'integrity_errors':[]},
      'postprocess':{'schema':'orbit-poc-correctness-postprocess07-run-v1','status':'failed','finished_at':'now','steps':[{'name':n,'returncode':v,'cleanup_verified':True} for n,v in [('audit',1),('report',0),('collect',1)]],'validation_status':'failed','scientific_status':'failed','source':{'commit':'a'*40,'sha256':source['sha256'],'file_count':1}},
      'independent_review':{'scope':'fabricated independent receipt; no native work'},
      'transfer_inventory':{'remote_root':remote,'local_match_verified':True,'files':[]},
    }
    if mutate:mutate(d)
    artifacts={}
    def store(k):
        raw=M.encoded(d[k]);artifacts[k]=pin(tmp_path/(k+'.json'),raw,k in ('audit','summary'));return {'path':remote+'/'+{'execution':'control/candidate07-execution.json','pins':'control/candidate07-pins.json','source_freeze':'control/candidate07-source-freeze.json','pipeline':'validation-07/pipeline.json','postprocess_plan':'control/candidate07-postprocess-plan.json','audit':'postprocess-07-01/independent-audit.json'}.get(k,k),'sha256':M.digest(raw),'bytes':len(raw)}
    ex=store('execution');fr=store('source_freeze');d['pins']['new_source_freeze']=fr;pn=store('pins')
    d['pipeline']['execution']=ex;d['pipeline']['required_pins']=pn;pl=store('pipeline')
    d['postprocess_plan'].update(execution=ex,candidate_pins=pn);pp=store('postprocess_plan')
    d['launch'].update(execution_sha256=ex['sha256'],pins_sha256=pn['sha256']);store('launch')
    d['postprocess_launch']['plan']=pp;store('postprocess_launch')
    d['audit']['input_artifacts']=[{'role':r,'sha256':p['sha256']} for r,p in [('pipeline',pl),('execution',ex),('candidate07_pins',pn)]];a=store('audit')
    d['summary'].update(pipeline={'evidence':pl},independent_audit={'record':copy.deepcopy(d['audit']),'evidence':a});sm=store('summary')
    d['postprocess']['steps'][0].update(result=a,reported_outcome=d['audit']['passed'])
    d['postprocess']['steps'][1].update(result={**sm,'path':remote+'/postprocess-07-01/report/summary.json'},reported_outcome=d['summary']['candidate_evidence_status'])
    d['postprocess'].update(validation_pipeline=pl,plan=pp);post=store('postprocess')
    d['independent_review'].update(source_commit=d['source_freeze']['commit'],source_sha256=d['source_freeze']['source']['sha256'],artifacts={'validation-07/pipeline.json':{'sha256':pl['sha256'],'bytes':pl['bytes']},'postprocess-07-01/pipeline.json':{'sha256':post['sha256'],'bytes':post['bytes']}});store('independent_review')
    artifacts['html']=pin(tmp_path/'original.html.gz',b'<html>original failed collector report /home/florianpfaff/path</html>',True)
    for key,relative in [('pipeline','validation-07/pipeline.json'),('postprocess','postprocess-07-01/pipeline.json'),('audit','postprocess-07-01/independent-audit.json'),('summary','postprocess-07-01/report/summary.json'),('html','postprocess-07-01/report/index.html')]:
        d['transfer_inventory']['files'].append({'source':remote+'/'+relative,'original_sha256':artifacts[key]['original_sha256'],'original_bytes':artifacts[key]['original_bytes']})
    store('transfer_inventory')
    return {'schema':'orbit-poc-bounded-retry-publication-plan-v1','execution_attempt':attempt,'candidate_control_version':'07','execution_root':remote,'output':str(tmp_path/'published'),'artifacts':artifacts,'attachments':[]}

def change_file(plan,role,fn):
    raw=M.artifact(plan['artifacts'][role]);value=M.decode(raw);fn(value)
    p=Path(plan['artifacts'][role]['path']);plan['artifacts'][role]=pin(p,M.encoded(value),plan['artifacts'][role]['encoding']=='gzip')

@pytest.mark.parametrize('attempt',['07','08'])
def test_publish_preserves_failures_missing_and_no_promotion(tmp_path,attempt):
    p=fixture(tmp_path,attempt);r=M.publish(p);out=Path(p['output']);s=M.decode((out/'summary.json').read_bytes())
    assert len(s['steps'])==13 and s['steps'][-1]['status']=='not_run'
    assert s['validation_status']=='failed' and s['postprocess_status']=='failed'
    assert s['original_tests']=={'status':'missing','counts':None}
    assert s['original_nuisance_replays']['strict']['strict_nuisance_converged'] is True
    assert s['original_nuisance_replays']['floor']['strict_nuisance_converged'] is False
    assert s['original_nuisance_replays']['floor']['progress_only_floor_validated'] is True
    assert s['objectives']['pulses']['accepted_derivative_scales']==[]
    assert not s['covariance_authorized'] and s['release_acceptance']=='not_assessed'
    assert not r['scientific_gate_substitution'] and not s['frozen_campaign_reclassified']
    for name,v in r['files'].items():
        actual=(out/name).read_bytes();assert len(actual)==v['bytes'] and M.digest(actual)==v['sha256']
        if name.endswith('.gz'):
            expanded=gzip.decompress(actual);assert M.digest(expanded)==v['published_expanded_sha256']
            role=name.split('/')[1].split('.')[0]
            assert v['original_sha256']==p['artifacts'][role]['original_sha256']
    assert '/home/florianpfaff' not in gzip.decompress((out/'full/html.html.gz').read_bytes()).decode()
    assert len((out/'index.html').read_bytes())<1024*1024

@pytest.mark.parametrize('role',sorted(M.REQUIRED))
def test_any_changed_artifact_rejected(tmp_path,role):
    p=fixture(tmp_path);path=Path(p['artifacts'][role]['path']);path.write_bytes(path.read_bytes()+b'x')
    with pytest.raises(ValueError):M.inspect(p)

@pytest.mark.parametrize('mutation',[
 lambda d:d['pipeline']['final_cleanup'].update(verified=False),
 lambda d:d['pipeline'].update(status='running'),
 lambda d:d['postprocess']['steps'][2].update(cleanup_verified=False),
 lambda d:d['postprocess'].update(status='running'),
 lambda d:d['execution']['paths'].update(root='/mnt/seagate10tb/orbit-v31-correctness-08-florianpfaff'),
 lambda d:d['pins'].update(expected_native_test_count=105),
 lambda d:d['pins']['input_artifacts'].pop('0'),
 lambda d:d['pins'].update(source_sha256='wrong'),
 lambda d:d['source_freeze'].update(commit='b'*40),
 lambda d:d['pipeline']['resume'].update(status='resumed'),
 lambda d:d['pipeline']['admission']['driver_identity'].update(pid=999),
 lambda d:d['pipeline']['admission'].update(boot_id='other-boot'),
 lambda d:d['summary'].update(release_acceptance=True),
 lambda d:d['summary'].update(frozen_campaign_reclassified=True),
 lambda d:d['summary'].update(candidate_evidence_status='passed'),
 lambda d:d['pipeline'].update(native={'sha256':'unexpected'}),
 lambda d:d['pipeline']['steps'][0].update(returncode=0),
 lambda d:d['pipeline'].update(schema='old-control-schema'),
 lambda d:d['postprocess'].update(schema='old-control-schema'),
])
def test_invalid_terminal_identity_rejected(tmp_path,mutation):
    p=fixture(tmp_path,mutate=mutation)
    with pytest.raises(ValueError):M.inspect(p)

@pytest.mark.parametrize('role,mutation',[
 ('pipeline',lambda d:d['required_pins'].update(sha256='wrong')),
 ('postprocess',lambda d:d['validation_pipeline'].update(sha256='wrong')),
 ('postprocess_launch',lambda d:d['plan'].update(sha256='wrong')),
 ('summary',lambda d:d['independent_audit']['record'].update(passed=True)),
 ('summary',lambda d:d['pipeline']['evidence'].update(sha256='wrong')),
 ('launch',lambda d:d.update(pins_sha256='wrong')),
 ('audit',lambda d:d['input_artifacts'][0].update(sha256='wrong')),
 ('independent_review',lambda d:d['artifacts']['validation-07/pipeline.json'].update(sha256='other-attempt')),
 ('independent_review',lambda d:d.update(source_commit='other-candidate')),
 ('summary',lambda d:d['native_tests'].update(status='passed')),
 ('transfer_inventory',lambda d:d['files'][-1].update(original_sha256='unrelated-report')),
])
def test_cross_record_tamper_rejected(tmp_path,role,mutation):
    p=fixture(tmp_path);change_file(p,role,mutation)
    with pytest.raises(ValueError):M.inspect(p)

def test_attempt_cannot_be_relabelled(tmp_path):
    p=fixture(tmp_path);p['execution_attempt']='08'
    with pytest.raises(ValueError):M.inspect(p)

def test_gzip_original_hash_and_expanded_size_verified(tmp_path):
    p=fixture(tmp_path);p['artifacts']['html']['original_bytes']+=1
    with pytest.raises(ValueError):M.inspect(p)

def test_repinned_unrelated_html_rejected_by_original_inventory(tmp_path):
    p=fixture(tmp_path);path=Path(p['artifacts']['html']['path']);p['artifacts']['html']=pin(path,b'<html>unrelated passing report</html>',True)
    with pytest.raises(ValueError,match='Original transferred report identity'):M.inspect(p)

def test_no_overwrite(tmp_path):
    p=fixture(tmp_path);M.publish(p)
    with pytest.raises(ValueError):M.publish(p)

def test_attachments_checked_sanitized_and_safe(tmp_path):
    p=fixture(tmp_path);a=pin(tmp_path/'receipt.txt',b'/home/florianpfaff/private receipt');p['attachments']=[{'name':'reviews/r.txt','artifact':a}]
    r=M.publish(p);assert 'attachments/reviews/r.txt.gz' in r['files']
    p['output']=str(tmp_path/'other');p['attachments'][0]['name']='../escape'
    with pytest.raises(ValueError):M.publish(p)

def test_noncanonical_plan_has_both_hashes(tmp_path):
    p=fixture(tmp_path);raw=json.dumps(p).encode();r=M.publish(p,M.digest(raw))
    assert r['plan_sha256']==M.digest(raw) and r['canonical_plan_sha256']==M.digest(M.encoded(p))

def test_duplicate_and_nonfinite_json_rejected():
    for raw in [b'{"a":1,"a":2}',b'{"a":NaN}']:
        with pytest.raises(ValueError):M.decode(raw)

def test_compact_bound_rejects_instead_of_truncating(tmp_path):
    p=fixture(tmp_path);_,d,_=M.inspect(p);d['summary']['objectives']['pulses']['error']='x'*(1024*1024)
    with pytest.raises(ValueError):M.compact(p,d)
