from pathlib import Path
import base64,datetime,hashlib,json
C=Path('/mnt/d/orbit-segmented-v4/control')
def pin(p):p=Path(p);return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
p=C/'native-complete-preflight02-terminal-capture01.json';capture=json.loads(p.read_bytes());raw={};rows={}
assert pin(p)['sha256']=='dc882cdd511ac942a12ca90c9497ef6dfaee7ae4649b92bfaa945c94808a36c6'
for row in capture['files']:
 data=base64.b64decode(row['base64'],validate=True);assert len(data)==row['bytes'] and hashlib.sha256(data).hexdigest()==row['sha256'] and row['path']not in raw
 raw[row['path']]=data;rows[row['path']]=row
assert len(raw)==22
root=capture['root'];plan=json.loads(raw[root+'/control/plan.json']);pipeline=json.loads(raw[root+'/control/pipeline.json']);result=json.loads(raw[root+'/run/preflight/result.json']);relink=json.loads(raw[root+'/run/preflight/baseline-relink.json'])
assert rows[root+'/control/plan.json']['sha256']=='cf35f2bbaf810f065d79d4f3f41e007e7fb58cb8c72a4d99ad39d8c54217d150'
assert result['status']=='failed' and [(r['label'],r['returncode'])for r in result['stages']]==[('baseline-link',0),('installer-equivalence',1)]
assert result['error']=="ValueError('Native complete build stage failed: installer-equivalence')"
error=json.loads(raw[root+'/run/preflight/installer-equivalence.stdout'])
assert error=={'status':'failed_before_owned_output','passed':False,'error':'Symlink path: /mnt/c/users/emper/documents/codex/2026-10-13/i-x20/work/v3/native-env/bin/python'}
assert result['baseline_relink']=={'path':root+'/run/preflight/baseline-relink.json','sha256':rows[root+'/run/preflight/baseline-relink.json']['sha256']}
assert relink['passed']is True and relink['native']['sha256']==relink['artifact']['sha256']=='25661fd88779c009a84f7479b8fb9639aaeb9a37df3a11dc2d4adff2af94f7c2'
assert len(relink['objects'])==611 and relink['link_inputs']==plan['inputs']['link_inventory']
assert relink['link_inputs']['sha256']=='8d130a0c3c1d5aa9685ca8312f6381ebeb4c0778760f022c54a3253b1da760bc'
assert pipeline['status']=='failed_diagnostic' and pipeline['returncode']==1 and pipeline['final_cleanup']['verified']is True and pipeline['final_cleanup']['errors']==[]
assert capture['candidate_build_files']==[] and capture['fit_attempts']==0 and len(capture['owned_processes'])==7
assert all(r['absent']is True and r['live']is False for r in capture['owned_processes'])
probe_path=C/'native-complete-preflight02-installer-paths02.json';probe=json.loads(probe_path.read_bytes())
assert pin(probe_path)['sha256']=='541909fd43958a19903de6a3bf699fe7aa657db233530aebd759f8a0c2c4b76a'
assert probe['request']==plan['inputs']['installation_request']
assert (probe['repository_members_checked'],probe['delta_payloads_checked'],probe['archive_members_checked'],probe['expected_native_files'])==(79,7,1185,1134)
assert probe['native_commands']==0
python=[r for r in probe['inputs']if r['key']=='python'];assert len(python)==1;python=python[0]
assert python['declared']['sha256']==python['resolved_sha256']=='58f0ee5f4cb0af42a69aed9f122d63cc535fcfa6bca71132a3d0e24be95c4ac8'
assert python['resolved_path']==python['declared']['path']+'3.11' and python['declared_guard'].startswith("ValueError('Symlink path:")
assert all(r['declared_guard']=='passed'for r in probe['inputs']if r['key']!='python')
review={'schema':'orbit-poc-native-complete-preflight-control-failure-review-v1','passed':True,'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'capture':pin(p),'installer_path_probe':pin(probe_path),'failure':{'status':result['status'],'stage':'installer-equivalence','error':error,'candidate_compilations':0,'fit_attempts':0},'baseline_relink':{'receipt':result['baseline_relink'],'native_sha256':relink['native']['sha256'],'copied_objects':611,'link_inputs':637,'recorded_byte_identity':True,'independent_binary_rehash':False},'cleanup':{'controller_verified':True,'captured_owned_identities_absent':7,'captured_at':capture['observed_at'],'fresh_independent_proc_scan':False},'path_delta':{'python_declared':python['declared'],'python_resolved':{'path':python['resolved_path'],'sha256':python['resolved_sha256']},'same_interpreter_bytes':True,'helper_policy_unchanged':True},'auditor_invocation_history':{'prior_script':'audit_native_complete_preflight02_failure01.py','failure':'Assertion treated link_inputs pin dictionary as inventory list; no output written. Corrected to exact plan/inventory pin binding.'},'scope':'Exact retained failure attribution and interpreter path metadata only. The source-only installer and supplemental fixtures did not pass in this attempt; no scientific or release validation is claimed.'}
out=C/'native-complete-preflight02-independent-failure-review01.json'
with out.open('x')as f:json.dump(review,f,indent=2);f.write('\n')
print(json.dumps(pin(out)))
