from pathlib import Path
import argparse,hashlib,json,re,datetime
ap=argparse.ArgumentParser();ap.add_argument('--candidate',required=True);ap.add_argument('--sha256',required=True);ap.add_argument('--output',required=True);args=ap.parse_args()
P=Path(args.candidate);C=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return dict(path=str(p),sha256=sha(p),bytes=Path(p).stat().st_size)
def read(p):return json.loads(Path(p).read_text())
mp=P/'manifest.json';assert sha(mp)==args.sha256;m=read(mp);entries=m['entries'];assert len(entries)==m['files']
assert {str(p.relative_to(P)) for p in P.rglob('*') if p.is_file()}=={x['relative'] for x in entries}|{'manifest.json'}
assert not any(p.is_symlink() for p in P.rglob('*'))
for x in entries:
 p=Path(x['relative']);assert not p.is_absolute() and '..' not in p.parts
 q=P/p;assert sha(q)==x['sha256'] and q.stat().st_size==x['bytes'];q.read_text()
 assert p.suffix not in {'.npz','.npy','.rows','.bin','.dat'}
assert sum(x['bytes'] for x in entries)==m['bytes']
s=read(P/'status.json');assert not s['release_ready'] and not s['corrected_fit_covariance_authorized'] and not m['release_ready']
source_map={x['source']['path']:x['relative'] for x in s['sources']};assert len(source_map)==len(s['sources'])
for row in s['sources']:
 source=row['source'];p=Path(source['path']);q=P/row['relative'];assert sha(p)==source['sha256'] and p.stat().st_size==source['bytes'] and q.read_bytes()==p.read_bytes()
a=read(P/'provenance/original150-tenth-terminal-independent-review01.json');assert sha(P/'provenance/original150-tenth-terminal-independent-review01.json')=='2038256650e3fbde12c40ce342e02b59c61274e89d71a0a8abea3778bbb9df71'
l=read(P/'provenance/preparation03-live-launch-independent-review02.json');assert sha(P/'provenance/preparation03-live-launch-independent-review02.json')=='5ae98e6c2cc8562d1ee2e1df0905e4a21ea8c2480c31ebaf1ecea12ab835ea1f'
u=read(P/'provenance/preparation03-actual-startup-independent-review01.json');assert sha(P/'provenance/preparation03-actual-startup-independent-review01.json')=='ed8a31086802ef87667b590d64a42ec666934cdaed5a0dcb3bab0cdf642203ed'
v=s['v4'];assert v['started_fits']==v['terminal_fits']==0 and v['planned_fits']==68 and v['preparation_observed_at']==l['observed_at']
assert not v['fit_time_truth_isolation_claimed'] and not v['complete_prepared_manifest_claimed']
assert v['startup_elapsed_seconds']==u['elapsed_seconds'] and v['startup_owned_identities_absent']==u['owned_processes_checked']==5
assert v['canonical_launch']==l['launch'] and v['driver']=={'pid':l['live_driver']['pid'],'start_ticks':l['live_driver']['start_ticks'],'boot_id':'95156dd4-0d4c-499d-a214-8883a2d650fa'}
o=s['original150'];assert o['terminal_attempts']==a['terminal_attempts']==10 and o['terminal_distribution']==a['status_counts'] and o['planned_attempts']==150
assert not o['campaign_complete'] and not o['corrected_executable_substituted']
assert o['eleventh']['request']==a['eleventh_request'] and o['eleventh']['observed_at']==a['observed_at'] and o['eleventh']['worker_and_native_processes']==a['live_eleventh_descendants']
assert o['tenth_legacy_validation']==a['tenth']['state_array_validation'] and o['tenth_convergence_scope']==a['tenth']['convergence_scope']
results={}
for row in o['new_terminal_records']:
 ar=a['terminal_prefix'][row['order']-1];assert row['attempt_id']==ar['attempt_id'] and row['status']==ar['status'] and row['profile']==ar['profile'] and row['result']==ar['result'] and row['index']==ar['index']
 d=P/'original150'/row['attempt_id'];r=read(d/'result.json');i=read(d/'result-record.json');assert r['status']==i['status']==row['status'] and i['request_hash']==r['request_hash']
 assert row['harness_elapsed_seconds']==r['harness_execution']['elapsed_seconds'] and row['peak_process_tree_rss_bytes']==r['harness_execution']['peak_process_tree_rss_bytes']
 results[row['order']]=r
ext=read(P/'external-evidence.json');assert len(ext['entries'])==sum(len(x['artifacts']) for x in results.values())==23
copied=[];external=[]
for order in [9,10]:
 rows=[x for x in ext['entries'] if x['attempt_order']==order];assert [x['artifact'] for x in rows]==results[order]['artifacts']
 for x in rows:
  path=x['artifact']['path']
  if path in source_map:
   copied.append(x);assert x['disposition']!='external_not_read_or_copied_by_this_publication';assert sha(P/source_map[path])==x['artifact']['sha256']
  else:
   external.append(x);assert x['disposition']=='external_not_read_or_copied_by_this_publication'
assert len(copied)==1 and copied[0]['artifact']['role']=='legacy_terminal_preservation' and len(external)==22
assert sum(x['attempt_order']==10 for x in external)==18
assert (P/'provenance/preparation03-live-launch-independent-readback01.json').stat().st_size==0
html=(P/'index.html').read_text()
for t in ['0/68','10/150','original legacy','06:25:57','No later state is inferred','18 of the 19','remaining legacy artifact is the compact preservation receipt']:
 assert t in html,t
for link in re.findall(r'href="([^"]+)"',html):
 if link in ['../validation04/index.html','../shifted02/index.html','../status-preparation-original150-03/index.html']:continue
 assert (P/link).is_file(),link
correction=read(P/'publication-correction.json');assert correction['numerical_changes'] is False and correction['new_remote_observation'] is False and correction['scientific_payload_rescan'] is False
for key in ('independent_finding','preserved_candidate_manifest'):
 x=correction[key];assert sha(x['path'])==x['sha256'] and Path(x['path']).stat().st_size==x['bytes']
assert correction['independent_finding']['sha256']=='08eab1c39a74c3640f53367453e65db8139eea72ed5fed12fbefdf58cc72a915'
assert correction['preserved_candidate_manifest']['sha256']=='8130385bbac2dd792c420699c25f74bfc809013ab5a34601ae7fccbe3708c022'
assert sha(mp)==args.sha256
value=dict(schema='orbit-poc-dated-status-publication-independent-review-v1',passed=True,reviewer='/root/v4_independent_review',reviewed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),manifest=pin(mp),helper=pin(Path(__file__)),source_copies_verified=len(s['sources']),files_verified=m['files'],bytes_verified=m['bytes'],terminal_attempts=10,terminal_distribution=a['status_counts'],v4_fits=0,external_artifacts=22,tenth_external_artifacts=18,tenth_copied_compact_receipts=1,previous_finding=pin(C/'status04-publication-independent-finding01.json'),checks=['All exact compact package members and source bytes verified; prior8snapshot linked unchanged.','Dates and scopes match the accepted preparation ownership and original150 checkpoint audits.','Legacy complete under original criteria remains distinct from corrected-v3.1/v4 convergence and covariance.','All23 result artifact references preserved;22 external entries and1 copied compact preservation receipt classified accurately.','No arrays/raw rows or bulky native artifacts copied; no current run-state inference, release or fit-isolation claim.'],scope='Publication-only byte and claim audit. No remote probing, scientific rerun or external artifact rehash.',release_ready=False)
out=Path(args.output)
with out.open('x') as f:json.dump(value,f,indent=2,sort_keys=True);f.write('\n')
print(json.dumps(pin(out)))
