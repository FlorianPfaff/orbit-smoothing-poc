"""Verify the approved source-only correction; no campaign writes or native runs."""
from datetime import datetime, timezone
import ast
import importlib.util
import json
from pathlib import Path
from orbit_poc.comparison.protocol import source_snapshot,file_hash,canonical_hash

base=Path('/home/florianpfaff/codex-runs/orbit-comparison-v3-20261013')
reference=base/'project-test-final-f2b41a4b'
current=base/'project-test-candidate-03-complete'
output=Path('/mnt/seagate10tb/orbit-comparison-v3-20261013-florianpfaff/validation-current')
name='protocol-reader-source-equivalence-f2-3b434b8c'
spec=importlib.util.spec_from_file_location('reviewed_helper',base/'freeze_acceptance_03.py')
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
before=source_snapshot(reference);after=source_snapshot(current)
assert before['sha256']==h.ENGINEERING_SOURCE
assert after['sha256']==h.CANDIDATE03_SOURCE
assert set(before['files'])==set(after['files'])
changes={p:{'controlled_sha256':before['files'][p],'final_sha256':after['files'][p]}
         for p in before['files'] if before['files'][p]!=after['files'][p]}
assert set(changes)=={h.PROTOCOL_READER}
h.exact_reader_change((reference/h.PROTOCOL_READER).read_bytes(),(current/h.PROTOCOL_READER).read_bytes())
backend='src/orbit_poc/comparison/backend.py'
assert before['files'][backend]==after['files'][backend]

def function_bytes(project,name):
    text=(project/backend).read_text()
    node=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name==name)
    return ast.get_source_segment(text,node).encode()

assert function_bytes(reference,'fit_job')==function_bytes(current,'fit_job')
native=[p for p in before['files'] if p.startswith('groops/')]
assert all(before['files'][p]==after['files'][p] for p in native)
binary=base/'native/bin/groops-74863d5a16dbcb1f'
assert file_hash(binary)==h.NATIVE_SHA
assert source_snapshot(reference)==before and source_snapshot(current)==after
manifests={}
for label,record in (('before',before),('after',after)):
    path=output/(name+'-'+label+'.json')
    assert not path.exists()
    path.write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
    manifests[label]={'file':path.name,'sha256':file_hash(path),'source_sha256':record['sha256']}
record={'schema_version':3,'passed':True,'controlled_source_sha256':before['sha256'],
 'final_source_sha256':after['sha256'],'source_file_differences':changes,
 'approved_replacement':{'path':h.PROTOCOL_READER,'old':h.OLD_READER.decode(),'new':h.NEW_READER.decode()},
 'scope':'Only protocol._fit preprocessing-audit lookup changes; native, backend fitting, model, numerical settings, preparation, scoring and evaluation bytes are unchanged',
 'fit_job_identical':True,'native_source_identical':True,'unchanged_backend_sha256':before['files'][backend],
 'runtime_files_verified':len(before['files']),'unchanged_native_files_verified':len(native),
 'native_binary_sha256':h.NATIVE_SHA,'source_manifests':manifests,
 'review_basis':['The backend already emits the audit at top level; the protocol now reads this documented result field.',
  'Legacy metadata is consulted only when the top-level key is absent; conflicting non-null legacy values explicitly block.',
  'The unchanged SHA-format and cross-method/candidate equality checks still reject missing, malformed or unequal audits.',
  'The exact approved lookup block is the sole byte difference in the complete runtime source file inventory.',
  'The native/backend numerical engineering evidence retains its original f2/c8/c766 source identities; only this post-fit protocol reader differs.'],
 'full_suite_requirement':'Fresh automated-tests-3b434b8c evidence must separately pass before acceptance; this source audit does not stand in for that suite.',
 'scientific_comparison_complete':False,'acceptance_frozen':False,
 'recorded_at_utc':datetime.now(timezone.utc).isoformat(),
 'audit_script_sha256':file_hash(__file__),'review_helper_sha256':file_hash(base/'freeze_acceptance_03.py')}
path=output/(name+'.json');assert not path.exists()
path.write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
print(json.dumps({'source_hash':after['sha256'],'runtime_files':len(before['files']),'changed_files':list(changes),'record':str(path),'record_sha256':file_hash(path),'passed':True}))
