#!/usr/bin/env python3
"""Collect pinned compact controls only; final status awaits actual launch audit."""
from pathlib import Path
import base64,datetime,hashlib,json,subprocess
R=Path('/mnt/d/orbit-segmented-v4');C=R/'control';O=R/'publication-validation04-launch-01'
def digest(b):return hashlib.sha256(b).hexdigest()
def pin(p):
 b=Path(p).read_bytes();return {'path':str(p),'sha256':digest(b),'bytes':len(b)}
def read(p):return json.loads(Path(p).read_text())
def put(rel,b):
 p=O/rel;p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('xb')as f:f.write(b)
def copy(rel,p,expected=None):
 b=Path(p).read_bytes()
 if expected:assert digest(b)==expected,p
 put(rel,b);return {'relative':rel,'source':pin(p)}
assert not O.exists();O.mkdir()
local=['validation04-staging.json','validation04-packet-assembly.json','validation04-base-config.json','validation04-packet-independent-review01/review.json','validation04-packet-independent-review01/readback02.json','validation04-packet-independent-review01/readback.json','validation04-packet-independent-review01/stderr.log','validation04-packet-independent-review01/stderr02.log','validation04-controls-independent-code-review01.json','assemble_validation04_packet.py','stage_segmented_validation04.py','audit_validation04_packet01.py','audit_validation04_packet02.py','test_assemble_validation04_packet.py','validation04-assembler-author-tests.log','validation04-assembler-author-tests.xml','validation04-assembler-independent-tests.log','validation04-assembler-independent-tests.xml','validation04-startup-addendum01.json','validation04-startup-addendum-independent-review01.json','validation04-startup-addendum-independent-readback01.json','validation04-startup-addendum-independent-readback01.stderr.log','validation04-startup-addendum-independent-readback03.json','validation04-startup-addendum-independent-readback03.stderr.log','audit_validation04_startup_addendum01.py','audit_validation04_startup_addendum02.py','audit_validation04_startup_addendum03.py','validation04_startup_probe.py','smoke_segmented_validation04.py','smoke_segmented_validation04_02.py','test_validation04_startup_probe.py','validation04-startup-author-tests.log','validation04-startup-author-tests.xml','validation04-startup-independent-tests01.log','validation04-startup-independent-tests01.xml','preparation-profile-fix01/author-validation02.json','preparation-profile-fix01/independent-review02.json','preparation-profile-fix01/independent-review02-scope-clarification.json','preparation-profile-fix01/candidate-files02.json','preparation-profile-fix01/candidate02.patch','preparation-profile-fix01/focused-tests01.log','preparation-profile-fix01/focused-tests01.xml','preparation-profile-fix01/focused-tests02.log','preparation-profile-fix01/focused-tests02.xml']
sources=[copy('provenance/'+n,C/n)for n in local]
base=read(C/'validation04-packet-independent-review01/review.json');add=read(C/'validation04-startup-addendum01.json')
assert base['passed'] and base['native_input_count']==70 and base['runtime_pin_count']==371
remote=[]
for key in ('source_freeze','execution','config','launch_plan','launch_pins','native_equivalence','staging'):
 p=base[key];remote.append({'relative':'controls/'+Path(p['path']).name,**p})
for name,p in add['helpers'].items():remote.append({'relative':'controls/'+name,**p})
remote.append({'relative':'controls/preserved-validation03-startup-probe.py',**add['preserved_probe']})
code="""import pathlib,json,base64,hashlib\nitems=json.loads(base64.b64decode(%r));out=[]\nfor e in items:\n p=pathlib.Path(e['path']);b=p.read_bytes();assert len(b)<2000000 and not p.is_symlink() and hashlib.sha256(b).hexdigest()==e['sha256'],str(p)\n out.append(dict(e,bytes=len(b),base64=base64.b64encode(b).decode()))\nprint(json.dumps(out))\n"""%base64.b64encode(json.dumps(remote).encode()).decode()
r=subprocess.run(['/mnt/c/Windows/System32/OpenSSH/ssh.exe','-o','BatchMode=yes','gpuserver4090','python3 -'],input=code,text=True,capture_output=True,timeout=45);assert r.returncode==0,r.stderr
for item in json.loads(r.stdout):
 b=base64.b64decode(item.pop('base64'));assert digest(b)==item['sha256'];relative=item.pop('relative');put(relative,b);sources.append({'relative':relative,'source':item})
ledger={'schema':'orbit-poc-validation04-launch-package-staging-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'root':str(O),'stage':'static_controls_copied; awaiting_actual_startup_and_full_launch_evidence','files':sources,'source_helper':pin(__file__),'native_results_claimed':False}
p=C/'validation04-launch-publication-staging01.json'
with p.open('x')as f:json.dump(ledger,f,indent=2);f.write('\n')
print(json.dumps({'root':str(O),'files':len(sources),'ledger':pin(p)}))
