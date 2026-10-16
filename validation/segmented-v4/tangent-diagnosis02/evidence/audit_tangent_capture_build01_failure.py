from pathlib import Path
import json,hashlib,datetime
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');D=B/'tangent-capture-01';O=B/'engineering-02'
def pin(p):
 p=Path(p);return dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size)
j=json.loads((D/'control/pipeline.json').read_text());m=json.loads((O/'build/build-manifest.json').read_text())
assert pin(D/'control/pipeline.json')['sha256']=='21aecd8b88649e7adf6e93c74f93d13f520a679a7381781d412cd13d6d03609b'
assert j['status']=='failed_diagnostic' and j['returncode']==1 and j['final_cleanup']['verified'] and not j['final_cleanup']['errors']
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==j['admission']['boot_id']
current={str(p.relative_to(O/'groops-source/source')):pin(p)['sha256']for p in(O/'groops-source/source').rglob('*')if p.is_file()}
assert {'source/'+k:v for k,v in current.items()}==m['patched_source']['files']
assert pin(O/'build/groops')['sha256']==m['executable_sha256']=='a66949456ad67b816d09f2f14df792c68c2685f5304139499e4d90092fd75b22'
assert all(not list((D/n).iterdir())for n in ('native_source','build','binaries'))
assert not(D/'run/build-result/result.json').exists() and not(D/'run/build-result/inputs.json').exists()
log=(D/'control/native-replay.log').read_text();assert 'line 29' in log and 'AssertionError' in log
ids={(q['pid'],q['start_ticks'])for q in[j['admission']['driver_identity'],*j['cleanup']['identities']]};absences=[]
for pid,start in sorted(ids):
 try:
  raw=(Path('/proc')/str(pid)/'stat').read_text();fields=raw[raw.rfind(')')+2:].split();assert int(fields[19])!=start or fields[0]=='Z';absences.append(dict(pid=pid,start_ticks=start,non_live=True))
 except FileNotFoundError:absences.append(dict(pid=pid,start_ticks=start,non_live=True,absent=True))
print(json.dumps(dict(schema='orbit-poc-tangent-capture-build01-control-failure-independent-readback-v1',passed=True,observed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),pipeline=pin(D/'control/pipeline.json'),worker_log=pin(D/'control/native-replay.log'),original_manifest=pin(O/'build/build-manifest.json'),native=pin(O/'build/groops'),source_members=len(current),source_hashes_equal_after_exact_prefix=True,private_native_source_build_binaries_empty=True,compiled_native_evaluations=0,fit_attempts=0,owned_identities_non_live=absences,classification='Metadata key convention mismatch before native source copy or compilation: build manifest uses source/ prefixes, while the helper collected relative names beneath that directory. All actual source hashes and original executable remain unchanged.'),indent=2))
