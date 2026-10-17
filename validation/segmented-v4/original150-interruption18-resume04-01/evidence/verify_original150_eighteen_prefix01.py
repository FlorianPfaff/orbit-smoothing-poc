from pathlib import Path
from types import SimpleNamespace
from dataclasses import asdict,make_dataclass
import ast,json,hashlib,datetime,collections
C=Path('/mnt/d/orbit-segmented-v4/control');B=Path('/mnt/d/orbit-numerics-v3.1/benchmark-d-volume/benchmark-01');P=C/'original150-interrupted-attempt18-proposal01/proposal.json'
def pin(p):
 p=Path(p);b=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest()}
def read(p):return json.loads(Path(p).read_bytes())
def verify(r):
 p=Path(r['path']);assert not p.is_symlink() and pin(p)['sha256']==r['sha256'];return p
def canonical(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
p=read(P);applied=C/'original150-interrupted-attempt18-apply01.json';run=read(applied);assert run['status']=='applied_exact_approved_bytes'and len(run['written'])==3
for row in p['append_files']:assert Path(row['destination']).read_bytes()==verify(row['candidate']).read_bytes()
m=read(verify(p['manifest']));cfg=read(verify(p['configuration']));source=verify(p['archived_protocol']);nodes={n.name:n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef)}
ns={'read_json':read,'verify_artifact':verify,'canonical_hash':canonical,'asdict':asdict,'validate_complete_result':lambda *_:(_ for _ in()).throw(AssertionError('Interrupted18 cannot be complete'))}
exec(compile(ast.Module(body=[nodes['attempt_job'],nodes['verify_checkpoint']],type_ignores=[]),str(source),'exec'),ns)
controls=make_dataclass('FrozenControls',[(k,object)for k in cfg['controls']]);a=m['attempts'][17];case=next(x for x in m['cases']if x['case_id']==a['case_id']);job=ns['attempt_job'](SimpleNamespace(controls=controls(**cfg['controls'])),m,case,a)
result=ns['verify_checkpoint'](B/'attempts'/a['attempt_id'],job);assert result['status']=='interrupted'
prefix=[]
for i,at in enumerate(m['attempts'][:18]):
 d=B/'attempts'/at['attempt_id'];r=pin(d/'result.json');ix=pin(d/'result-record.json');v=read(d/'result.json');idx=read(d/'result-record.json');assert idx['result']==r and idx['status']==v['status']
 if i<17:
  old=p['expected_checkpoint_prefix'][i];assert old['attempt_id']==at['attempt_id']
  for k,val in [('result',r),('index',ix)]:assert all(old[k][key]==val[key]for key in ['path','sha256'])
 prefix.append({'attempt_id':at['attempt_id'],'profile':at['profile'],'status':v['status'],'result':r,'index':ix})
for at in m['attempts'][18:]:
 d=B/'attempts'/at['attempt_id'];assert not d.exists()or(d.is_dir()and not any(d.iterdir()))
value={'schema':'orbit-poc-original150-eighteen-prefix-postappend-v1','passed':True,'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'helper':pin(__file__),'proposal':pin(P),'append_result':pin(applied),'actual_three_files_equal_approved_candidates':True,'new_eighteenth_archived_checkpoint_validation_passed':True,'first_seventeen_result_index_bytes_unchanged':True,'terminal_prefix':prefix,'terminal_attempts':18,'status_counts':dict(collections.Counter(r['status']for r in prefix)),'future_attempts_unstarted':132,'scope':'Actual new18 checkpoint accepted by the unchanged archived validator; first17 exact result/index bytes preserved, not a repeated full scientific artifact audit. Append helper rechecked all224 partial hashes and9aliases before/after under lock. No numerical retry, native substitution, cleanup fabrication or continuation launch.'}
out=C/'original150-eighteen-prefix-postappend01.json'
with out.open('x')as f:json.dump(value,f,indent=2);f.write('\n')
print(json.dumps(pin(out)))
