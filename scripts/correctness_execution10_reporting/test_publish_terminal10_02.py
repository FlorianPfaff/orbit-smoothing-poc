"""Fabricated presentation fixtures; no remote calls or scientific execution."""
from pathlib import Path
import gzip,importlib.util,json
import pytest
HERE=Path(__file__).parent
s=importlib.util.spec_from_file_location('transfer_test',HERE/'test_transfer_terminal10_compact.py');t=importlib.util.module_from_spec(s);s.loader.exec_module(t)
fixture=t.fixture
s=importlib.util.spec_from_file_location('publish10',HERE/'publish_terminal10_02.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def write(p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d));return p
def pin(p):return {'path':str(p),'sha256':m.sha(p.read_bytes())}

@pytest.fixture
def prepared(fixture,tmp_path):
 root,transfer_plan=fixture;post=root/'postprocess-09-01';summary=post/'report/summary.json'
 write(summary,{'candidate_evidence_status':'failed','native_tests':{'status':'passed','counts':{'tests':106,'passed':106}},'correction_regression_tests':{'status':'passed','counts':{'tests':51,'passed':51}},'objectives':{'log_drag_ou':{'status':'failed','prior_status':'passed','accepted_derivative_scales':[],'error':'original failure'}},'nuisance_replays':{'nuisance-replay-candidate1-point012':{'status':'failed','resolution_status':'unresolved'}}})
 p=post/'pipeline.json';d=json.loads(p.read_text());d['steps'][1]['result']={**pin(summary),'bytes':summary.stat().st_size};write(p,d);transfer_plan['journals']['postprocess-09-01/pipeline.json']=pin(p)['sha256']
 value=t.m.capture(transfer_plan);out=tmp_path/'transfer';value=t.m.restore(value,out);manifest=write(tmp_path/'transfer.json',value)
 audit={'execution_attempt':'10','control_version':'09','consistency_audit_passed':True,'cleanup_verified':True,'source_commit':transfer_plan['source_commit'],'source_sha256':transfer_plan['source_sha256'],'pipeline_status':'failed','identity':{k:transfer_plan[k] for k in ('execution_sha256','pins_sha256')},'artifacts':{k:{'sha256':v} for k,v in transfer_plan['journals'].items()},'scientific_correctness_gate_passed':False}
 auditfile=write(tmp_path/'audit.json',audit)
 plan={k:transfer_plan[k] for k in ('source_commit','source_sha256','journals','execution_sha256','pins_sha256','previous_source_commit','previous_validation_sha256','installer_correction_sha256','supplementary_verification_sha256')}
 plan.update(schema='orbit-poc-terminal10-publication-plan-v1',transfer_manifest=pin(manifest),independent_audit=pin(auditfile),scrubber=pin(HERE/'recovery09/collect_correctness_publication_09.py'),output=str(tmp_path/'publication'))
 return plan,value,root,transfer_plan

def test_failed_collector_preserves_all_stages_and_failed_science(prepared):
 plan,value,root,tp=prepared;r=m.publish(plan);out=Path(r['output']);d=json.loads((out/'summary.json').read_text())
 assert len(d['planned_steps'])==13 and sum(x['status']=='not_run' for x in d['planned_steps'])==12
 assert d['candidate_evidence_status']=='failed' and d['scientific_correctness_gate_passed'] is False
 assert not d['raw_collector_available'] and not d['covariance_authorized'] and d['release_acceptance']=='not_assessed'
 text=(out/'index.html').read_text();assert 'immediate predecessor is failed execution09/source05' in text and 'compatibility basis' in text
 raw=json.loads(gzip.decompress((out/'evidence/report-summary.json.gz').read_bytes()));assert raw['objectives']['log_drag_ou']['error']=='original failure'

@pytest.mark.parametrize('field',['source_commit','source_sha256','execution_sha256','pins_sha256','previous_source_commit','previous_validation_sha256','installer_correction_sha256','supplementary_verification_sha256'])
def test_plan_attribution_mutations_fail(prepared,field):
 plan,*_=prepared;plan[field]='0'*len(plan[field])
 with pytest.raises(ValueError):m.publish(plan)
 assert not Path(plan['output']).exists()

def test_changed_transferred_bytes_fail(prepared):
 plan,value,*_=prepared;p=Path(value['local_root'])/value['files'][0]['relative'];p.write_bytes(p.read_bytes()+b' ')
 with pytest.raises(ValueError,match='bytes changed'):m.publish(plan)

def test_independent_unrelated_journal_fails_even_rehashed(prepared):
 plan,*_=prepared;p=Path(plan['independent_audit']['path']);d=json.loads(p.read_text());d['artifacts']['validation-09/pipeline.json']['sha256']='0'*64;write(p,d);plan['independent_audit']=pin(p)
 with pytest.raises(ValueError,match='journal differs'):m.publish(plan)

@pytest.mark.parametrize('field,value',[('consistency_audit_passed',False),('execution_attempt','09'),('control_version','10'),('pipeline_status','passed')])
def test_independent_attribution_mutations(prepared,field,value):
 plan,*_=prepared;p=Path(plan['independent_audit']['path']);d=json.loads(p.read_text());d[field]=value;write(p,d);plan['independent_audit']=pin(p)
 with pytest.raises(ValueError):m.publish(plan)

def test_existing_publication_is_never_changed(prepared):
 plan,*_=prepared;p=Path(plan['output']);p.mkdir();(p/'keep').write_text('keep')
 with pytest.raises(ValueError,match='must be new'):m.publish(plan)
 assert (p/'keep').read_text()=='keep'

def test_repinning_changed_summary_cannot_override_original_postprocess(prepared):
 plan,value,*_=prepared;r=next(x for x in value['files'] if x['source'].endswith('/report/summary.json'));p=Path(value['local_root'])/r['relative'];raw=b'{"candidate_evidence_status":"passed"}';packed=gzip.compress(raw,mtime=0);p.write_bytes(packed)
 old=r['bytes'];r.update(bytes=len(packed),sha256=m.sha(packed),original_bytes=len(raw),original_sha256=m.sha(raw));value['transfer_bytes']+=len(packed)-old
 mp=Path(plan['transfer_manifest']['path']);write(mp,value);plan['transfer_manifest']=pin(mp)
 with pytest.raises(ValueError,match='original postprocess result'):m.publish(plan)

def test_successful_collector_is_copied_verbatim_without_upgrading_science(prepared,tmp_path):
 plan,value,root,tp=prepared;post=root/'postprocess-09-01';pub=post/'publication';(pub/'partial.json').unlink()
 payloads={'index.html':b'<h1>Archived failed</h1>','summary.json.gz':gzip.compress(b'{"failed":true}',mtime=0),'README.md':b'exact README\n'}
 records=[]
 for name,raw in payloads.items():
  (pub/name).write_bytes(raw)
  if name=='README.md':continue
  expanded=gzip.decompress(raw) if name.endswith('.gz') else raw
  records.append({'destination':name,'encoding':'gzip' if name.endswith('.gz') else 'identity','published_bytes':len(raw),'published_sha256':m.sha(raw),'published_expanded_bytes':len(expanded),'published_expanded_sha256':m.sha(expanded)})
 manifest=write(pub/'manifest.json',{'files':records});p=post/'pipeline.json';d=json.loads(p.read_text());d['steps'][2].update(returncode=0,result=pin(manifest));write(p,d)
 tp['journals']['postprocess-09-01/pipeline.json']=pin(p)['sha256'];plan['journals']=tp['journals']
 value=t.m.restore(t.m.capture(tp),tmp_path/'transfer2');mp=write(tmp_path/'transfer2.json',value);plan['transfer_manifest']=pin(mp)
 ap=Path(plan['independent_audit']['path']);a=json.loads(ap.read_text());a['artifacts']['postprocess-09-01/pipeline.json']['sha256']=tp['journals']['postprocess-09-01/pipeline.json'];write(ap,a);plan['independent_audit']=pin(ap)
 result=m.publish(plan);out=Path(result['output']);assert all((out/'raw-report'/('README.txt' if name=='README.md' and (out/'raw-report/README.txt').exists() else name)).read_bytes()==raw for name,raw in payloads.items())
 assert json.loads((out/'summary.json').read_text())['scientific_correctness_gate_passed'] is False

def test_missing_report_stays_missing_with_full_stage_inventory(prepared,tmp_path):
 plan,value,root,tp=prepared;post=root/'postprocess-09-01';(post/'report/summary.json').unlink();p=post/'pipeline.json';d=json.loads(p.read_text());d['steps'][1].pop('result');d['steps'][1]['returncode']=1;write(p,d);tp['journals']['postprocess-09-01/pipeline.json']=pin(p)['sha256'];plan['journals']=tp['journals']
 value=t.m.restore(t.m.capture(tp),tmp_path/'transfer3');mp=write(tmp_path/'transfer3.json',value);plan['transfer_manifest']=pin(mp)
 ap=Path(plan['independent_audit']['path']);a=json.loads(ap.read_text());a['artifacts']['postprocess-09-01/pipeline.json']['sha256']=tp['journals']['postprocess-09-01/pipeline.json'];write(ap,a);plan['independent_audit']=pin(ap)
 m.publish(plan);d=json.loads((Path(plan['output'])/'summary.json').read_text());assert d['missing_report'] and d['candidate_evidence_status']=='unavailable' and len(d['planned_steps'])==13


def test_actual_identity_html_manifest_shape(prepared,tmp_path):
 plan,value,root,tp=prepared
 # Reuse the complete successful collector fixture while removing only the optional
 # redundant identity expansion fields before the immutable transfer is captured.
 original=t.m.capture
 def actual_capture(p):
  pub=root/'postprocess-09-01/publication';manifest=pub/'manifest.json'
  if manifest.exists():
   d=json.loads(manifest.read_text())
   for row in d['files']:
    if row['destination']=='index.html':
     row.pop('encoding');row.pop('published_expanded_bytes');row.pop('published_expanded_sha256')
   write(manifest,d)
   post=root/'postprocess-09-01/pipeline.json';journal=json.loads(post.read_text());journal['steps'][2]['result']=pin(manifest);write(post,journal)
   p['journals']['postprocess-09-01/pipeline.json']=pin(post)['sha256'];plan['journals']=p['journals']
  return original(p)
 t.m.capture=actual_capture
 try:test_successful_collector_is_copied_verbatim_without_upgrading_science(prepared,tmp_path)
 finally:t.m.capture=original


def test_actual_readme_txt_is_preserved(prepared,tmp_path):
 plan,value,root,tp=prepared
 original=t.m.capture
 def actual_capture(p):
  pub=root/'postprocess-09-01/publication'
  if (pub/'README.md').exists():(pub/'README.md').rename(pub/'README.txt')
  return original(p)
 t.m.capture=actual_capture
 try:
  test_successful_collector_is_copied_verbatim_without_upgrading_science(prepared,tmp_path)
  assert (Path(plan['output'])/'raw-report/README.txt').read_bytes()==b'exact README\n'
 finally:t.m.capture=original

@pytest.mark.parametrize('encoding,field',[('identity','published_expanded_bytes'),('identity','published_expanded_sha256'),('gzip','published_expanded_bytes'),('gzip','published_expanded_sha256')])
def test_explicit_identity_conflict_and_missing_gzip_metadata_reject(prepared,tmp_path,encoding,field):
 plan,value,root,tp=prepared;original=t.m.capture
 def altered_capture(p):
  pub=root/'postprocess-09-01/publication';manifest=pub/'manifest.json';d=json.loads(manifest.read_text())
  for row in d['files']:
   if row.get('encoding')==encoding:
    if encoding=='gzip':row.pop(field)
    else:row[field]=0 if field.endswith('bytes') else '0'*64
  write(manifest,d)
  post=root/'postprocess-09-01/pipeline.json';journal=json.loads(post.read_text());journal['steps'][2]['result']=pin(manifest);write(post,journal)
  p['journals']['postprocess-09-01/pipeline.json']=pin(post)['sha256'];plan['journals']=p['journals']
  return original(p)
 t.m.capture=altered_capture
 try:
  with pytest.raises((ValueError,KeyError)):test_successful_collector_is_copied_verbatim_without_upgrading_science(prepared,tmp_path)
  assert not Path(plan['output']).exists()
 finally:t.m.capture=original
