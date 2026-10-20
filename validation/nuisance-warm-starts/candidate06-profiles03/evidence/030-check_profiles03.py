from pathlib import Path
import hashlib,json,os,subprocess,sys
B=Path('/home/emper/orbit-nuisance-warmstarts');RUN=B/'profiles03';OUT=B/'profiles03-checks';SOURCE=B/'source-candidate06';CHECK=SOURCE/'scripts/check_nuisance_warm_profiles.py'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
f=json.loads((RUN/'freeze.json').read_text());assert sha(CHECK)==f['checker']['sha256'];assert (RUN/'run-result.json').exists()
OUT.mkdir(exist_ok=False);env={k:v for k,v in os.environ.items() if not k.startswith('ORBIT_POC_') and k not in ['PYTHONPATH','PYTHONHOME']};env.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1',LD_LIBRARY_PATH=str(B/'toolchain-01/lib'))
results=[]
for group in ['pulses','density','pulses-bias-priors']:
 def point(name):return RUN/(group+'--'+name)
 for name,paths,flags in [('inert-full',['disabled_source','cold_source_full'],['--inert']),('inert-clock',['disabled_source','cold_source_clock'],['--inert']),('warm-source-full',['cold_source_full','warm_source_full','cold_source_repeat_full'],[]),('warm-target-full',['cold_target_full','warm_target_full','cold_target_repeat_full'],[]),('warm-target-clock',['cold_target_full','warm_target_clock','cold_target_repeat_full'],[])]:
  assert sha(CHECK)==f['checker']['sha256'];output=OUT/(group+'--'+name+'.json');command=['/usr/bin/taskset','-c','0',sys.executable,'-s','-B',str(CHECK),*[str(point(p)) for p in paths],*flags,'--output',str(output)]
  r=subprocess.run(command,cwd=SOURCE,env=env,capture_output=True,text=True);(OUT/(group+'--'+name+'.log')).write_text(r.stdout+r.stderr)
  result={'name':group+'--'+name,'command':command,'returncode':r.returncode,'output':str(output),'sha256':sha(output) if output.exists() else None};results.append(result);print(json.dumps(result),flush=True)
with (B/'control/profiles03-check-execution-index.json').open('x') as out:json.dump({'schema':'orbit-poc-warm-profile-check-execution-index-v1','freeze_sha256':sha(RUN/'freeze.json'),'checker_sha256':sha(CHECK),'runner_sha256':sha(__file__),'checks':results},out,indent=2,sort_keys=True)
