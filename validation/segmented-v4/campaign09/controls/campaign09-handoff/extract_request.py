#!/usr/bin/env python3
"""Project immutable captured first-request records offline; execute no fit code."""
from pathlib import Path
import hashlib,json
C=Path('/mnt/d/orbit-segmented-v4/control');HERE=Path(__file__).resolve().parent
def pin(p):return {'path':str(p),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def checked(p,h):
 assert pin(p)['sha256']==h,str(p)
 return json.loads(p.read_bytes())
def save(name,v):
 p=HERE/name;data=(json.dumps(v,indent=2,sort_keys=True)+'\n').encode()
 if p.exists():assert p.read_bytes()==data,str(p)
 else:
  with p.open('xb') as f:f.write(data)
D=C/'campaign09-first-attempt01';K=C/'campaign09-first-attempt-config01'
m=checked(D/'manifest.json','20589f65d981f68ce00c722778bbe0f67f09d7a3a333b6a1180205d0d0be01a9')
k=checked(K/'manifest.json','1826768f2ab54b5eddea280503ee9ecd0d94f8d0204b621f03c2051d467b91dc')
for folder,manifest in [(D,m),(K,k)]:
 for row in manifest['files']:
  p=folder/row['relative_path'];a=pin(p)
  assert a['sha256']==row['sha256'] and a['bytes']==row['bytes'],str(p)
r=checked(D/'request.json','0fd71929a448587a00574216c3ebc79b9453de314beb989b9c8d4b32d333bbf1')
s=checked(D/'supervisor.plan.json','1eff35e3e66653ac42ab80c8c588b34d9ee8055d63627d8202b44d8959af2531')
c=checked(K/'segmented-v4.json','33cf305ada15863e2ee04e57390707344ed045a9fc712efc3f5e6e9247656378')
assert r['id']==m['attempt_id']=='leo500-quiet-normal-groops_pulses-24h--dense_corrected'
assert r['numerical_controls']==c['controls']
assert r['expected_native_binary_sha256']==c['dense_runtime']['native']['sha256']
assert r['backend']['groops_executable']==c['dense_runtime']['native']['path']
assert r['source_hash']==c['dense_runtime']['source_sha256']
assert r['segmented_manifest_hash']==m['frozen_manifest']['manifest_hash']
assert s['argv'][-1]=='[24]' and s['timeout_seconds']==r['numerical_controls']['wall_time_seconds']
save('compact-first-request.json',{
 'schema':'orbit-poc-campaign09-first-request-projection-v1',
 'scope':'Exact immutable capture projection, with full request input inventory and profile XML external. Equality to the frozen ordered job is established separately by the independent reconstruction audit. No fitting, propagation, scoring or remote access performed by this extractor.',
 'capture_manifest':pin(D/'manifest.json'),'config_capture_manifest':pin(K/'manifest.json'),
 'request':pin(D/'request.json'),'profile_xml':pin(D/'point-001-initial/profile.xml'),
 'supervisor_plan':pin(D/'supervisor.plan.json'),'config':pin(K/'segmented-v4.json'),
 'request_identity':{key:value for key,value in r.items() if not isinstance(value,(dict,list))},
 'case_scalar_fields':{key:value for key,value in r['case'].items() if not isinstance(value,(dict,list))},
 'backend':r['backend'],'numerical_controls':r['numerical_controls'],'parameters':r['parameters'],
 'estimation_input_records':len(r['estimation_inputs']),
 'resources':{key:c['resources'][key] for key in ['reserved_cpu_ids','threads','maximum_process_tree_rss_bytes','minimum_free_output_bytes','reserve_bytes']},
 'supervisor':{key:s[key] for key in ['schema','boot_id','cwd','working_directory','timeout_seconds','max_process_tree_rss_bytes','min_free_disk_bytes','helper_sha256']},
 'frozen_manifest':m['frozen_manifest']})
