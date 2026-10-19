#!/usr/bin/env python3
"""Project a fixed local proof into compact publication data; execute no controls."""
from collections import Counter
from pathlib import Path
import hashlib,json

HERE=Path(__file__).resolve().parent
SOURCE=Path('/mnt/d/orbit-segmented-v4/control/loader-alias-smoke-terminal03/execution/proof.json')
EXPECTED='28a55f76f007b023d166621e29f80dbf508b6ca4a7fb81c68d7f6bd50461f75e'
raw=SOURCE.read_bytes()
assert hashlib.sha256(raw).hexdigest()==EXPECTED and len(raw)==1558491
v=json.loads(raw)
assert v['status']=='passed' and v['benchmark_attempts_launched']==0 and v['fit_execution_authorized'] is False
assert v['descriptors']==[] and v['release_ready'] is False
denial=v['denial_probes'];errno_counts=dict(sorted(Counter(str(r['errno']) for r in denial).items()))
assert len(denial)==len({r['path'] for r in denial})==1800 and errno_counts=={'2':1800}
forms=Counter('proc_self_root' if r['path'].startswith('/proc/self/root/') else 'proc_1_root' if r['path'].startswith('/proc/1/root/') else 'direct' for r in denial)
assert forms=={'direct':600,'proc_self_root':600,'proc_1_root':600}
public=v['public_readonly_checks'];validation=public['validation'];mounts=v['mount_checks']
assert public['terminal_prefix']==[] and validation['status']=='passed' and len(validation['checks'])==14
result={'schema':'orbit-poc-campaign09-smoke03-compact-proof-v1',
 'scope':'Deterministic projection of the recorded smoke03 proof. The complete proof remains external. Validation fields describe read-only verification of existing prebenchmark evidence; no new scientific fit or validation workload is asserted.',
 'source_proof':{'path':str(SOURCE),'sha256':EXPECTED,'bytes':len(raw)},
 'status':v['status'],'benchmark_attempts_launched':v['benchmark_attempts_launched'],
 'fit_execution_authorized':v['fit_execution_authorized'],'release_ready':v['release_ready'],
 'specification_file_sha256':v['specification_file_sha256'],
 'specification_content_sha256':v['specification_content_sha256'],
 'host_verified_final_artifacts':v['host_verified_final_artifacts'],
 'denial_probe_count':len(denial),'distinct_denial_paths':len({r['path'] for r in denial}),
 'denial_errno_counts':errno_counts,'denial_path_forms':dict(sorted(forms.items())),
 'descriptors':v['descriptors'],'namespaces':v['namespaces'],
 'mount_checks':{'mount_record_count':len(mounts['mounts']),
                 'ordinary_writable':mounts['ordinary_writable'],
                 'retained_attempts_readonly':mounts['retained_attempts_readonly'],
                 'virtual_mount_scope':mounts['virtual_mount_scope']},
 'public_readonly_checks':{'manifest_hash':public['manifest_hash'],'terminal_prefix':public['terminal_prefix'],
   'validation':{'status':validation['status'],'scope':validation['scope'],
                 'pipeline':validation['pipeline'],'plan_hash':validation['plan_hash'],
                 'check_names':sorted(validation['checks']),'check_count':len(validation['checks'])}},
 'omitted_bulk_fields':['denial_probes path rows','mount_checks.mounts inventory','public_readonly_checks.validation.checks detailed inventories/results'],
 'original_scope':v['scope']}
data=(json.dumps(result,indent=2,sort_keys=True)+'\n').encode()
p=HERE/'compact-proof.json'
if p.exists():assert p.read_bytes()==data
else:
 with p.open('xb') as f:f.write(data)
