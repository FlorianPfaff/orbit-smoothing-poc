from pathlib import Path
import json,hashlib
C=Path('/mnt/d/orbit-segmented-v4/control')
def pin(p):
 b=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
def read(p):return json.loads(p.read_bytes())
def walk(v):
 if isinstance(v,dict):
  if isinstance(v.get('path'),str)and isinstance(v.get('sha256'),str):yield v
  for x in v.values():yield from walk(x)
 elif isinstance(v,list):
  for x in v:yield from walk(x)
names=['nominal-complete-native-controls-author-review01.json','nominal-complete-native-controls-author-review02.json','nominal-complete-native-controls-author-tests02.json','nominal-complete-native-independent-code-review02.json','nominal-complete-native-root-code-review02.json','nominal-complete-native-independent-finding01.json','nominal-complete-native-author-tests01.log','nominal-complete-native-author-tests02.log','nominal-complete-native-author-tests03.log','nominal-complete-native-author-tests04.log','nominal-complete-native-independent-tests01.log','nominal-complete-native-independent-tests02.log','nominal-complete-four-independent-packet-review01.json','nominal-complete-supplemental01-independent-packet-review01.json','native-complete-build02-independent-terminal-review01.json','nominal-complete-single01-live01.json','nominal-complete-single01-live01.stderr','nominal-complete-single01-live02.json','nominal-complete-single01-live02.stderr','read_nominal_complete_live01.py','read_nominal_complete_live02.py','audit_nominal_complete_native_terminal01.py','audit_nominal_complete_native_terminal02.py','audit_nominal_complete_supplemental01_remote.py','capture_nominal_complete_checks01.py','capture_nominal_complete_checks02.py','read_nominal_complete_supplemental01_packet.py','nominal-complete-supplemental01-independent-readback01.json','nominal-complete-supplemental01-independent-readback01.stderr','nominal-complete-supplemental01-independent-readback02.json','nominal-complete-supplemental01-independent-readback02.stderr','read_nominal_complete_four01_packet.py','prepare_native_complete_four_publication_spec01.py']
files={C/n for n in names};audits={}
for k in ['single01','single02','closure01','closure02','supplemental']:
 stem='nominal-complete-'+(k if k!='supplemental'else'supplemental01');p=C/(stem+'-independent-terminal-review01.json');a=read(p);assert a['passed'];audits[k]=pin(p);files.add(p)
 for field in ['raw_capture','actual_readback','audit_helper']:
  if field in a:
   r=a[field];q=Path(r['path']);assert q.is_relative_to(C)and pin(q)['sha256']==r['sha256'];files.add(q)
 stderr=C/(stem+'-independent-actual01.stderr')
 if stderr.exists():files.add(stderr)
 # Exact sealed raw captures are the only sources of original remote bytes.
 assert Path(a['raw_capture']['path'])in files
for name in ['nominal-complete-native-controls-author-review01.json','nominal-complete-native-controls-author-review02.json','nominal-complete-native-controls-author-tests02.json','nominal-complete-native-independent-code-review02.json','nominal-complete-four-independent-packet-review01.json','nominal-complete-supplemental01-independent-packet-review01.json']:
 for r in walk(read(C/name)):
  q=Path(r['path'])
  if q.is_relative_to(C)and q.is_file()and q.suffix not in {'.tar','.gz'}:
   assert pin(q)['sha256']==r['sha256'],str(q);files.add(q)
for p in files:
 assert p.is_file()and not p.is_symlink(),str(p)
 b=p.read_bytes();assert b'\0'not in b;b.decode('utf-8')
history=[
 {'kind':'preexecution_control_review_finding','finding':pin(C/'nominal-complete-native-independent-finding01.json'),'correction':pin(C/'nominal-complete-native-independent-code-review02.json'),'scope':'The earlier unexecuted closure control recorded initial-state drift without rejecting it. Final controls reject any drift before acceptance;77 independent pure tests passed. No actual native outcome was reclassified.'},
 {'kind':'read_only_supplemental_packet_inspection_failure','stderr':pin(C/'nominal-complete-supplemental01-independent-readback01.stderr'),'empty_output':pin(C/'nominal-complete-supplemental01-independent-readback01.json'),'corrected_readback':pin(C/'nominal-complete-supplemental01-independent-readback02.json'),'scope':'Read-only inspector reported reserved CPUs outside its current affinity. Preserve the exact failure separately from actual accepted supplemental execution; no numerical rerun is attributed to this inspection correction.'},
 {'kind':'read_only_live_inspector_receipt_name_failure','stderr':pin(C/'nominal-complete-single01-live01.stderr'),'empty_output':pin(C/'nominal-complete-single01-live01.json'),'corrected_readback':pin(C/'nominal-complete-single01-live02.json'),'scope':'The inspector expected native-check-launch.json instead of actual native-single-launch.json. Correction affected observation only; the original native execution was not repeated.'},
 {'kind':'unexecuted_terminal_auditor_assumption','preserved_source':pin(C/'audit_nominal_complete_native_terminal01.py'),'actual_source':pin(C/'audit_nominal_complete_native_terminal02.py'),'scope':'Earlier auditor source assumed a receipt name. The preserved file is not represented as an executed failure; actual02 is bound by each terminal audit.'}]
s={'schema':'orbit-poc-complete-native-four-check-publication-spec-v1','files':[pin(p)for p in sorted(files)],'audits':audits,'history':history,'scope':'Exact existing audited records only; native arrays remain external. No numerical run, full-suite or benchmark result generated by publication.'}
p=C/'native-complete-four-checks-publication-spec01.json'
with p.open('x')as f:json.dump(s,f,indent=2);f.write('\n')
print(json.dumps({'spec':pin(p),'files':len(files),'bytes':sum(x['bytes']for x in s['files'])},indent=2))
