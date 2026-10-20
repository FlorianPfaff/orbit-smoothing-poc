import importlib.util,json,tempfile,hashlib
from pathlib import Path
D=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('fixture',D/'tests/test_nuisance_performance_pair.py');f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
rows=[]
with tempfile.TemporaryDirectory(prefix='nuisance-review2-') as t:
 off,on=f.pair(Path(t));v=f.check.compare(off,on);assert v['passed'] and v['cache_pair_verified'];rows.append({'case':'reviewed_actual_runner_taskset_shape','passed':v['passed']})
 for p in (off,on):
  q=p/'profile.execution.json';e=json.loads(q.read_text());e.update(status='running',owned_process_group_cleaned=False,cache=0);q.write_text(json.dumps(e))
 v=f.check.compare(off,on);assert not v['passed'] and not v['cache_pair_verified'];rows.append({'case':'both_running_unclean_and_cache_off','passed':v['passed'],'issues':v['issues']})
with tempfile.TemporaryDirectory(prefix='nuisance-review2-') as t:
 off,on=f.pair(Path(t));q=on/'profile.execution.json';e=json.loads(q.read_text());e['cache']=0;q.write_text(json.dumps(e));v=f.check.compare(off,on);assert not v['passed'];rows.append({'case':'off_off_alone_rejected','passed':v['passed']})
with tempfile.TemporaryDirectory(prefix='nuisance-review2-') as t:
 off,on=f.pair(Path(t));q=on/'qr.1.nuisance_performance.json';s=json.loads(q.read_text());s['arithmetic_audits']=[s['zero_update_replay']];q.write_text(json.dumps(s));v=f.check.compare(off,on);assert not v['passed'];rows.append({'case':'unmatched_arithmetic_timing_rejected','passed':v['passed'],'issues':v['issues']})
with tempfile.TemporaryDirectory(prefix='nuisance-review2-') as t:
 off,on=f.pair(Path(t));q=on/'qr.1.nuisance_performance.json';s=json.loads(q.read_text());s['probe_rounds']=[[s['zero_update_replay']]];q.write_text(json.dumps(s));v=f.check.compare(off,on);assert not v['passed'];rows.append({'case':'unmatched_probe_timing_rejected','passed':v['passed'],'issues':v['issues']})
# Bind actual reviewed job metadata without executing or making artifacts in those job roots.
B=Path('/home/emper/orbit-nuisance-performance');prep_path=B/'paired01/preparation.json';prep=json.loads(prep_path.read_text());native={'path':str(B/'build-01/groops'),'sha256':'b'*64}
with tempfile.TemporaryDirectory(prefix='nuisance-review2-bind-') as t:
 freeze=Path(t)/'freeze.json';freeze.write_text(json.dumps({'schema':'orbit-poc-nuisance-pair-freeze-v1','preparation_sha256':hashlib.sha256(prep_path.read_bytes()).hexdigest(),'order':prep['predeclared_order'],'native':native}))
 runs=[]
 for cache in (0,1):
  job=next(j for j in prep['jobs'] if j['method']=='pulses' and j['accumulate']==0 and j['cache']==cache)
  row={'available':True,'interpolation_cache':bool(cache),'interpolation_calls':2,'interpolation_cache_hits':cache,'interpolation_evaluations':2-cache}
  side={'parent_row_build':row,'zero_update_replay':{'row_build':row},'ordinary_trials':[],'arithmetic_audits':[],'probe_rounds':[]}
  runs.append({'execution_verified':True,'root':str(Path(job['profile']).parent),'final_generation':2,'performance_sidecars':[side],'execution':{'cache':cache,'accumulate_epoch_observations':0,'freeze_sha256':hashlib.sha256(freeze.read_bytes()).hexdigest(),'native_binary_sha256':native['sha256'],'config_sha256':job['profile_sha256'],'command':['/usr/bin/taskset','-c','0',native['path'],job['profile']],'blas_openmp_threads':1,'input_identity_after':'verified'}})
 r=f.check.bind_cache_pair(runs,freeze,prep_path);assert r['verified'];rows.append({'case':'actual_preparation_schema_contract_with_explicitly_synthetic_execution_values','verified':r['verified'],'native_executed':False,'scope':'Metadata binding fixture only, not evidence of actual completed profiles.'})
out=D/'counterexamples-result.json';out.write_text(json.dumps({'schema':'nuisance-tools-review-counterexamples-v2','script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'cases':rows},indent=2)+'\n');print(out)
