"""Independent offline publication audit; no host queries or campaign imports."""
from pathlib import Path
from html.parser import HTMLParser
import ast,hashlib,json
from datetime import datetime,timezone
C=Path('/mnt/d/orbit-segmented-v4/control');R=Path('/mnt/d/orbit-segmented-v4/source/validation/segmented-v4/campaign09')
def sha(b):return hashlib.sha256(b).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p.read_bytes())}
def read(p):return json.loads(p.read_bytes())
def need(ok,msg):
 if not ok:raise ValueError(msg)
man=R/'publication-manifest.json';expected='bdfd4b11837398bea057d7d41a650da69182cf8a7d8792135685b9a3238fa287'
need(sha(man.read_bytes())==expected,'Publication manifest changed')
rows=read(man)['files'];names={x['path'] for x in rows}
need(len(names)==len(rows)==369,'Count or duplicate names')
need({p.relative_to(R).as_posix() for p in R.rglob('*') if p.is_file()}==names|{'publication-manifest.json'},'Closed inventory mismatch')
for row in rows:
 p=R/row['path'];need(not p.is_symlink() and R in p.resolve().parents and '..' not in Path(row['path']).parts and not Path(row['path']).is_absolute(),'Unsafe path')
 b=p.read_bytes();need(len(b)==row['bytes'] and sha(b)==row['sha256'],'Publication bytes changed: '+row['path'])
 if p.suffix=='.json':json.loads(b)
 if p.suffix=='.py':ast.parse(b,filename=str(p))
prov=read(R/'provenance.json')['copied_files'];need(len(prov)==364,'Copy count')
for row in prov:
 p=R/row['path'];b=p.read_bytes();src=Path(row['source_path']).read_bytes();need(b==src and len(b)==row['bytes'] and sha(b)==row['sha256'],'Exact source copy mismatch '+row['path'])
class Links(HTMLParser):
 def __init__(self):super().__init__();self.values=[];self.text=[]
 def handle_starttag(self,tag,attrs):self.values.extend(v for k,v in attrs if k in ('href','src'))
 def handle_data(self,data):self.text.append(data)
l=Links();l.feed((R/'index.html').read_text());local_links=[]
for target in l.values:
 if '://' not in target:
  p=(R/target.split('#')[0]).resolve();need(p.is_file(),'Broken HTML link '+target);local_links.append(target)
s=read(R/'summary.json');review=read(C/'campaign09-first-native-independent-review01.json');snapshot=read(C/'campaign09-live05/snapshot.json')
need(s['evidence_cutoff']==review['cutoff']==snapshot['captured_at']=='2026-10-19T01:41:13.968477+00:00','Cutoff')
need((s['fit_attempts_started'],s['fit_attempts_completed'],s['planned_fit_attempts'],s['release_ready'])==(1,0,68,False),'Scope counts')
need(s['status']=='first_native_fit_running' and review['status']=='verified_actual_first_native_handoff','Status')
key_copies={
'evidence/campaign09-handoff/native-independent-review01.json':'campaign09-first-native-independent-review01.json',
'evidence/campaign09-handoff/native-reconstruction02.json':'campaign09-first-native-reconstruction02.json',
'evidence/campaign09-handoff/inner-proof-independent-review01.json':'campaign09-inner-proof-independent-review01.json',
'evidence/seal06-terminal/independent-review01.json':'normalization-seal-terminal-independent-review01.json',
'evidence/smoke03/terminal-independent-review03.json':'normalization-smoke-terminal-independent-review03.json',
}
for rp,cp in key_copies.items():need((R/rp).read_bytes()==(C/cp).read_bytes(),'Key review identity')
projection=read(R/'evidence/campaign09-handoff/compact-live02-to05.json');last=projection['snapshots'][-1]
need(last['source_snapshot']['sha256']==sha((C/'campaign09-live05/snapshot.json').read_bytes()),'Snapshot projection source')
need(last['native_processes']==snapshot['native_processes'] and last['fit_attempts_started']==1 and last['fit_attempts_completed']==0,'Native projection')
need(last['active_attempts'][0]['request']=={k:v for k,v in snapshot['attempts'][0]['request'].items() if k!='content'},'Request projection')
need(last['observer_latest']['recorded_state']=={k:snapshot['observer_latest']['content'][k] for k in last['observer_latest']['recorded_state']},'Observer projection')
for p in projection['snapshots']:
 raw=read(Path(p['source_snapshot']['path']));need(p['captured_at']==raw['captured_at'] and p['native_processes']==raw['native_processes'] and p['fit_attempts_completed']==raw['terminal_count'],'Historical projection mismatch')
proof=read(R/'evidence/campaign09-handoff/compact-inner-proof.json');rawproof=read(C/'campaign09-transition-01/prelaunch-probe.json')
need(proof['source_proof']['sha256']==sha((C/'campaign09-transition-01/prelaunch-probe.json').read_bytes()),'Proof source')
need(proof['status']==rawproof['status']=='passed' and proof['denial_probe_count']==len(rawproof['denial_probes'])==1800 and proof['descriptors']==[],'Proof projection')
need(proof['public_readonly_checks']['manifest_hash']==rawproof['public_readonly_checks']['manifest_hash'],'Proof manifest')
text=' '.join(l.text);need('Started in cited evidence: 1. Completed: 0. Release ready: false.' in text,'Rendered status differs')
need('XML was captured after the observation cutoff' in text and 'No executable rehash during the timed fit is claimed' in text,'Required attribution limitations missing')
need('full-arc' in text.lower() and 'release readiness remain unestablished' in text,'Release limitation missing')
titles={e['title'] for e in s['events']}
need({'Preserved first actual alias smoke failure','Second actual probe: bootstrap passed; required GPS bias product absent','Reviewer command-digest correction retained'}<=titles,'Prior failures not retained')
need('../campaign08/index.html' in local_links and (R/'../campaign07/index.html').is_file(),'Prior campaign reports absent')
external=read(R/'external-evidence.json')['artifacts'];need(len(external)==858,'External pin count')
for e in external:
 need(isinstance(e['path'],str) and len(e['sha256'])==64 and all(c in '0123456789abcdef' for c in e['sha256']),'Invalid external pin')
need(sha(man.read_bytes())==expected,'Publication changed during review')
result={'schema':'orbit-poc-campaign09-publication-independent-review-v1','status':'accepted_dated_handoff_publication','created_at':datetime.now(timezone.utc).isoformat(),'script':pin(Path(__file__)),'publication_manifest':pin(man),'summary':pin(R/'summary.json'),'html':pin(R/'index.html'),'files_including_manifest':len(rows)+1,'bytes_including_manifest':sum(x['bytes'] for x in rows)+man.stat().st_size,'exact_source_copies_verified':len(prov),'html_local_links_checked':len(local_links),'external_pin_records':len(external),'external_large_artifacts_rehashed':False,'cutoff':s['evidence_cutoff'],'started_attempts':1,'terminal_attempts':0,'planned_attempts':68,'release_ready':False,'first_native_review':pin(C/'campaign09-first-native-independent-review01.json'),'checks':['Exact closed inventory, every file digest/size, all copied original bytes, JSON and Python syntax verified offline.','Every local HTML link exists; first-native, actual inner-proof, fresh-seal and smoke acceptance copies match exact independently reviewed bytes.','Dated live process and proof projections checked against raw captured snapshots. Snapshot 1/0/68 scope agrees with rendered HTML and machine-readable summary.','Campaign07/08 reports and both failed smoke outcomes remain available; historical zero-fit stages are distinguished from the actual first native handoff.','Post-cutoff profile capture, reviewer argv-digest correction, no running-binary rehash, shared-host timing and outstanding scientific/release gates remain disclosed.'],'limitations':['This audit verifies publication integrity and attribution. It adds no scientific validation or completed fit.','External large artifacts are retained as attributed pins; they were not redundantly rehashed here. No host command or campaign control was run.']}
out=C/'campaign09-publication-independent-review01.json'
with out.open('x') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
with (C/'campaign09-publication-reviewed-manifest01.json').open('xb') as f:f.write(man.read_bytes())
print(json.dumps({'review':pin(out),'script':pin(Path(__file__)),'counts':[len(rows)+1,len(prov),len(local_links)],'manifest':expected}))
