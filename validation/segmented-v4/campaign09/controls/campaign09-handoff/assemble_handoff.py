#!/usr/bin/env python3
"""Assemble actual supplied handoff evidence offline; never execute campaign controls."""
from pathlib import Path
import argparse,hashlib,json
C=Path('/mnt/d/orbit-segmented-v4/control');D=Path(__file__).resolve().parent
def pin(p):return {'path':str(p),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def read(p):return json.loads(p.read_bytes())
def save(name,value):
 p=D/name;data=(json.dumps(value,indent=2,sort_keys=True)+'\n').encode()
 if p.exists():assert p.read_bytes()==data,str(p)
 else:
  with p.open('xb') as f:f.write(data)
def checked(p,h):
 assert pin(p)['sha256']==h,str(p)
 return read(p)
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--native-audit',type=Path,required=True)
parser.add_argument('--native-audit-sha256',required=True)
parser.add_argument('--evidence',nargs=2,action='append',default=[],metavar=('SOURCE','DESTINATION'))
a=parser.parse_args();native=checked(a.native_audit,a.native_audit_sha256)
assert native['status']=='verified_actual_first_native_handoff' and native['request_exact_match'] and native['supervisor_exact_match']
assert native['cutoff']=='2026-10-19T01:41:13.968477+00:00' and native['started_attempts']==1 and native['terminal_attempts']==0 and native['planned_attempts']==68
assert not native['release_ready'] and not native['covariance_authorized'] and not native['scientific_success_inferred']
copies=[];external=[];seen=set()
def ext(row,cited_by):
 r={k:row[k] for k in ['path','sha256','bytes','scope','captured_part'] if k in row}
 assert len(r['sha256'])==64
 p=Path(r['path']);r['cited_by']=cited_by;r['local_bytes_verified']=False
 if p.is_file():
  actual=pin(p);assert actual['sha256']==r['sha256'],str(p)
  if 'bytes' in r:assert actual['bytes']==r['bytes'],str(p)
  r['bytes']=actual['bytes'];r['local_bytes_verified']=True
 key=(r['path'],r['sha256'],cited_by,r.get('scope'),r.get('captured_part'))
 if key not in seen:external.append(r);seen.add(key)
def walk(v,cited_by):
 if isinstance(v,dict):
  if isinstance(v.get('path'),str) and isinstance(v.get('sha256'),str) and len(v['sha256'])==64 and Path(v['path']).is_absolute():ext(v,cited_by)
  for x in v.values():walk(x,cited_by)
 elif isinstance(v,list):
  for x in v:walk(x,cited_by)
def copy(src,dest,walk_json=True):
 src=Path(src);r=pin(src);r['source_path']=r.pop('path');r['path']=dest;copies.append(r)
 if src.suffix=='.json' and walk_json:walk(read(src),dest)
 return r
def evidence(name):return 'evidence/campaign09-handoff/'+name
for suffix,h in [('02','4520c2b960feecf9f773aba6e1fdef8ca9ed037f67bd9f663064516226ce2ff1'),('03','93d2d2b357faf664f8cf176eeecbfdec4407f3c7cf70406cc9f9baed102bb686'),('04','edd6db62a18d189a9dd4ce3aa393b1dbf8b4ec819b1bcae14e3d59d2988e806b'),('05','0300e2e13a7edd1fc6b0b1418d1c43391f790be904655ed3219cc59fef3f5803')]:
 folder=C/('campaign09-live'+suffix);assert pin(folder/'snapshot.json')['sha256']==h
 ext(pin(folder/'snapshot.json'),evidence('compact-live02-to05.json'))
 for name in ['request.json','process.json','stderr.log']:copy(folder/name,evidence('root-live'+suffix+'/'+name))
T=C/'campaign09-transition-01'
tm=checked(T/'manifest.json','7b268efb0173aa6ff518e7974dbc7a8d68694f5fddae439482e52caf4ee59a01')
copy(T/'manifest.json',evidence('transition/capture-manifest.json'),False)
for row in tm['files']:
 local=T/row['relative_path'];actual=pin(local);assert actual['sha256']==row['sha256'] and actual['bytes']==row['bytes']
 remote=dict(row)
 if 'scope' in row:remote['captured_part']=row['relative_path']
 ext(remote,evidence('transition/capture-manifest.json'));ext(actual,evidence('transition/capture-manifest.json'))
 if row['relative_path'] not in ['prelaunch-probe.json','prefix-before.json']:copy(local,evidence('transition/'+row['relative_path']))
for name in ['capture-command.py','stderr.log']:copy(T/name,evidence('transition/'+name))
for folder,expected,part in [(C/'campaign09-first-attempt01','20589f65d981f68ce00c722778bbe0f67f09d7a3a333b6a1180205d0d0be01a9','first-attempt'),(C/'campaign09-first-attempt-config01','1826768f2ab54b5eddea280503ee9ecd0d94f8d0204b621f03c2051d467b91dc','config')]:
 manifest=checked(folder/'manifest.json',expected)
 copy(folder/'manifest.json',evidence(part+'/capture-manifest.json'))
 for row in manifest['files']:
  local=folder/row['relative_path'];actual=pin(local);assert actual['sha256']==row['sha256'] and actual['bytes']==row['bytes']
  ext(actual,evidence(part+'/capture-manifest.json'))
  if row['relative_path']=='supervisor.plan.json':copy(local,evidence(part+'/supervisor.plan.json'))
 for name in ['capture-command.py','stderr.log']:copy(folder/name,evidence(part+'/'+name))
copy(C/'campaign09-inner-proof-independent-review01.json',evidence('inner-proof-independent-review01.json'))
assert pin(C/'campaign09-inner-proof-independent-review01.json')['sha256']=='745d577ba5454e4713a6670617b17d54b33a522b1d03342c17fcfbffce799766'
copy(a.native_audit,evidence('native-independent-review01.json'))
for name in ['capture_campaign09_transition01.py','capture_campaign09_first_attempt01.py']:copy(C/name,'controls/campaign09-handoff/'+name)
for p in sorted((C/'campaign-live-snapshot-draft03').iterdir()):
 assert p.is_file();copy(p,'controls/campaign-live-snapshot-draft03/'+p.name)
for src,dest in [('campaign-live-snapshot03-independent-review01.json','capture-independent-review01.json'),('campaign-live03-independent01.xml','capture-independent-tests.xml'),('campaign-live03-independent01.log','capture-independent-tests.log')]:copy(C/src,evidence(dest))
for src,dest in a.evidence:copy(Path(src),dest)
for name in ['extract_handoff.py','extract_request.py','assemble_handoff.py']:copy(D/name,'controls/campaign09-handoff/'+name)
for name in ['compact-live02-to05.json','compact-inner-proof.json','compact-first-request.json']:copy(D/name,evidence(name))
events=[
 {'title':'First native fit running at the 01:41:13 UTC cutoff',
  'detail':'The 19 October 2026 snapshot at 01:41:13.968477 UTC observes exactly the first ordered attempt, leo500-quiet-normal-groops_pulses-24h--dense_corrected, with a native GROOPS process and no terminal outcomes. PID 20782, start ticks 135757891, executes point-001-initial/profile.xml through the frozen dense runtime on CPU 24; all four numerical thread settings are one and HOME is private. The global, controller and segmented locks have the recorded owned holders, and the latest captured observer sample is clear. This establishes one of 68 attempts started at that dated observation, with zero completed; it establishes no fit convergence or accepted covariance.',
  'evidence':[{'path':evidence('native-independent-review01.json'),'label':'Independent first-native and request audit'},{'path':evidence('compact-live02-to05.json'),'label':'Dated startup, proof and native process projections'},{'path':evidence('root-live05/process.json'),'label':'Read-only live05 capture receipt'}]},
 {'title':'Frozen first request and native identity tied to the observed handoff',
  'detail':'The bounded first-attempt capture preserves the immutable request, supervisor plan and initial profile XML. Independent reconstruction establishes exact equality of every request and supervisor field with the frozen ordered job and config. The compact projection retains source, manifest, input, objective/model and numerical-control identities; the complete request and profile remain external. The XML was captured after the observation cutoff: key pulse, float-ambiguity and cadence conventions were inspected, without rerunning full XML generation. Native executable attribution uses observed path, device 2048, inode 217255543 and size 24,071,920 bytes with the previously checked frozen digest. No executable rehash during the timed fit is claimed. The driver and observer remain assigned to CPU 32; performance observations are shared-host timing.',
  'evidence':[{'path':evidence('compact-first-request.json'),'label':'Reproducible request and settings projection'},{'path':evidence('first-attempt/capture-manifest.json'),'label':'Exact immutable request/profile capture pins'},{'path':evidence('config/capture-manifest.json'),'label':'Frozen config capture pin'},{'path':evidence('native-reconstruction02.json'),'label':'Exact independent reconstruction result'},{'path':'controls/campaign09-handoff/audit_campaign09_first_native02.py','label':'Independent reconstruction source'},{'path':evidence('native-independent-review01.json'),'label':'Independent frozen-job reconstruction and identity review'}]},
 {'title':'Actual campaign inner proof passed before native handoff',
  'detail':'The actual campaign proof is separate from the earlier successful no-fit smoke. Its full public manifest, validation and prefix checks pass; all 1,800 denial opens fail as required, no inherited descriptors remain, and the mount policy retains 3,320 protected read-only targets and the original three writable targets. The exact namespace and private-device bootstrap headers, durable launch and empty 68-attempt prefix are preserved. The independent inner-proof audit refers to the earlier live04 observation with zero native processes; the later live05 observation and native audit establish the handoff. Earlier controller-start and wrapper-running labels are historical stages, not earlier fit starts.',
  'evidence':[{'path':evidence('inner-proof-independent-review01.json'),'label':'Actual inner-proof independent audit'},{'path':evidence('compact-inner-proof.json'),'label':'Reproducible full-proof projection'},{'path':evidence('transition/capture-manifest.json'),'label':'Exact proof, prefix and bounded-header capture pins'},{'path':evidence('transition/workload-header-1.json'),'label':'Actual namespace transport receipt'},{'path':evidence('transition/workload-header-2.json'),'label':'Actual private-device bootstrap receipt'}]},
 {'title':'Reviewer command-digest correction retained',
  'detail':'The first offline native audit used canonical JSON for the observed argv digest. Its version02 uses the accepted snapshot helper\u2019s NUL-separated argv bytes with a trailing NUL and passes. The prior reviewer script remains externally pinned. This assertion correction changed no production control, captured input or scientific setting and is not a fit outcome.',
  'evidence':[{'path':evidence('native-independent-review01.json'),'label':'Preserved reviewer correction and prior-script pin'},{'path':evidence('native-reconstruction02.json'),'label':'Passing version02 reconstruction'}]}]
value={'schema':'orbit-poc-campaign09-publication-event-ingredients-v1',
 'scope':'Actual audited first-native handoff at the fixed live05 cutoff, with historical live02–04 stages retained. No remote calls or scientific execution by publication assembly.',
 'copied_files':copies,'external_artifacts':external,'events':events}
save('event-ingredients.json',value)
save('verification.json',{'schema':'orbit-poc-campaign09-handoff-ingredients-verification-v1','native_audit':pin(a.native_audit),'event':pin(D/'event-ingredients.json'),'copied_files':len(copies),'copied_bytes':sum(r['bytes'] for r in copies),'external_pin_records':len(external),'locally_verified_external_pin_records':sum(r['local_bytes_verified'] for r in external),'remote_calls':False,'campaign_controls_executed':False,'report_materialized':False})
save('manifest.json',{'schema':'orbit-poc-campaign09-offline-handoff-ingredient-set-v1','files':[{**pin(p),'path':p.name} for p in sorted(D.iterdir()) if p.name!='manifest.json']})
print(json.dumps({'event':pin(D/'event-ingredients.json'),'manifest':pin(D/'manifest.json'),'verification':pin(D/'verification.json')},indent=2))
