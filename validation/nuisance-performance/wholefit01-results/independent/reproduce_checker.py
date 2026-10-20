from pathlib import Path
import hashlib,json,os,subprocess,time,datetime
b=Path('/home/emper/orbit-nuisance-performance');a=b/'control/wholefit-outcome-audit01';r=Path('/mnt/d/orbit-nuisance-performance/publication/wholefit01-results');w=b/'wholefit01';py='/mnt/c/users/emper/documents/codex/2026-10-13/i-x20/work/numerics-v3.1/python/bin/python'
sha=lambda f:hashlib.sha256(Path(f).read_bytes()).hexdigest()
tools={b/'source/scripts/analyze_nuisance_wholefit.py':'6316cd37b23edadc678e1a3a083802780488882db37c7ca9d686691f93e74836',b/'source/scripts/analyze_nuisance_profile.py':'3ccf1d2ff9235136c00f909df44f9e623785e2476191717e469f65f05e6040c2',b/'source/scripts/check_nuisance_performance_pair.py':'7a396b15cdb8ca3be1129aedbcf20359e9ddfcb4480c0e03e2d4b24b6f4545fd'}
for p,h in tools.items():assert sha(p)==h
assert sha(w/'freeze.json')=='cb4e4a339361002723cf56053bed27dd521f9f51f097f18b1be148126b78a7e4'
protected={str(p):sha(p) for p in r.rglob('*') if p.is_file()}
protected.update({str(w/'execution-complete.json'):sha(w/'execution-complete.json')})
for name in ('cache1','cache0'):
 for file in ('result.json','supervisor.json','post-input-check.json','effective-environment.json','request.json','supervisor.plan.json'):
  p=w/name/file;protected[str(p)]=sha(p)
assert not (w/'execution-stopped.json').exists()
freeze=json.loads((w/'freeze.json').read_text())
env={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME') and not k.startswith(('ORBIT_POC_','LD_'))}
env.update({k:'1' for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','BLIS_NUM_THREADS','GOTO_NUM_THREADS')});env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',LD_LIBRARY_PATH=freeze['environment']['LD_LIBRARY_PATH'])
argv=[py,'-s','-B',str(b/'source/scripts/analyze_nuisance_wholefit.py'),str(w),'--output',str(a/'checker.json')]
plan={'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'argv':argv,'cpu_affinity':sorted(os.sched_getaffinity(0)),'numerical_environment':{k:env[k] for k in ['LD_LIBRARY_PATH','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','BLIS_NUM_THREADS','GOTO_NUM_THREADS','PYTHONDONTWRITEBYTECODE','PYTHONNOUSERSITE']},'protected_pre':protected,'tool_pins':{str(p):h for p,h in tools.items()},'native_runs':0}
assert plan['cpu_affinity']==[4]
(a/'reproduction-plan.json').open('x').write(json.dumps(plan,indent=2,sort_keys=True)+'\n')
t=time.monotonic()
with (a/'stdout.log').open('x') as o,(a/'stderr.log').open('x') as e: result=subprocess.run(argv,env=env,cwd=b/'source',stdout=o,stderr=e)
post={p:sha(p) for p in protected}
for p,h in tools.items():assert sha(p)==h
record={'returncode':result.returncode,'elapsed_monotonic_seconds':time.monotonic()-t,'protected_unchanged':post==protected,'protected_post':post,'tool_pins_unchanged':True,'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'native_runs':0}
(a/'reproduction-execution.json').open('x').write(json.dumps(record,indent=2,sort_keys=True)+'\n')
assert post==protected
print(json.dumps({k:v for k,v in record.items() if k!='protected_post'}))
raise SystemExit(result.returncode)
