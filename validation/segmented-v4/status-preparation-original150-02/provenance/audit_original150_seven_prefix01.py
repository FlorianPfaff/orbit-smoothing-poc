"""Read-only post-append validation; never runs the numerical campaign."""
from pathlib import Path
from types import SimpleNamespace
from dataclasses import make_dataclass,asdict
import ast,hashlib,json,importlib.util,datetime
C=Path('/mnt/d/orbit-segmented-v4/control');B=Path('/mnt/d/orbit-numerics-v3.1/benchmark-d-volume/benchmark-01');P=C/'original150-interrupted-append-proposal01/proposal.json';AP=C/'original150-interrupted-append-plan02.json'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def read(p):return json.loads(Path(p).read_text())
def canonical(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def verify(x):
 p=Path(x['path']);assert p.is_file() and not p.is_symlink() and sha(p)==x['sha256'];return p
assert sha(P)=='1d5259826792399809989a6b381299b6d3bb097fc8225dd6ca109ec67a552bbf' and sha(AP)=='91659414fd19cba85bbe3a59df7c82771c7d5f4ce6584913d5f77b7dde3a1659'
p=read(P);plan=read(AP);helper=verify(plan['helper']);assert sha(helper)=='7700157cd8d3fc3a322e612c636622c9a738d77e6c76929e32c7baf060d715f8'
spec=importlib.util.spec_from_file_location('independent_postappend_helper',helper);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
inspection=m.run(AP,sha(AP),False);assert inspection['status']=='verified_not_applied' and inspection['written']==[]
for x in p['append_files']:
 actual=Path(x['destination']);candidate=verify(x['candidate']);assert actual.read_bytes()==candidate.read_bytes()
manifest=read(verify(p['manifest']));config=read(verify(p['configuration']));source=verify(p['archived_protocol']);nodes={x.name:x for x in ast.parse(source.read_text()).body if isinstance(x,ast.FunctionDef)}
module=ast.Module(body=[nodes['attempt_job'],nodes['verify_checkpoint']],type_ignores=[]);ast.fix_missing_locations(module)
ns={'read_json':read,'verify_artifact':verify,'canonical_hash':canonical,'asdict':asdict,'validate_complete_result':lambda *_:(_ for _ in ()).throw(AssertionError('No complete fit expected'))};exec(compile(module,str(source),'exec'),ns)
ct=make_dataclass('OriginalControls',[(k,object) for k in config['controls']]);cfg=SimpleNamespace(controls=ct(**config['controls']));cases={x['case_id']:x for x in manifest['cases']};prefix=[]
for a in manifest['attempts'][:7]:
 d=B/'attempts'/a['attempt_id'];job=ns['attempt_job'](cfg,manifest,cases[a['case_id']],a);result=ns['verify_checkpoint'](d,job)
 prefix.append({'attempt_id':a['attempt_id'],'profile':a['profile'],'status':result['status'],'result':pin(d/'result.json'),'index':pin(d/'result-record.json')})
assert [x['status'] for x in prefix]==['failed','timeout','timeout','timeout','timeout','failed','interrupted']
for actual,expected in zip(prefix,p['expected_six_checkpoint_prefix']):
 for key in ('result','index'):assert actual[key]['sha256']==expected[key]['sha256'] and actual[key]['path']==expected[key]['path']
for a in manifest['attempts'][7:]:
 d=B/'attempts'/a['attempt_id'];assert not d.exists() or (d.is_dir() and not d.is_symlink() and not any(d.iterdir()))
receipt=read(Path(p['append_files'][0]['destination']));assert receipt['process_cleanup_verified'] is False and receipt['numerical_rerun'] is False and receipt['covariance_authorized'] is False
out=C/'original150-seven-prefix-independent-review01.json';v={'schema':'orbit-poc-original150-seven-prefix-independent-review-v1','passed':True,'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'helper':pin(Path(__file__)),'append_plan':pin(AP),'proposal':pin(P),'current_boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'terminal_prefix':prefix,'terminal_attempts':7,'not_started':143,'actual_three_files_equal_reviewed_candidates':True,'archived_checkpoint_validation_passed':True,'readonly_append_helper_reinspection':inspection,'original_six_checkpoints_unchanged':True,'no_retry_or_covariance_or_fabricated_cleanup':True,'new_launch_approved':False,'scope':'Seven terminal records verified at actual original paths; original seventh partial output and aliases preserved. No fit, source change, full-runtime startup validation or launch performed. Separate admitted launch and frozen startup remain required.'}
with out.open('x') as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
print(json.dumps(pin(out)))
