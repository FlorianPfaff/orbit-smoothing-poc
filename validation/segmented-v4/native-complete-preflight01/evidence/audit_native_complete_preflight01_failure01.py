from pathlib import Path
import base64,datetime,hashlib,json
C=Path('/mnt/d/orbit-segmented-v4/control')
def pin(p):p=Path(p);return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
p=C/'native-complete-preflight01-terminal-capture01.json';capture=json.loads(p.read_text());raw={};rows={}
assert pin(p)['sha256']=='a8f79fb416fe032e16bf67c14508fca4e1d167e152c72c6f4d34d74585c94154'
for row in capture['files']:
 data=base64.b64decode(row['base64'],validate=True);assert len(data)==row['bytes'] and hashlib.sha256(data).hexdigest()==row['sha256'] and row['path']not in raw
 raw[row['path']]=data;rows[row['path']]=row
assert len(raw)==19
root=capture['root'];plan=json.loads(raw[root+'/control/plan.json']);pipeline=json.loads(raw[root+'/control/pipeline.json']);result=json.loads(raw[root+'/run/preflight/result.json']);launch=json.loads(raw[root+'/control/native-complete-launch.json'])
assert rows[root+'/control/plan.json']['sha256']=='d1537fb72b6e796ff0be1360d8382b2a5f77586cd303914a9fee310b418f0a19'
assert result['status']=='failed' and result['stages']==[] and result['error']=="ValueError('Changed, incomplete or duplicated link dependency identity')"
assert pipeline['status']=='failed_diagnostic' and pipeline['returncode']==1 and pipeline['final_cleanup']['verified'] is True and pipeline['final_cleanup']['errors']==[]
assert capture['candidate_build_files']==[] and capture['fit_attempts']==0 and len(capture['owned_processes'])==4
assert all(r['absent']is True and r['live']is False for r in capture['owned_processes'])
probe_path=C/'native-complete-preflight01-namespace-identities02.json';probe=json.loads(probe_path.read_text())
assert pin(probe_path)['sha256']=='d2f31197a53e1787931c41581e1b2548f114c7e393bbfaa23b5d24735a9c4ca1'
assert probe['count']==637 and len(probe['actual_links'])==637 and len(probe['different'])==6 and probe['dependency_differences']==[] and len(probe['actual_dependencies'])==420
for row in probe['different']:
 assert row['fields']==['resolved_path']
 assert {k:v for k,v in row['declared'].items()if k!='resolved_path'}=={k:v for k,v in row['actual'].items()if k!='resolved_path'}
readback_path=C/'native-complete-preflight02-root-readback01.json';readback=json.loads(readback_path.read_text());decoded={}
for name,row in readback.items():
 data=row['text'].encode();assert hashlib.sha256(data).hexdigest()==row['sha256'];decoded[name]=json.loads(data)
newroot=root[:-2]+'02';newplan=decoded[newroot+'/control/plan.json'];newlinks=decoded[newplan['inputs']['link_inventory']['path']]
assert newlinks['inputs']==probe['actual_links'] and newlinks['baseline_result']==plan['inputs']['baseline_result']
for key in plan['inputs']:
 if key not in ('link_inventory','installation_request'):assert newplan['inputs'][key]==plan['inputs'][key]
for key in ('worker','controller','driver'):assert newplan[key]['sha256']==plan[key]['sha256']
assert newplan['phase']==plan['phase']=='prepare' and newplan['native']==plan['native'] and newplan['global_lock']==plan['global_lock']
review={'schema':'orbit-poc-native-complete-preflight-control-failure-review-v1','passed':True,'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'capture':pin(p),'namespace_identity_probe':pin(probe_path),'new_packet_readback':pin(readback_path),'failure':{'status':result['status'],'error':result['error'],'stages':0,'candidate_compilations':0,'fit_attempts':0},'cleanup':{'controller_verified':True,'captured_owned_identities_absent':4,'captured_at':capture['observed_at'],'fresh_independent_proc_scan':False},'namespace_delta':{'link_inputs':637,'changed_resolved_path_only':6,'unchanged_payload_device_inode_size_linktext':True,'compile_dependencies':420,'dependency_changes':0},'scope':'Failure attribution and exact namespace metadata correction only; no source/native/scientific gate passed and no current process-state claim beyond the pinned observation.'}
out=C/'native-complete-preflight01-independent-failure-review01.json'
with out.open('x')as f:json.dump(review,f,indent=2);f.write('\n')
print(json.dumps(pin(out)))
