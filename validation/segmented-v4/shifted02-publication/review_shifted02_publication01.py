#!/usr/bin/env python3
"""Independent byte/claim check of the closed shifted-cut text distribution."""
from pathlib import Path
from collections import Counter
import hashlib,json,re,tarfile
C=Path(__file__).resolve().parent
P=C.parent/'publication-shifted02-git-02'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p),'bytes':Path(p).stat().st_size}
def checked(p):
    assert sha(p['path'])==p['sha256'] and Path(p['path']).stat().st_size==p['bytes'],p
def read(p):return json.loads(Path(p).read_text())
mp=P/'manifest.json';assert sha(mp)=='f5b384e1cee1a03116491449878f5d3bd6585e3296dbcdf911a543426bc84c0b'
m=read(mp); files=m['files'];assert len(files)==120
assert {str(p.relative_to(P)) for p in P.rglob('*') if p.is_file()}=={x['path'] for x in files}|{'manifest.json'}
assert not any(p.is_symlink() for p in P.rglob('*'))
unavailable_originals=[]
for row in files:
    name=Path(row['path']);assert not name.is_absolute() and '..' not in name.parts
    p=P/name;assert sha(p)==row['sha256'] and p.stat().st_size==row['bytes']
    p.read_text() # Every published member must be text.
    if 'original' in row:
        assert row['original']['sha256']==row['sha256'] and row['original']['bytes']==row['bytes']
        if Path(row['original']['path']).exists():
            checked(row['original']);assert p.read_bytes()==Path(row['original']['path']).read_bytes()
        else:
            assert Path(row['original']['path']).parent==Path('/tmp') and p.suffix=='.xml'
            unavailable_originals.append(row['original'])
assert sum(x['bytes'] for x in files)==m['bytes']==1226435
for k in ('audit','capture','builder'):checked(m[k])
assert m['audit']['sha256']=='8b7710f665992bbed6ce128ce9f773104f283c95eb4c623739375380bc0aec51'
assert m['capture']['sha256']=='2fcbbeb40d456fb852eda01aac0098ef748938de16eae8bfe12aaf90d4c14f79'
assert m['builder']['sha256']=='b57cb04100a34735466bfb3ca5ab5b1824f1aa12f297fbe2f1eaff0ff29caf22'
a=read(P/'audit.json');assert (P/'audit.json').read_bytes()==Path(m['audit']['path']).read_bytes()
capture=read(P/'raw-capture/manifest.json');assert (P/'raw-capture/manifest.json').read_bytes()==Path(m['capture']['path']).read_bytes()
ext=read(P/'external-evidence.json');assert len(ext['files'])==84
assert Counter(x['category'] for x in ext['files'])=={'captured_numerical_payload':48,'shifted_raw_rows':32,'original_raw_rows':4}
records={x['stored']['path']:x for x in capture['records']};assert len(records)==109
omitted={x['capture_member']:x for x in ext['files'] if x['category']=='captured_numerical_payload'}
for name,x in omitted.items():
    r=records[name];assert x['source']==r['source'];assert not (P/'raw-capture'/name).exists()
    checked(x['local_preserved']);assert x['local_preserved']['sha256']==r['stored']['sha256'] and x['local_preserved']['bytes']==r['stored']['bytes']
for name,r in records.items():
    if name in omitted:continue
    q=P/'raw-capture'/name;assert sha(q)==r['stored']['sha256'] and q.stat().st_size==r['stored']['bytes']
assert len(records)-len(omitted)==61
for category,key in [('shifted_raw_rows','external_not_copied'),('original_raw_rows','original_unshifted_rows')]:
    rows=[{k:v for k,v in x.items() if k!='category'} for x in ext['files'] if x['category']==category]
    if category=='shifted_raw_rows':
        rows=[{'artifact':x['source'],'reason':x['reason']} for x in rows]
    assert rows==capture[key]
s=read(P/'summary.json');assert s['identity']==a['identity'] and s['scientific_status']==a['scientific_status']=='passed_scoped_checks'
assert a['consistency_passed'] and a['cleanup_verified']
for k in ('release_ready','fit_covariance_authorized'):assert s[k] is False and m[k] is False and a[k] is False
for k in ('physical_evaluations','nuisance_profile_evaluations','benchmark_attempts_executed'):assert s[k]==a[k]==0
assert s['benchmark_attempts_planned']==68 and s['benchmark_status']=='not_run'
assert s['solver_calls']==a['solver_calls']==32
assert [x['method'] for x in s['methods']]==[x['method'] for x in a['methods']]==['log_drag_ou','pulses']
profiles=trials=0
for am,sm in zip(a['methods'],s['methods']):
    assert am['original_columns']==sm['original_columns'] and len(am['profiles'])==len(sm['profiles'])==4
    for ap,sp in zip(am['profiles'],sm['profiles']):
        profiles+=1;trials+=len(sp['trials']);assert len(sp['trials'])==3
        for k in ('segment_seconds','offset_seconds','covariance_relative_error','trials'):assert ap[k]==sp[k]
        assert [x['damping'] for x in sp['trials']]==[0.,.001,1000.]
        assert sp['interior_movement_count']==ap['coverage']['interior_movement_count']
        assert sp['cut_coverage']==('genuine_interior_movement' if ap['coverage']['adequate'] else 'no_cut_coverage')
        for dest,src in [('maximum_map_discrepancy_posterior_sd','map_discrepancy_posterior_sd'),('maximum_normalized_full_energy_difference','normalized_full_energy_difference'),('maximum_independent_equality_backward_error','independent_all_row_equality_backward_error')]:assert sp[dest]==max(t[src] for t in ap['trials'])
        if am['method']=='pulses' and sp['offset_seconds']==300:assert sp['interior_movement_count']==0 and sp['cut_coverage']=='no_cut_coverage'
        if sp['offset_seconds']==1800:assert sp['interior_movement_count']>0
assert (profiles,trials)==(8,24)
html=(P/'index.html').read_text();assert html.count('<tr>')==9
for text in ['24 proposal solves and 8 undamped covariance solves','0 of 68 fits','no cut-coverage evidence','not be counted as independent long-arc trials','unit denominator','this historical failure is not attributed to the new native run']:assert text in html,text
links=re.findall(r'href="([^"]+)"',html)
for link in links:
    if link=='../validation04/index.html':continue # Verified intended sibling deployment target.
    assert (P/link).is_file(),link
for row in s['preserved_history']:assert (P/'provenance'/row['evidence']).is_file()
asset_manifest=P.parent/'publication-shifted02-assets-01/manifest.json'
asset=read(asset_manifest);checked(asset['asset']);checked(asset['source_archive']);checked(asset['capture_manifest'])
assert sha(asset_manifest)=='18770eebec2c9507ef3f0d02762dcd8e15e119f572a52126cdbeb018877a4026'
assert asset['asset']['sha256']=='17c16d8ee9c628f33346e61bbbc065eba6830afb10c54a686b5c8ac3eeb85c5c'
assert asset['remote_shifted_row_files']==capture['external_not_copied']
assert asset['remote_original_row_files']==capture['original_unshifted_rows']
assert asset['benchmark_attempts_executed']==0 and asset['fit_covariance_authorized'] is False and asset['release_ready'] is False
expected={name:{'sha256':r['stored']['sha256'],'bytes':r['stored']['bytes']} for name,r in records.items()}
expected['manifest.json']={'sha256':sha(P/'raw-capture/manifest.json'),'bytes':(P/'raw-capture/manifest.json').stat().st_size}
seen=set()
with tarfile.open(asset['asset']['path'],'r:gz') as archive:
    for member in archive:
        name=Path(member.name)
        assert not name.is_absolute() and '..' not in name.parts and name.parts[0]=='terminal-capture-01'
        if member.isdir():continue
        assert member.isfile() and len(name.parts)>1
        relative=str(Path(*name.parts[1:]))
        assert relative in expected and relative not in seen
        stream=archive.extractfile(member);digest=hashlib.sha256();size=0
        while data:=stream.read(1048576):digest.update(data);size+=len(data)
        assert size==member.size==expected[relative]['bytes'] and digest.hexdigest()==expected[relative]['sha256']
        seen.add(relative)
assert seen==set(expected) and len(seen)==110
assert not any(Path(x['path']).suffix.lower() in {'.npz','.npy','.rows'} for x in files)
assert sha(mp)=='f5b384e1cee1a03116491449878f5d3bd6585e3296dbcdf911a543426bc84c0b'

v={'schema':'orbit-poc-shifted-publication-independent-review-v1','reviewer':'/root/v4_independent_review','passed':True,'artifacts':{'manifest':pin(mp),'summary':pin(P/'summary.json'),'html':pin(P/'index.html'),'external_inventory':pin(P/'external-evidence.json'),'terminal_audit':m['audit'],'helper':pin(__file__)},'verified_files':120,'verified_bytes':1226435,'exact_original_copies':sum('original' in x for x in files),'captured_text_records':61,'external_counts':dict(Counter(x['category'] for x in ext['files'])),'profiles':8,'proposal_solves':24,'undamped_covariance_solves':8,'scope':'Byte/identity/presentation review against the independently audited closed diagnostic. No scientific recomputation or production launch.','claims_verified':['One-hour synthetic captured linearizations only; zero physical or nuisance evaluations.','Pulse300s provides no interior cut coverage;1800s provides movement for both methods and periods.','Covariance is undamped linearization covariance, not accepted-fit covariance.','Historical diagnostic01 parser and new publication-only input-format failures remain distinct from successful diagnostic02 native solves.','Benchmark remains0/68; no release, long-arc, flight or speedup claim.'],'benchmark_attempts_executed':0,'release_ready':False,'native_processes_launched':0}
v['external_asset']=pin(asset_manifest)
v['external_asset_verified_regular_members']=110
assert unavailable_originals==[]
v['all_original_source_copies_currently_verified']=True
v['builder_delta']='Only narrative labels/report links changed from the previously reviewed builder; numerical parsing, external payload classification and source-recheck logic are unchanged.'
v['publication_failure']=pin(C/'shifted02-publication-staging-failure01.json')
assert any(x['path'].endswith('.json.raw.txt') and x['bytes']==0 for x in files)
out=C/'shifted02-publication-independent-review01.json'
with out.open('x') as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
print(json.dumps(pin(out)))
