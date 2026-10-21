from pathlib import Path
c=Path('/mnt/d/orbit-segmented-v4/control')
s=(c/'run_loader_alias_smoke_template03.py').read_text()
s=s.replace("P=C/'loader-alias-smoke-packet03';O=C/'loader-alias-smoke-execution02'","P=C/'loader-alias-smoke-packet04';O=C/'loader-alias-smoke-execution03'")
s=s.replace("S=B/'loader-alias-smoke-control-02';out=B/'loader-alias-smoke-execution02'","S=B/'loader-alias-smoke-control-03';out=B/'loader-alias-smoke-execution03'")
a=s.index('def verify_prior_smoke():');b=s.index('def empty(mount):',a)
s=s[:a]+'''def verify_prior_smoke():
 for item in PLAN['prior_smokes']:
  cap=item['capture'];review=item['review']
  for x in (cap,review):need(PAYLOAD[x['path']]['sha256']==x['sha256'],'Prior smoke metadata pin changed')
  prior=json.loads(base64.b64decode(PAYLOAD[cap['path']]['data']));audit=json.loads(base64.b64decode(PAYLOAD[review['path']]['data']))
  need(prior['status']=='failed' and prior['fit_attempts']==0 and prior['attempts_empty'] and prior['temporary_empty'],'Prior smoke failed boundary changed')
  need(audit['status']=='verified_failed_actual_namespace_probe' and audit['capture']['sha256']==cap['sha256'] and audit['benchmark_attempts_launched']==0 and audit['cleanup_verified'],'Prior smoke failure audit changed')
  for row in prior['files']:check(row['path'],row['sha256'])
  previous=read(audit['execution']);need(previous['status']=='failed' and previous['cleanup']['verified'] and not previous['cleanup']['live_owned_processes'],'Prior smoke cleanup changed')
  for i in previous['cleanup']['identities']:
   path=Path('/proc')/str(i['pid'])/'stat'
   if path.exists():
    fields=path.read_text().rsplit(')',1)[1].split();need(int(fields[19])!=i['start_ticks'] or fields[0]=='Z','Prior smoke owned process is live')
def verify_seal():
 audit_pin=PLAN['seal_review'];need(PAYLOAD[audit_pin['path']]['sha256']==audit_pin['sha256'],'Actual seal review changed')
 audit=json.loads(base64.b64decode(PAYLOAD[audit_pin['path']]['data']))
 need(audit['status']=='accepted_normalization_support_seal' and audit['sealed_result']==PLAN['sealed_result'] and audit['verifier_missing_count']==0 and audit['added_observation_support_files']==3 and audit['fit_attempts']==0,'Actual exact closure review required')
 result=read(PLAN['sealed_result']);need(result['status']=='sealed_metadata' and result['fit_attempts']==0 and result['native_executions']==0 and result['fit_execution_authorized'] is False,'Fresh seal not complete')
 for artifact in result['artifacts'].values():read(artifact)
 need(result['artifacts']['invocation.json']==PLAN['original_invocation'],'Fresh invocation attribution differs')
''' +s[b:]
s=s.replace('admission=d.admission(e);verify_old();verify_prior_smoke()','admission=d.admission(e);verify_old();verify_prior_smoke();verify_seal()')
s=s.replace("if k!='wrapper'", "if k not in ('wrapper','bubblewrap')").replace("'Only wrapper may change'", "'Only wrapper and control bubblewrap may change'")
s=s.replace("need(new['wrapper']==", "need(new['bubblewrap']=={'path':str(B/'bwrap-cap-01/binaries/bwrap-0.6.1-ubuntu0.3-maxargs16384'),'sha256':'7983e8f9ac3c68f072b4ea7884f4d3ce87c2086a1198412649663614113fc3f4'},'Wrong cap control binary')\n need(new['wrapper']==")
s=s.replace("p.parent==S or p==parent/'with_segmented_fit_namespace05.py'", "p.parent==S")
s=s.replace("str(S/'run_alias_probe02.py')", "str(S/'run_alias_probe03.py')")
s=s.replace("'c40ea3371aaa28675adad96262e090e1fde12033fd6b714b1afd295018a8532d'", "PLAN['expected_sealed_options_sha256']")
s=s.replace("'allowlist_sha256':'a768ddf14c8ebb7fb11e4752c9787da407f7db77ee618176ae2946ce32c4ed3d'", "'allowlist_sha256':PLAN['expected_allowlist_sha256']")
s=s.replace("empty(mount);verify_old();verify_prior_smoke()", "empty(mount);verify_old();verify_prior_smoke();verify_seal()")
s=s.replace("'original_captures':PLAN['original_captures'],'empty_writables_before'", "'original_captures':PLAN['original_captures'],'sealed_result':PLAN['sealed_result'],'seal_review':PLAN['seal_review'],'empty_writables_before'")
(c/'run_loader_alias_smoke_template04.draft.py').write_text(s)
