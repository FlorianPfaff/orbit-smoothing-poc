from pathlib import Path
import json,hashlib,datetime
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');C=B/'preparation-03/control';R=B/'validation-04/run'
def pin(p):
 p=Path(p);b=p.read_bytes();return dict(path=str(p),sha256=hashlib.sha256(b).hexdigest(),bytes=len(b))
def read(p):return json.loads(Path(p).read_text())
pp=C/'pipeline.json';assert pin(pp)['sha256']=='af054964670e6f978bde7db205dc9933ab269825e3ed176e2ca9cd251abc0ae3';p=read(pp)
assert p['status']=='failed_or_blocked' and p['benchmark_attempts']==0 and p['release_ready'] is False
assert p['plan']['sha256']=='99579b42e6bb743b6bba16da9da12ef04e568fa18b920af03231f6aca4d7de83' and pin(p['plan']['path'])['sha256']==p['plan']['sha256']
assert p['final_cleanup']['verified'] and p['final_cleanup']['errors']==[]
assert [x['returncode'] for x in p['checks']]==[0,1] and p['preparation']['returncode']==1
assert p['preparation']['interrupted_or_timeout'] is False
status=R/'preparation-status.json';assert pin(status)['sha256']=='14e1883227b181038b184b0bbf1e57119fcf28d7d58db340d5e21a72038276e6';ss=read(status);assert ss['status']=='blocked' and ss['expected_attempts']==68
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();assert boot==p['admission']['boot_id']=='95156dd4-0d4c-499d-a214-8883a2d650fa'
identities={(p['admission']['driver_identity']['pid'],p['admission']['driver_identity']['start_ticks'])}
for command in p['final_cleanup']['commands']:
 assert command['verified'] and command['live_owned_processes']==[]
 identities.update((x['pid'],x['start_ticks']) for x in command['identities'])
absence=[]
for pid,ticks in sorted(identities):
 try:
  f=(Path('/proc')/str(pid)/'stat').read_text().rsplit(')',1)[1].split();same=int(f[19])==ticks;assert not same or f[0]=='Z';absence.append(dict(pid=pid,start_ticks=ticks,actual_start_ticks=int(f[19]),actual_state=f[0],live=False))
 except FileNotFoundError:absence.append(dict(pid=pid,start_ticks=ticks,absent=True))
rows=[];failed=None
for d in sorted((R/'preparation-jobs').iterdir()):
 if not d.is_dir():continue
 ep=d/'execution.json';assert ep.is_file();v=read(ep);request=read(d/'request.json');h=v['harness_execution'];assert h['cleanup']['verified'] and h['cleanup']['remaining']==[] and h['owned_process_group_cleaned'] is True and h['boot_id']==boot
 assert h['runtime']['native']['sha256']=='a66949456ad67b816d09f2f14df792c68c2685f5304139499e4d90092fd75b22'
 assert h['runtime']['source_sha256']=='68e17e5b5ebe6fe22a47b9c6213c89397cfb80e25cc5e033da2621fc0aa44474'
 assert h['argv'][-1]=='[24]' and h['returncode'] in (0,1)
 row=dict(component_id=d.name,execution=pin(ep),request=pin(d/'request.json'),status=v['status'],component=v.get('component'),returncode=h['returncode'],elapsed_seconds=h['elapsed_seconds'],peak_process_tree_rss_bytes=h['peak_process_tree_rss_bytes'],worker_log=h['log'])
 assert pin(h['log']['path'])['sha256']==h['log']['sha256']
 if h['returncode']==1:
  assert failed is None;failed=row;assert d.name=='prefix-753992c25b8ee35f52468f0d4439501f642bc531685eecd44942eac438ba7769'
  row['worker_traceback']=Path(h['log']['path']).read_text();row['request_top_level_keys']=list(request);row['request_case']=request.get('case');row['request_component']=request.get('component');row['request_output']=request.get('output');row['worker_result_absent']=not(d/'worker-result.json').exists();assert row['worker_result_absent']
 rows.append(row)
assert len(rows)==8 and sum(r['returncode']==0 for r in rows)==7 and sum(r['component']=='generation' for r in rows)==2 and sum(r['component']=='prefix' for r in rows)==5
assert not (R/'manifest.json').exists() and not (R/'attempts').exists()
assert pin(pp)['sha256']=='af054964670e6f978bde7db205dc9933ab269825e3ed176e2ca9cd251abc0ae3'
print(json.dumps(dict(schema='orbit-poc-preparation03-terminal-failure-independent-readback-v1',passed=True,observed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),pipeline=pin(pp),preparation_status=pin(status),finished_at=p['finished_at'],owned_process_absence=absence,components=rows,failed_component=failed,benchmark_fits=0,prepared_manifest_exists=False,scope='Actual failure and owned cleanup audit; native outputs and source are read-only. Successful component status counts do not constitute a complete prepared manifest or scientific fit.'),indent=2))
