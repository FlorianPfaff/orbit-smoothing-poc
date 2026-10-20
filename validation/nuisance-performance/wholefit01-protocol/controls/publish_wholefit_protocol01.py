#!/usr/bin/env python3
"""Publish immutable whole-fit controls; never inspect live numerical output."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,stat
BASE=Path('/home/emper/orbit-nuisance-performance');W=BASE/'wholefit01';C=BASE/'control'
OUT=BASE/'source/validation/nuisance-performance/wholefit01-protocol'

def sha_bytes(b):return hashlib.sha256(b).hexdigest()
def canonical(v):return sha_bytes(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def save(p,v):
 with p.open('x') as f:json.dump(v,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
def state(pid):
 p=Path('/proc')/str(pid);data=(p/'stat').read_text();tail=data[data.rfind(')')+2:].split()
 return dict(pid=pid,parent=int(tail[1]),start_ticks=int(tail[19]),comm=(p/'comm').read_text().strip(),
             executable=os.readlink(p/'exe'),children=[int(x) for x in (p/'task'/str(pid)/'children').read_text().split()])

if os.sched_getaffinity(0)!={4}:raise ValueError('Protocol publication must use CPU4')
freeze=json.loads((W/'freeze.json').read_text());launch=json.loads((W/'controller-launch.json').read_text())
if sha_bytes((W/'freeze.json').read_bytes())!=launch['freeze_sha256']:raise ValueError('Launch freeze mismatch')
if Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=launch['boot_id']:raise ValueError('Changed boot')
controller=state(launch['pid'])
if controller['start_ticks']!=launch['start_ticks']:raise ValueError('Controller identity changed')
queue=list(controller['children']);processes=[controller]
while queue and len(processes)<16:
 pid=queue.pop(0)
 try:r=state(pid)
 except (FileNotFoundError,ProcessLookupError):continue
 processes.append(r);queue.extend(r['children'])
if not any(x['executable']==freeze['candidate']['path'] for x in processes):raise ValueError('Expected first-arm native process not observed')
if (W/'cache0').exists():raise ValueError('Second arm already started; update explicit status attribution separately')
observed=datetime.now(timezone.utc).isoformat()
status=dict(schema='orbit-poc-wholefit-protocol-publication-status-v1',observed_at=observed,
            evidence_scope='Bounded owned-process metadata and second-arm directory existence only. No live scientific files, logs, rows or results read.',
            process_snapshot_atomic=False,controller=launch,owned_processes=processes,
            arms=[dict(name='cache1',cache=1,status='running'),dict(name='cache0',cache=0,status='pending')],
            numerical_outcome_claim=False)
selections=[]
for name in ['freeze.json','preparation.json','input-protocol01.json','source-inventory.json','runtime-closures01.json',
             'python-runtime-actual01.json','python-runtime.json','local-input-copies01.json','input-layout01.json','input-preflight01.json',
             'controller-launch.json','launch.json','capture-inputs-plan01.json','capture-inputs01.execution.json',
             'capture-inputs01.stderr','capture-inputs01.remote.py','capture-inputs02.execution.json',
             'capture-inputs02.receipt.json','capture-inputs02.stderr','capture-inputs02.remote.py',
             'capture_inputs01.py','capture_inputs02.py','copy_local_inputs01.py','prepare_local_requests01.py']:
 selections.append((W/name,'protocol/'+name))
for name in ['request.json','native_preparation.json','capture-preparation.py','capture-preparation-receipt.json','capture-preparation.stderr']:
 selections.append((W/'original'/name,'original/'+name))
for name in ['cache1.request.json','cache0.request.json']:
 selections.append((W/'templates'/name,'templates/'+name))
selections.append((W/'inputs/native_preparation.json','adapted/native_preparation.json'))
for name in ['freeze_wholefit01.py','run_wholefit01.py','wholefit_worker01.py','audit_wholefit_preparation01.py',
             'wholefit-controller-independent-review01.json','wholefit-preparation-independent-review01.json',
             'wholefit-concrete-launch-independent-review01.json','wholefit-analysis-design01.json',
             'test_wholefit_controller_review01.py','test_wholefit_controller_review01.before-fixture-adaptation.py',
             'wholefit-controller-review01-tests.log','wholefit-controller-review01-tests.xml',
             'wholefit-controller-review02-tests.log','wholefit-controller-review02-tests.xml',
             'publish_wholefit_protocol01.py','candidate-build-complete01.json']:
 selections.append((C/name,'controls/'+name))
selections.append((BASE/'build-01/build-manifest.json','build/candidate-build-manifest.json'))
prep=json.loads((W/'preparation.json').read_text())
for change in prep['configuration_transformations']:
 key=Path(change['local_path']).name
 selections.append((W/'inputs/mirror'/change['original_path'].lstrip('/'),'original/configs/'+key))
 selections.append((Path(change['local_path']),'adapted/configs/'+key))
exporter=Path(freeze['diagnostic_exporter']['path'])
selections.append((exporter.with_name(exporter.name+'.build-manifest.json'),'build/original-exporter-build-manifest.json'))
OUT.mkdir(exist_ok=False)
records=[]
for source,relative in selections:
 before=source.stat()
 if source.is_symlink() or not stat.S_ISREG(before.st_mode) or before.st_size>1000000:raise ValueError('Unexpected publication payload: '+str(source))
 data=source.read_bytes();after=source.stat()
 identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)
 if identity(before)!=identity(after):raise ValueError('Immutable control changed during copy')
 destination=OUT/relative;destination.parent.mkdir(parents=True,exist_ok=True)
 with destination.open('xb') as f:f.write(data)
 digest=sha_bytes(data)
 if sha_bytes(destination.read_bytes())!=digest:raise ValueError('Copy mismatch')
 records.append(dict(path=relative,source=str(source),sha256=digest,bytes=len(data),source_device=before.st_dev,source_inode=before.st_ino,source_mtime_ns=before.st_mtime_ns,source_unchanged_during_copy=True))
save(OUT/'status-at-publication.json',status)
readme=f"""# Whole-fit nuisance-cache protocol

The protocol was frozen before launch. At **{observed}**, the cache-enabled attempt was running and the cache-disabled attempt was pending. This packet contains immutable controls and a bounded process-status observation; it contains no numerical results.

The two attempts use the original 24-hour **500 km, quiet atmosphere, normal tracking, pulse** case that timed out in campaign09. Both use candidate `8b6986943d7836c4f4cb03278069893d3b797a5bcbd2a3f4ba763a1b27a6fcb2`, with cache order **1 → 0**. Inputs, initialization, pulse interval (1,200 s), pulse standard deviation (10⁻⁴ m/s), physical models, weights and correctness thresholds are preserved. Each full fit retains the two-hour limit, 8 GiB process-tree limit, one numerical thread, 32 accepted iterations and 96 trials.

The [actual freeze](protocol/freeze.json), [input preparation](protocol/preparation.json), [source inventory](protocol/source-inventory.json), [runtime inventory](protocol/runtime-closures01.json) and [actual Python runtime](protocol/python-runtime-actual01.json) identify the planned execution. Its SHA-256 is `{launch['freeze_sha256']}`. The [independent launch review](controls/wholefit-concrete-launch-independent-review01.json) predates launch. [Copy provenance](manifest.json) records every published file and its source hash.

The original diagnostic exporter `643a1b6d523a363eae88902f2a2d4807452ea3edbd504bceaad23a94d65fb2f6` is retained. Both arms share the recorded local runtime; six system-library or loader files differ from the historical remote runtime. This experiment does not establish equivalence to that historical runtime. One attempt per arm cannot support a statistical speedup claim. A timeout remains a failure, and progress cannot authorize covariance or establish whole-fit convergence.

The [first input-transfer failure](protocol/capture-inputs01.execution.json) and [its error](protocol/capture-inputs01.stderr) are retained: Python 3.10 rejected the streaming tar `compresslevel` argument before reading input files. The corrected gzip-stream capture succeeded with the original hashes. The earlier controller test-fixture failures are also preserved alongside their corrected checks.

Bulky inputs, executables, transfer archives and every live fit output stay outside this packet. The frozen v4 campaign remains separate. Later results require their own attributed report; the running/pending status here is fixed to the timestamp above.
"""
with (OUT/'README.md').open('x') as f:f.write(readme)
for relative in ['README.md','status-at-publication.json']:
 p=OUT/relative;records.append(dict(path=relative,sha256=sha_bytes(p.read_bytes()),bytes=p.stat().st_size,generated=True))
manifest=dict(schema='orbit-poc-wholefit-protocol-publication-v1',created_at=observed,publication_cpu=4,
              source_root=str(W),destination_root=str(OUT),freeze_sha256=launch['freeze_sha256'],
              scope='Immutable predeclared two-attempt protocol, exact copy provenance and metadata-only launch-status snapshot; no live numerical output read or copied.',
              omitted=['bulky source and converted inputs','executables and shared libraries','transfer archives including failed21-byte archive','live fit outputs, logs, row archives and numerical results'],
              files=sorted(records,key=lambda r:r['path']))
manifest['manifest_hash']=canonical(manifest);save(OUT/'manifest.json',manifest)
print(json.dumps(dict(directory=str(OUT),files=len(records)+1,bytes=sum(r['bytes'] for r in records)+(OUT/'manifest.json').stat().st_size,
                     manifest_sha256=sha_bytes((OUT/'manifest.json').read_bytes()),manifest_hash=manifest['manifest_hash'],observed_at=observed)))
